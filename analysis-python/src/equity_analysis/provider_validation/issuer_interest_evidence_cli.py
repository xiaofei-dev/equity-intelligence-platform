from __future__ import annotations

import argparse
import gzip
import json
import os
import time
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from equity_analysis.provider_validation.cli import _load_local_environment
from equity_analysis.provider_validation.current_factor_windows_v1 import (
    _cached_sec_inputs,
)
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
from equity_analysis.provider_validation.objective_rating_semantics_audit import (
    _load_response,
    _verify_event,
)
from equity_analysis.provider_validation.sec_filing_evidence import (
    build_filing_evidence,
    bytes_sha256,
    filing_archive_root,
    select_filing_documents,
)

CANARY_SYMBOLS = ("AMAT", "CSCO", "FIX")
LIVE_CONFIRMATION = "EXECUTE_BOUNDED_SEC_ISSUER_INTEREST_CANARY"
PHYSICAL_ATTEMPT_CEILING = 100
MAX_RETRIES = 0
REQUEST_DELAY_SECONDS = 0.2
PREFLIGHT_SCHEMA_VERSION = "sec-issuer-interest-evidence-preflight-v1.0.0"
RUN_SCHEMA_VERSION = "sec-issuer-interest-evidence-run-v1.0.0"


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def _decode_response(response) -> bytes:
    body = response.read()
    encoding = str(getattr(response, "headers", {}).get("Content-Encoding", "")).lower()
    return gzip.decompress(body) if encoding == "gzip" else body


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


def _request_identity(
    *,
    symbol: str,
    endpoint: str,
    url: str,
) -> str:
    return canonical_hash(
        {
            "provider": "sec_edgar",
            "symbol": symbol,
            "endpoint": endpoint,
            "path": urlparse(url).path.lower(),
        }
    )


def _response_body_from_event(
    event: dict[str, Any],
    *,
    repository_root: Path,
) -> bytes:
    path = Path(event["detail"]["responseCheckpointPath"])
    if not path.is_absolute():
        path = repository_root / path
    body = path.read_bytes()
    if _file_sha256(path) != event["detail"]["responseContentHash"]:
        raise ValueError(f"CACHED_RESPONSE_HASH_MISMATCH[{path}]")
    if body.startswith(b"\x1f\x8b"):
        body = gzip.decompress(body)
    return body


def _cached_responses(
    repository_root: Path,
) -> dict[str, dict[str, Any]]:
    roots = (
        repository_root
        / "storage/provider-validation/sec-filing-evidence/physical-request-journals",
        repository_root
        / "storage/provider-validation/sec-issuer-interest-evidence/"
        "physical-request-journals",
    )
    result = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*-COMPLETED.json")):
            event = _verify_event(path)
            _response_body_from_event(event, repository_root=repository_root)
            result[event["requestIdentity"]] = event
    return result


def _evidence_by_accession(
    *,
    repository_root: Path,
    symbol: str,
) -> dict[str, dict[str, Any]]:
    root = (
        repository_root
        / "storage/provider-validation/scoring-inputs-v4/filing-evidence"
        / symbol
    )
    result = {}
    if not root.exists():
        return result
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected = payload["contentHash"]
        actual = canonical_hash(
            {key: value for key, value in payload.items() if key != "contentHash"}
        )
        if actual != expected:
            raise ValueError(f"CACHED_FILING_EVIDENCE_HASH_MISMATCH[{path}]")
        result[payload["accession"]] = {
            "path": path,
            "payload": payload,
        }
    return result


