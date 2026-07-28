from __future__ import annotations

import argparse
import gzip
import json
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from equity_analysis.provider_validation.cli import _load_local_environment
from equity_analysis.provider_validation.execution_safety import (
    ExecutionLease,
    JournaledOpener,
    PhysicalRequestJournal,
    repository_root_env_path,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    new_run_id,
    write_immutable_json,
)
from equity_analysis.provider_validation.sec_filing_evidence import (
    SEC_FILING_EVIDENCE_SCHEMA_VERSION,
    build_filing_evidence,
    bytes_sha256,
    filing_archive_root,
    select_filing_documents,
    select_latest_annual_filing,
)

CANARY_SYMBOLS = ("AAPL", "CAT", "JNJ", "NVDA", "XEL")
CACHE_MISSING_SYMBOLS = frozenset({"A", "AAPL", "ACN", "ADBE", "ADI", "CAT", "JNJ"})
LIVE_CONFIRMATION = "EXECUTE_BOUNDED_SEC_FILING_EVIDENCE_CANARY"
PHYSICAL_ATTEMPT_CEILING = 50
REQUEST_DELAY_SECONDS = 0.2
RUN_SCHEMA_VERSION = "sec-filing-evidence-run-v1.0.0"
PREFLIGHT_SCHEMA_VERSION = "sec-filing-evidence-preflight-v1.0.0"


def _decode_response(response) -> bytes:
    body = response.read()
    encoding = str(getattr(response, "headers", {}).get("Content-Encoding", "")).lower()
    return gzip.decompress(body) if encoding == "gzip" else body


def _fetch(
    opener: JournaledOpener,
    url: str,
    user_agent: str,
) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip",
            "Accept": "application/json,text/html,application/xml,text/xml,*/*",
        },
    )
    with opener(request, timeout=30) as response:
        body = _decode_response(response)
    time.sleep(REQUEST_DELAY_SECONDS)
    return body