def _accessions_from_audit(
    audit: dict[str, Any],
) -> dict[str, tuple[str, ...]]:
    result = {}
    for record in audit["records"]:
        if record["symbol"] not in CANARY_SYMBOLS:
            continue
        sets = [
            tuple(item["accessions"])
            for item in record["minimumMissingEvidence"]
            if item.get("accessions")
        ]
        if len(sets) != 1 or len(sets[0]) != 6:
            raise ValueError(
                f"ISSUER_INTEREST_ACCESSION_SET_NOT_FROZEN[{record['symbol']}]"
            )
        result[record["symbol"]] = sets[0]
    if tuple(result) != CANARY_SYMBOLS:
        raise ValueError("ISSUER_INTEREST_CANARY_SYMBOL_SET_DRIFT")
    return result


def _filing_metadata(
    submissions: dict[str, Any],
    accession: str,
) -> dict[str, str]:
    recent = submissions.get("filings", {}).get("recent", {})
    rows = zip(
        recent.get("accessionNumber", ()),
        recent.get("form", ()),
        recent.get("filingDate", ()),
        recent.get("acceptanceDateTime", ()),
        recent.get("primaryDocument", ()),
        strict=False,
    )
    matches = [
        {
            "accession": str(candidate),
            "form": str(form),
            "filed": str(filed),
            "accepted": _accepted_iso(str(accepted)),
            "primaryDocument": str(primary),
        }
        for candidate, form, filed, accepted, primary in rows
        if str(candidate) == accession
    ]
    if len(matches) != 1:
        raise ValueError(f"SEC_ACCESSION_METADATA_NOT_UNIQUE[{accession}]")
    if matches[0]["form"].removesuffix("/A") not in {"10-K", "10-Q"}:
        raise ValueError(f"SEC_ACCESSION_FORM_NOT_ELIGIBLE[{accession}]")
    return matches[0]


def _cached_or_missing_request(
    *,
    cached: dict[str, dict[str, Any]],
    symbol: str,
    endpoint: str,
    url: str,
) -> dict[str, Any]:
    identity = _request_identity(symbol=symbol, endpoint=endpoint, url=url)
    event = cached.get(identity)
    return {
        "endpoint": endpoint,
        "urlPath": urlparse(url).path,
        "requestIdentity": identity,
        "cacheStatus": "HASH_VERIFIED_REPLAY" if event else "NEEDS_HTTP",
        "cachedResponseHash": (
            event["detail"]["responseContentHash"] if event else None
        ),
    }


def build_preflight(
    *,
    run_id: str,
    repository_root: Path,
    audit_path: Path,
) -> dict[str, Any]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit["artifactContentHash"] != canonical_hash(
        {key: value for key, value in audit.items() if key != "artifactContentHash"}
    ):
        raise ValueError("ISSUER_INTEREST_AUDIT_HASH_MISMATCH")
    accessions_by_symbol = _accessions_from_audit(audit)
    aggregate = json.loads(
        (
            repository_root
            / "docs/generated/formula-ready-243-final-aggregate-v1.json"
        ).read_text(encoding="utf-8")
    )
    run_ids = tuple(item["runId"] for item in aggregate["componentReports"])
    ticker_to_cik, cached_sec = _cached_sec_inputs(
        repository_root=repository_root,
        run_ids=run_ids,
    )
    cached_http = _cached_responses(repository_root)
    entries = []
    endpoint_counts = Counter()
    replay_counts = Counter()
    for symbol in CANARY_SYMBOLS:
        cik = ticker_to_cik[symbol]
        submissions_event = cached_sec[("submissions", cik)]
        submissions = _load_response(submissions_event, repository_root)
        evidence = _evidence_by_accession(
            repository_root=repository_root,
            symbol=symbol,
        )
        for accession in accessions_by_symbol[symbol]:
            filing = _filing_metadata(submissions, accession)
            if accession in evidence:
                entries.append(
                    {
                        "symbol": symbol,
                        "cik": cik,
                        "accession": accession,
                        "filing": filing,
                        "status": "SKIP_COMPLETE_EVIDENCE",
                        "evidencePath": evidence[accession]["path"].relative_to(
                            repository_root
                        ).as_posix(),
                        "evidenceContentHash": evidence[accession]["payload"][
                            "contentHash"
                        ],
                        "requests": [],
                    }
                )
                continue
            root = filing_archive_root(cik, accession)
            index_url = urljoin(root, "index.json")
            index_request = _cached_or_missing_request(
                cached=cached_http,
                symbol=symbol,
                endpoint="filing_index",
                url=index_url,
            )
            requests = [index_request]
            if index_request["cacheStatus"] == "HASH_VERIFIED_REPLAY":
                index_event = cached_http[index_request["requestIdentity"]]
                documents = select_filing_documents(
                    _json(
                        _response_body_from_event(
                            index_event,
                            repository_root=repository_root,
                        ),
                        f"SEC_FILING_INDEX_PARSE_FAILED[{accession}]",
                    ),
                    primary_document=filing["primaryDocument"],
                )
                for category, endpoint in (
                    ("primary", "inline_xbrl"),
                    ("presentation", "presentation_linkbase"),
                    ("labels", "label_linkbase"),
                ):
                    requests.append(
                        _cached_or_missing_request(
                            cached=cached_http,
                            symbol=symbol,
                            endpoint=endpoint,
                            url=urljoin(root, documents[category]),
                        )
                    )
            else:
                for endpoint in (
                    "inline_xbrl",
                    "presentation_linkbase",
                    "label_linkbase",
                ):
                    requests.append(
                        {
                            "endpoint": endpoint,
                            "urlPath": (
                                f"{urlparse(root).path}<resolved-from-index>"
                            ),
                            "requestIdentity": None,
                            "cacheStatus": "NEEDS_HTTP_AFTER_INDEX",
                            "cachedResponseHash": None,
                        }
                    )
            for request in requests:
                if request["cacheStatus"].startswith("NEEDS_HTTP"):
                    endpoint_counts[request["endpoint"]] += 1
                else:
                    replay_counts[request["endpoint"]] += 1
            entries.append(
                {
                    "symbol": symbol,
                    "cik": cik,
                    "accession": accession,
                    "filing": filing,
                    "status": "NEEDS_EVIDENCE_COLLECTION",
                    "submissionsSourceHash": submissions_event["detail"][
                        "responseContentHash"
                    ],
                    "requests": requests,
                }
            )
    total = sum(endpoint_counts.values())
    if total > PHYSICAL_ATTEMPT_CEILING:
        raise ValueError("SEC_ISSUER_INTEREST_PREFLIGHT_EXCEEDS_CEILING")
    generated = repository_root / "docs/generated"
    paths = {
        "preflight": generated
        / f"sec-issuer-interest-evidence-{run_id}-preflight.json",
        "report": generated / f"sec-issuer-interest-evidence-{run_id}.json",
        "diagnostics": generated
        / f"sec-issuer-interest-evidence-{run_id}-diagnostics.json",
        "checkpoint": generated
        / f"sec-issuer-interest-evidence-{run_id}-checkpoint.json",
    }
    for path in paths.values():
        if path.exists():
            raise FileExistsError(f"IMMUTABLE_OUTPUT_EXISTS[{path}]")
    preflight = {
        "schemaVersion": PREFLIGHT_SCHEMA_VERSION,
        "runId": run_id,
        "provider": "sec_edgar",
        "symbols": list(CANARY_SYMBOLS),
        "frozenSourceAuditPath": audit_path.relative_to(
            repository_root
        ).as_posix(),
        "frozenSourceAuditSha256": _file_sha256(audit_path),
        "frozenSourceAuditContentHash": audit["artifactContentHash"],
        "accessionsBySymbol": {
            symbol: list(accessions)
            for symbol, accessions in accessions_by_symbol.items()
        },
        "accessionCount": sum(map(len, accessions_by_symbol.values())),
        "endpointPlan": dict(sorted(endpoint_counts.items())),
        "hashVerifiedReplayPlan": dict(sorted(replay_counts.items())),
        "plannedPhysicalHttpAttempts": total,
        "maximumPhysicalHttpAttempts": PHYSICAL_ATTEMPT_CEILING,
        "maximumRetries": MAX_RETRIES,
        "requestDelaySeconds": REQUEST_DELAY_SECONDS,
        "submissionsRequests": 0,
        "companyFactsRequests": 0,
        "eodhdRequests": 0,
        "entries": entries,
        "paths": {
            key: path.relative_to(repository_root).as_posix()
            for key, path in paths.items()
        },
        "immutableOutputs": True,
        "networkAccessedDuringPreflight": False,
    }
    preflight["contentHash"] = canonical_hash(preflight)
    return preflight