def _json(body: bytes, error_code: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(error_code) from error


def _accepted_iso(raw: str) -> str:
    if raw.endswith("Z") or "+" in raw:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        parsed = datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _ticker_map(payload: Any) -> dict[str, str]:
    rows = payload.values() if isinstance(payload, dict) else payload
    return {
        str(row["ticker"]).upper(): f"{int(row['cik_str']):010d}"
        for row in rows
        if isinstance(row, dict) and row.get("ticker") and row.get("cik_str") is not None
    }


def build_preflight(
    *,
    run_id: str,
    repository_root: Path,
    symbols: tuple[str, ...] = CANARY_SYMBOLS,
) -> dict[str, Any]:
    if len(symbols) > 5 or len(set(symbols)) != len(symbols):
        raise ValueError("SEC_CANARY_SYMBOL_SET_INVALID")
    missing = sorted(set(symbols) & CACHE_MISSING_SYMBOLS)
    planned = {
        "ticker_mapping": 1,
        "submissions": len(symbols),
        "company_facts": len(missing),
        "filing_index": len(symbols),
        "inline_xbrl": len(symbols),
        "presentation_linkbase": len(symbols),
        "label_linkbase": len(symbols),
    }
    total = sum(planned.values())
    if total > PHYSICAL_ATTEMPT_CEILING:
        raise ValueError("SEC_CANARY_PREFLIGHT_EXCEEDS_ATTEMPT_CEILING")
    report = repository_root / "docs/generated" / f"sec-filing-evidence-{run_id}.json"
    diagnostics = (
        repository_root
        / "docs/generated"
        / f"sec-filing-evidence-{run_id}-diagnostics.json"
    )
    checkpoint = (
        repository_root
        / "docs/generated"
        / f"sec-filing-evidence-{run_id}-checkpoint.json"
    )
    for path in (report, diagnostics, checkpoint):
        if path.exists():
            raise FileExistsError(f"IMMUTABLE_OUTPUT_EXISTS[{path}]")
    payload = {
        "schemaVersion": PREFLIGHT_SCHEMA_VERSION,
        "runId": run_id,
        "provider": "sec_edgar",
        "symbols": list(symbols),
        "cacheMissingSymbols": missing,
        "endpointPlan": planned,
        "plannedPhysicalHttpAttempts": total,
        "maximumPhysicalHttpAttempts": PHYSICAL_ATTEMPT_CEILING,
        "maximumRetries": 0,
        "requestDelaySeconds": REQUEST_DELAY_SECONDS,
        "officialSecSourcesOnly": True,
        "eodhdRequests": 0,
        "reportPath": report.relative_to(repository_root).as_posix(),
        "diagnosticsPath": diagnostics.relative_to(repository_root).as_posix(),
        "checkpointPath": checkpoint.relative_to(repository_root).as_posix(),
        "immutableOutputs": True,
    }
    payload["contentHash"] = canonical_hash(payload)
    return payload


def _classify_factory(url_symbols: dict[str, str]):
    def classify(request) -> tuple[str, str, str, int]:
        url = request.full_url
        path = urlparse(url).path.lower()
        symbol = url_symbols.get(url, "SEC_GLOBAL")
        if path.endswith("/company_tickers.json"):
            endpoint = "ticker_mapping"
        elif "/submissions/" in path:
            endpoint = "submissions"
        elif "/companyfacts/" in path:
            endpoint = "company_facts"
        elif path.endswith("/index.json"):
            endpoint = "filing_index"
        elif path.endswith("_pre.xml"):
            endpoint = "presentation_linkbase"
        elif path.endswith("_lab.xml"):
            endpoint = "label_linkbase"
        else:
            endpoint = "inline_xbrl"
        identity = canonical_hash(
            {
                "provider": "sec_edgar",
                "symbol": symbol,
                "endpoint": endpoint,
                "path": path,
            }
        )
        return symbol, endpoint, identity, 1

    return classify


def execute_canary(
    *,
    repository_root: Path,
    run_id: str,
    user_agent: str,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    journal_root = (
        repository_root
        / "storage/provider-validation/sec-filing-evidence/physical-request-journals"
    )
    response_journal = PhysicalRequestJournal(journal_root, run_id)
    response_journal.preflight(preflight)
    url_symbols: dict[str, str] = {}
    opener = JournaledOpener(
        urlopen,
        response_journal,
        request_classifier=_classify_factory(url_symbols),
        physical_attempt_ceiling=PHYSICAL_ATTEMPT_CEILING,
        configured_weight_ceiling=PHYSICAL_ATTEMPT_CEILING,
    )
    lock_path = (
        repository_root
        / "storage/provider-validation/sec-filing-evidence/.sec-filing-evidence.lock"
    )
    storage_root = repository_root / "storage/provider-validation/scoring-inputs-v4"
    evidence_root = storage_root / "filing-evidence"
    ingested_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    records = []
    failure: str | None = None
    with ExecutionLease(lock_path, run_id):
        try:
            ticker_url = "https://www.sec.gov/files/company_tickers.json"
            url_symbols[ticker_url] = "SEC_GLOBAL"
            ticker_payload = _json(
                _fetch(opener, ticker_url, user_agent),
                "SEC_TICKER_MAPPING_PARSE_FAILED",
            )
            ticker_map = _ticker_map(ticker_payload)
            for symbol in preflight["symbols"]:
                cik = ticker_map.get(symbol)
                if not cik:
                    raise RuntimeError(f"SEC_TICKER_CIK_NOT_FOUND[{symbol}]")
                submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
                url_symbols[submissions_url] = symbol
                submissions_body = _fetch(opener, submissions_url, user_agent)
                submissions = _json(
                    submissions_body,
                    f"SEC_SUBMISSIONS_PARSE_FAILED[{symbol}]",
                )
                filing = select_latest_annual_filing(submissions)
                filing["accepted"] = _accepted_iso(filing["accepted"])
                company_facts_hash = None
                if symbol in CACHE_MISSING_SYMBOLS:
                    facts_url = (
                        "https://data.sec.gov/api/xbrl/companyfacts/"
                        f"CIK{cik}.json"
                    )
                    url_symbols[facts_url] = symbol
                    company_facts_body = _fetch(opener, facts_url, user_agent)
                    _json(
                        company_facts_body,
                        f"SEC_COMPANY_FACTS_PARSE_FAILED[{symbol}]",
                    )
                    company_facts_hash = bytes_sha256(company_facts_body)

                root = filing_archive_root(cik, filing["accession"])
                index_url = urljoin(root, "index.json")
                url_symbols[index_url] = symbol
                index_payload = _json(
                    _fetch(opener, index_url, user_agent),
                    f"SEC_FILING_INDEX_PARSE_FAILED[{symbol}]",
                )
                documents = select_filing_documents(
                    index_payload,
                    primary_document=filing["primaryDocument"],
                )
                bodies = {}
                for category, filename in documents.items():
                    url = urljoin(root, filename)
                    url_symbols[url] = symbol
                    bodies[category] = _fetch(opener, url, user_agent)
                source_hashes = {
                    "submissions": bytes_sha256(submissions_body),
                    "filing": bytes_sha256(bodies["primary"]),
                    "presentation": bytes_sha256(bodies["presentation"]),
                    "labels": bytes_sha256(bodies["labels"]),
                }
                if company_facts_hash:
                    source_hashes["companyFacts"] = company_facts_hash
                evidence = build_filing_evidence(
                    symbol=symbol,
                    cik=cik,
                    filing=filing,
                    source_references={
                        "submissions": f"sec-edgar:submissions:CIK{cik}",
                        "filing": (
                            f"sec-edgar:filing:{filing['accession']}:primary"
                        ),
                        "presentation": (
                            f"sec-edgar:filing:{filing['accession']}:presentation"
                        ),
                        "labels": f"sec-edgar:filing:{filing['accession']}:labels",
                    },
                    source_hashes=source_hashes,
                    inline_document=bodies["primary"],
                    presentation_document=bodies["presentation"],
                    label_document=bodies["labels"],
                    ingested_at=ingested_at,
                )
                evidence_path = (
                    evidence_root / symbol / f"{evidence['contentHash']}.json"
                )
                write_immutable_json(evidence_path, evidence)
                strict_interest = any(
                    item["scope"]["acceptedAsStrictInterestExpense"]
                    for item in evidence["interestEvidence"]
                )
                records.append(
                    {
                        "symbol": symbol,
                        "status": "EVIDENCE_COLLECTED",
                        "entityId": f"CIK:{cik}",
                        "accession": filing["accession"],
                        "form": filing["form"],
                        "evidencePath": evidence_path.relative_to(
                            repository_root
                        ).as_posix(),
                        "evidenceContentHash": evidence["contentHash"],
                        "strictInterestScopeProven": strict_interest,
                        "totalDebtProven": evidence["debtEvidence"][
                            "totalDebtAuthorized"
                        ],
                        "tradedClassIdentityProven": evidence[
                            "tradedClassEvidence"
                        ]["historicalMarketCapSharesAuthorized"],
                        "reasonCodes": [
                            code
                            for condition, code in (
                                (
                                    not strict_interest,
                                    "STRICT_INTEREST_SCOPE_NOT_PROVEN",
                                ),
                                (
                                    not evidence["debtEvidence"][
                                        "totalDebtAuthorized"
                                    ],
                                    "TOTAL_DEBT_COMPLETENESS_NOT_PROVEN",
                                ),
                                (
                                    not evidence["tradedClassEvidence"][
                                        "historicalMarketCapSharesAuthorized"
                                    ],
                                    "TRADED_CLASS_IDENTITY_NOT_PROVEN",
                                ),
                            )
                            if condition
                        ],
                    }
                )
        except Exception as error:
            failure = str(error)
            response_journal.finalize(
                "ABORTED",
                {
                    "sanitizedError": type(error).__name__.upper(),
                    "completedSymbols": [item["symbol"] for item in records],
                    "physicalAttempts": opener.physical_attempts,
                },
            )
            raise
        else:
            response_journal.finalize(
                "COMPLETE",
                {
                    "completedSymbols": [item["symbol"] for item in records],
                    "physicalAttempts": opener.physical_attempts,
                },
            )
    counts = Counter(
        reason
        for record in records
        for reason in record["reasonCodes"]
    )
    report = {
        "artifactType": "SEC_FILING_EVIDENCE_CANARY_REPORT",
        "schemaVersion": RUN_SCHEMA_VERSION,
        "evidenceSchemaVersion": SEC_FILING_EVIDENCE_SCHEMA_VERSION,
        "runId": run_id,
        "preflightContentHash": preflight["contentHash"],
        "symbols": preflight["symbols"],
        "status": "PASS" if failure is None else "SYSTEM_FAIL",
        "physicalHttpAttempts": opener.physical_attempts,
        "physicalAttemptsByEndpoint": opener.physical_attempts_by_endpoint,
        "configuredLocalWeight": opener.configured_weight,
        "maximumRetries": 0,
        "records": records,
        "reasonCounts": dict(sorted(counts.items())),
        "eodhdRequests": 0,
        "algorithmScoringExecuted": False,
        "forwardValidationExecuted": False,
        "rawFilingValuesIncluded": False,
    }
    report["artifactContentHash"] = canonical_hash(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect bounded official SEC filing presentation/context evidence."
    )
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--confirmation", default="")
    arguments = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[4]
    run_id = new_run_id()
    preflight = build_preflight(run_id=run_id, repository_root=repository_root)
    print(json.dumps(preflight, indent=2))
    if not arguments.execute_live:
        return
    if arguments.confirmation != LIVE_CONFIRMATION:
        raise SystemExit("Explicit SEC filing evidence confirmation is required")
    environment = _load_local_environment(repository_root_env_path())
    user_agent = os.environ.get("SEC_USER_AGENT") or environment.get(
        "SEC_USER_AGENT",
        "",
    )
    if not user_agent:
        raise SystemExit("SEC_USER_AGENT is required before network access")
    report = execute_canary(
        repository_root=repository_root,
        run_id=run_id,
        user_agent=user_agent,
        preflight=preflight,
    )
    output = repository_root / preflight["reportPath"]
    write_immutable_json(output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