def _classify_factory(url_symbols: dict[str, str]):
    def classify(request) -> tuple[str, str, str, int]:
        url = request.full_url
        path = urlparse(url).path.lower()
        symbol = url_symbols[url]
        if path.endswith("/index.json"):
            endpoint = "filing_index"
        elif path.endswith("_pre.xml"):
            endpoint = "presentation_linkbase"
        elif path.endswith("_lab.xml"):
            endpoint = "label_linkbase"
        else:
            endpoint = "inline_xbrl"
        return (
            symbol,
            endpoint,
            _request_identity(symbol=symbol, endpoint=endpoint, url=url),
            1,
        )

    return classify


def _fetch(
    opener: JournaledOpener,
    *,
    url: str,
    symbol: str,
    user_agent: str,
    url_symbols: dict[str, str],
) -> bytes:
    url_symbols[url] = symbol
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


def _fetch_or_replay(
    opener: JournaledOpener,
    *,
    cached: dict[str, dict[str, Any]],
    endpoint: str,
    url: str,
    symbol: str,
    user_agent: str,
    url_symbols: dict[str, str],
    repository_root: Path,
) -> tuple[bytes, str, str]:
    identity = _request_identity(symbol=symbol, endpoint=endpoint, url=url)
    event = cached.get(identity)
    if event:
        body = _response_body_from_event(event, repository_root=repository_root)
        return body, "HASH_VERIFIED_REPLAY", event["detail"]["responseContentHash"]
    body = _fetch(
        opener,
        url=url,
        symbol=symbol,
        user_agent=user_agent,
        url_symbols=url_symbols,
    )
    return body, "PHYSICAL_HTTP", bytes_sha256(body)


def execute_canary(
    *,
    repository_root: Path,
    preflight: dict[str, Any],
    user_agent: str,
) -> dict[str, Any]:
    run_id = preflight["runId"]
    journal_root = (
        repository_root
        / "storage/provider-validation/sec-issuer-interest-evidence/"
        "physical-request-journals"
    )
    journal = PhysicalRequestJournal(journal_root, run_id)
    journal.preflight(preflight)
    cached = _cached_responses(repository_root)
    url_symbols: dict[str, str] = {}
    opener = JournaledOpener(
        urlopen,
        journal,
        request_classifier=_classify_factory(url_symbols),
        physical_attempt_ceiling=PHYSICAL_ATTEMPT_CEILING,
        configured_weight_ceiling=PHYSICAL_ATTEMPT_CEILING,
    )
    lock_path = (
        repository_root
        / "storage/provider-validation/sec-issuer-interest-evidence/"
        ".sec-issuer-interest-evidence.lock"
    )
    evidence_root = (
        repository_root
        / "storage/provider-validation/scoring-inputs-v4/filing-evidence"
    )
    ingested_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    records = []
    endpoint_modes = Counter()
    with ExecutionLease(lock_path, run_id):
        try:
            for entry in preflight["entries"]:
                symbol = entry["symbol"]
                accession = entry["accession"]
                if entry["status"] == "SKIP_COMPLETE_EVIDENCE":
                    records.append(
                        {
                            "symbol": symbol,
                            "accession": accession,
                            "status": "SKIPPED_HASH_VERIFIED_EVIDENCE",
                            "evidencePath": entry["evidencePath"],
                            "evidenceContentHash": entry["evidenceContentHash"],
                            "endpointModes": {},
                        }
                    )
                    continue
                filing = entry["filing"]
                cik = entry["cik"]
                root = filing_archive_root(cik, accession)
                index_url = urljoin(root, "index.json")
                index_body, mode, index_hash = _fetch_or_replay(
                    opener,
                    cached=cached,
                    endpoint="filing_index",
                    url=index_url,
                    symbol=symbol,
                    user_agent=user_agent,
                    url_symbols=url_symbols,
                    repository_root=repository_root,
                )
                endpoint_modes[f"filing_index:{mode}"] += 1
                documents = select_filing_documents(
                    _json(
                        index_body,
                        f"SEC_FILING_INDEX_PARSE_FAILED[{accession}]",
                    ),
                    primary_document=filing["primaryDocument"],
                )
                bodies = {}
                hashes = {"filingIndex": index_hash}
                modes = {"filing_index": mode}
                for category, endpoint in (
                    ("primary", "inline_xbrl"),
                    ("presentation", "presentation_linkbase"),
                    ("labels", "label_linkbase"),
                ):
                    body, mode, content_hash = _fetch_or_replay(
                        opener,
                        cached=cached,
                        endpoint=endpoint,
                        url=urljoin(root, documents[category]),
                        symbol=symbol,
                        user_agent=user_agent,
                        url_symbols=url_symbols,
                        repository_root=repository_root,
                    )
                    bodies[category] = body
                    hashes[
                        {
                            "primary": "filing",
                            "presentation": "presentation",
                            "labels": "labels",
                        }[category]
                    ] = content_hash
                    modes[endpoint] = mode
                    endpoint_modes[f"{endpoint}:{mode}"] += 1
                evidence = build_filing_evidence(
                    symbol=symbol,
                    cik=cik,
                    filing=filing,
                    source_references={
                        "submissions": f"sec-edgar:submissions:CIK{cik}",
                        "filingIndex": (
                            f"sec-edgar:filing:{accession}:index"
                        ),
                        "filing": f"sec-edgar:filing:{accession}:primary",
                        "presentation": (
                            f"sec-edgar:filing:{accession}:presentation"
                        ),
                        "labels": f"sec-edgar:filing:{accession}:labels",
                    },
                    source_hashes={
                        "submissions": entry["submissionsSourceHash"],
                        **hashes,
                    },
                    inline_document=bodies["primary"],
                    presentation_document=bodies["presentation"],
                    label_document=bodies["labels"],
                    ingested_at=ingested_at,
                )
                path = (
                    evidence_root / symbol / f"{evidence['contentHash']}.json"
                )
                write_immutable_json(path, evidence)
                records.append(
                    {
                        "symbol": symbol,
                        "accession": accession,
                        "status": "EVIDENCE_COLLECTED",
                        "evidencePath": path.relative_to(
                            repository_root
                        ).as_posix(),
                        "evidenceContentHash": evidence["contentHash"],
                        "endpointModes": modes,
                        "sourceHashes": hashes,
                        "interestEvidenceCount": len(
                            evidence["interestEvidence"]
                        ),
                    }
                )
        except Exception as error:
            journal.finalize(
                "ABORTED",
                {
                    "errorCode": type(error).__name__.upper(),
                    "completedAccessions": [
                        item["accession"] for item in records
                    ],
                    "physicalAttempts": opener.physical_attempts,
                },
            )
            raise
        journal.finalize(
            "COMPLETE",
            {
                "completedAccessions": [item["accession"] for item in records],
                "physicalAttempts": opener.physical_attempts,
            },
        )
    return {
        "artifactType": "SEC_ISSUER_INTEREST_EVIDENCE_CANARY_REPORT",
        "schemaVersion": RUN_SCHEMA_VERSION,
        "runId": run_id,
        "preflightContentHash": preflight["contentHash"],
        "symbols": preflight["symbols"],
        "accessionCount": preflight["accessionCount"],
        "status": "PASS",
        "physicalHttpAttempts": opener.physical_attempts,
        "physicalAttemptsByEndpoint": opener.physical_attempts_by_endpoint,
        "configuredLocalWeight": opener.configured_weight,
        "maximumRetries": MAX_RETRIES,
        "endpointModes": dict(sorted(endpoint_modes.items())),
        "records": records,
        "eodhdRequests": 0,
        "submissionsRequests": 0,
        "companyFactsRequests": 0,
        "algorithmScoringExecuted": False,
        "forwardValidationExecuted": False,
        "rawFilingValuesIncluded": False,
    }


def _write_run_artifacts(
    *,
    repository_root: Path,
    preflight: dict[str, Any],
    report: dict[str, Any],
) -> None:
    report["artifactContentHash"] = canonical_hash(report)
    report_path = repository_root / preflight["paths"]["report"]
    write_immutable_json(report_path, report)
    diagnostics = {
        "artifactType": "SEC_ISSUER_INTEREST_EVIDENCE_CANARY_DIAGNOSTICS",
        "schemaVersion": "sec-issuer-interest-evidence-diagnostics-v1.0.0",
        "runId": preflight["runId"],
        "reportPath": preflight["paths"]["report"],
        "reportSha256": _file_sha256(report_path),
        "reportContentHash": report["artifactContentHash"],
        "records": report["records"],
        "rawFilingValuesIncluded": False,
    }
    diagnostics["artifactContentHash"] = canonical_hash(diagnostics)
    write_immutable_json(
        repository_root / preflight["paths"]["diagnostics"],
        diagnostics,
    )
    checkpoint = {
        "artifactType": "SEC_ISSUER_INTEREST_EVIDENCE_CANARY_CHECKPOINT",
        "schemaVersion": "sec-issuer-interest-evidence-checkpoint-v1.0.0",
        "runId": preflight["runId"],
        "completedAccessions": [
            {
                "symbol": item["symbol"],
                "accession": item["accession"],
                "evidenceContentHash": item["evidenceContentHash"],
            }
            for item in report["records"]
        ],
        "reportPath": preflight["paths"]["report"],
        "reportContentHash": report["artifactContentHash"],
    }
    checkpoint["artifactContentHash"] = canonical_hash(checkpoint)
    write_immutable_json(
        repository_root / preflight["paths"]["checkpoint"],
        checkpoint,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect bounded SEC issuer interest transition evidence."
    )
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--confirmation", default="")
    arguments = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[4]
    run_id = new_run_id()
    audit_path = (
        repository_root
        / "docs/generated/sec-issuer-interest-consistency-audit-v1-3.json"
    )
    preflight = build_preflight(
        run_id=run_id,
        repository_root=repository_root,
        audit_path=audit_path,
    )
    preflight_path = repository_root / preflight["paths"]["preflight"]
    write_immutable_json(preflight_path, preflight)
    print(json.dumps(preflight, indent=2))
    if not arguments.execute_live:
        return 0
    if arguments.confirmation != LIVE_CONFIRMATION:
        raise SystemExit("Explicit SEC issuer-interest confirmation is required")
    environment = _load_local_environment(repository_root_env_path())
    user_agent = os.environ.get("SEC_USER_AGENT") or environment.get(
        "SEC_USER_AGENT",
        "",
    )
    if not user_agent:
        raise SystemExit("SEC_USER_AGENT is required before network access")
    report = execute_canary(
        repository_root=repository_root,
        preflight=preflight,
        user_agent=user_agent,
    )
    _write_run_artifacts(
        repository_root=repository_root,
        preflight=preflight,
        report=report,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
