import argparse
import gzip
import json
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.market_data.eodhd import EODHD_FINANCIAL_FIELD_MAP
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)
from equity_analysis.provider_validation.sec_edgar import REQUIRED_TAG_GROUPS

CACHE_AUDIT_SCHEMA_VERSION = "provider-cache-semantic-audit-v1.2.0"
SEC_FIELD_MAP = {
    "revenue": "revenue",
    "operating_income": "operating_income",
    "net_income": "net_income",
    "diluted_shares": "diluted_weighted_average_shares",
    "interest_expense": "interest_expense",
    "cash": "cash_and_equivalents",
    "assets": "total_assets",
    "equity": "stockholders_equity",
    "operating_cash_flow": "operating_cash_flow",
    "capital_expenditure": "capital_expenditure",
}
DURATION_FIELDS = frozenset(
    {
        "capital_expenditure",
        "diluted_weighted_average_shares",
        "ebitda",
        "gross_profit",
        "income_tax",
        "interest_expense",
        "net_income",
        "operating_cash_flow",
        "operating_income",
        "pretax_income",
        "revenue",
    }
)
PUBLICATION_KEYS = frozenset(
    {
        "published_at",
        "publication_date",
        "provider_published_at",
        "last_updated",
        "updated_at",
        "timestamp",
    }
)
OBSERVATION_KEYS = frozenset({"date", "datetime", "period_end", "end"})


def _sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _load_response(event: dict[str, Any], repository_root: Path) -> Any:
    detail = event["detail"]
    path = repository_root / detail["responseCheckpointPath"]
    body = path.read_bytes()
    if _sha256_bytes(body) != detail["responseContentHash"]:
        raise ValueError(f"CACHE_RESPONSE_HASH_MISMATCH[{path}]")
    if body.startswith(b"\x1f\x8b"):
        body = gzip.decompress(body)
    return json.loads(body.decode("utf-8"))


def _verify_event(path: Path) -> dict[str, Any]:
    event = json.loads(path.read_text(encoding="utf-8"))
    expected = event.get("eventHash")
    if expected != canonical_hash(
        {key: value for key, value in event.items() if key != "eventHash"}
    ):
        raise ValueError(f"CACHE_EVENT_HASH_MISMATCH[{path}]")
    return event


def _ticker_cik_map(payload: Any) -> dict[str, str]:
    rows = payload.values() if isinstance(payload, dict) else payload
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = row.get("ticker")
        cik = row.get("cik_str")
        if ticker and cik is not None:
            result[str(ticker).upper()] = f"{int(cik):010d}"
    return result


def _financial_records(payload: dict[str, Any]):
    financials = payload.get("Financials", {})
    for statement in financials.values():
        if not isinstance(statement, dict):
            continue
        for period_type in ("quarterly", "yearly"):
            records = statement.get(period_type, {})
            values = records.values() if isinstance(records, dict) else records
            for record in values or ():
                if isinstance(record, dict):
                    yield period_type, record


def _increment_metadata(counter: Counter, record: dict[str, Any]) -> None:
    counter["recordsObserved"] += 1
    counter["periodStartPresent"] += int(
        any(key in record and record[key] not in (None, "") for key in ("start", "period_start"))
    )
    counter["periodEndPresent"] += int(
        any(
            key in record and record[key] not in (None, "")
            for key in ("end", "date", "period_end")
        )
    )
    counter["formPresent"] += int(bool(record.get("form")))
    counter["framePresent"] += int(bool(record.get("frame")))
    counter["accessionPresent"] += int(
        bool(record.get("accn") or record.get("accessionNumber"))
    )


def _audit_eodhd_fundamentals(
    payload: dict[str, Any],
    symbol: str,
    counters: dict[tuple[str, str, str], Counter],
) -> None:
    seen_fields = set()
    for period_type, record in _financial_records(payload):
        normalized_fields = {
            normalized
            for provider_field, normalized in EODHD_FINANCIAL_FIELD_MAP.items()
            if provider_field in record
        }
        for field in normalized_fields:
            key = ("eodhd", "fundamentals", field)
            _increment_metadata(counters[key], record)
            counters[key]["quarterlyBucketRecords"] += int(period_type == "quarterly")
            counters[key]["annualBucketRecords"] += int(period_type == "yearly")
            seen_fields.add(field)
    for field in seen_fields:
        counters[("eodhd", "fundamentals", field)][f"security:{symbol}"] = 1


def _audit_sec_company_facts(
    payload: dict[str, Any],
    symbol: str,
    counters: dict[tuple[str, str, str], Counter],
) -> None:
    facts = payload.get("facts", {}).get("us-gaap", {})
    seen_fields = set()
    for metric, tags in REQUIRED_TAG_GROUPS.items():
        field = SEC_FIELD_MAP.get(metric)
        if field is None:
            continue
        for tag in tags:
            concept = facts.get(tag, {})
            for entries in concept.get("units", {}).values():
                for record in entries:
                    if not isinstance(record, dict):
                        continue
                    key = ("sec_edgar", "company-facts", field)
                    _increment_metadata(counters[key], record)
                    counters[key]["fiscalPeriodPresent"] += int(bool(record.get("fp")))
                    seen_fields.add(field)
    for field in seen_fields:
        counters[("sec_edgar", "company-facts", field)][f"security:{symbol}"] = 1


def _audit_market_payload(payload: Any, endpoint: str) -> dict[str, Any]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        nested = payload.get("data")
        if isinstance(nested, list):
            rows = nested
        elif isinstance(nested, dict):
            rows = nested.values()
        else:
            rows = payload.values()
    else:
        rows = ()
    rows = [item for item in rows if isinstance(item, dict)]
    keys = {key for item in rows for key in item}
    return {
        "endpoint": endpoint,
        "responseCount": 1,
        "recordCount": len(rows),
        "observedDateFieldNames": sorted(keys & OBSERVATION_KEYS),
        "providerPublicationFieldNames": sorted(keys & PUBLICATION_KEYS),
        "effectiveMetadataPresent": bool(keys & OBSERVATION_KEYS),
        "providerPublicationMetadataPresent": bool(keys & PUBLICATION_KEYS),
    }


def build_cache_audit(
    *,
    aggregate_path: Path,
    aggregate_sha256: str,
    repository_root: Path,
) -> dict[str, Any]:
    if _sha256_bytes(aggregate_path.read_bytes()) != aggregate_sha256.upper():
        raise ValueError("CACHE_AUDIT_AGGREGATE_SHA_MISMATCH")
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    ready_symbols = {
        item["symbol"]
        for item in aggregate["securities"]
        if item["status"] == "FORMULA_READY"
    }
    run_ids = [item["runId"] for item in aggregate["componentReports"]]
    journal_root = (
        repository_root
        / "storage/provider-validation/scoring-inputs-v2/physical-request-journals"
    )
    events = []
    ticker_to_cik = {}
    for run_id in run_ids:
        for path in sorted((journal_root / run_id / "requests").rglob("*-COMPLETED.json")):
            event = _verify_event(path)
            events.append(event)
            if event["detail"]["endpointCategory"] == "ticker-mapping":
                ticker_to_cik.update(
                    _ticker_cik_map(_load_response(event, repository_root))
                )
    cik_to_symbols: dict[str, set[str]] = defaultdict(set)
    for symbol, cik in ticker_to_cik.items():
        if symbol in ready_symbols:
            cik_to_symbols[cik].add(symbol)
    counters: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    endpoint_counts = Counter()
    endpoint_symbols: dict[str, set[str]] = defaultdict(set)
    response_hashes = []
    market_audits: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        endpoint = event["detail"]["endpointCategory"]
        event_symbol = event["symbol"]
        symbols = (
            tuple(sorted(cik_to_symbols.get(event_symbol, ())))
            if endpoint in {"company-facts", "submissions"}
            else ((event_symbol,) if event_symbol in ready_symbols else ())
        )
        if not symbols:
            continue
        payload = _load_response(event, repository_root)
        endpoint_counts[endpoint] += 1
        endpoint_symbols[endpoint].update(symbols)
        response_hashes.append(
            {
                "runId": event["runId"],
                "symbols": list(symbols),
                "endpoint": endpoint,
                "responseContentHash": event["detail"]["responseContentHash"],
                "eventHash": event["eventHash"],
            }
        )
        if endpoint == "fundamentals":
            _audit_eodhd_fundamentals(payload, symbols[0], counters)
        elif endpoint == "company-facts":
            for symbol in symbols:
                _audit_sec_company_facts(payload, symbol, counters)
        elif endpoint in {"eod", "historical-market-cap"}:
            audit = _audit_market_payload(payload, endpoint)
            key = ("eodhd", endpoint)
            current = market_audits.setdefault(
                key,
                {
                    "provider": "eodhd",
                    "endpoint": endpoint,
                    "responseCount": 0,
                    "recordCount": 0,
                    "observedDateFieldNames": set(),
                    "providerPublicationFieldNames": set(),
                },
            )
            current["responseCount"] += 1
            current["recordCount"] += audit["recordCount"]
            current["observedDateFieldNames"].update(
                audit["observedDateFieldNames"]
            )
            current["providerPublicationFieldNames"].update(
                audit["providerPublicationFieldNames"]
            )

    field_audits = []
    for (provider, endpoint, field), counter in sorted(counters.items()):
        security_count = sum(
            value for key, value in counter.items() if key.startswith("security:")
        )
        metadata = {
            key: value
            for key, value in counter.items()
            if not key.startswith("security:")
        }
        duration_field = field in DURATION_FIELDS
        cached_support = (
            provider == "sec_edgar"
            and duration_field
            and metadata.get("periodStartPresent", 0) > 0
            and metadata.get("periodEndPresent", 0) > 0
            and metadata.get("formPresent", 0) > 0
            and metadata.get("accessionPresent", 0) > 0
        )
        field_audits.append(
            {
                "provider": provider,
                "endpoint": endpoint,
                "normalizedField": field,
                "securityCount": security_count,
                **metadata,
                "durationField": duration_field,
                "cachedOfflineDurationSemanticsSupported": cached_support,
                "remediationClass": (
                    "NEEDS_PARSER_EXTENSION"
                    if cached_support
                    else (
                        "NOT_REQUIRED_INSTANT_FIELD"
                        if not duration_field
                        else "NEEDS_PROVIDER_DOCUMENTATION_OR_NEW_SOURCE"
                    )
                ),
            }
        )
    market = []
    for item in market_audits.values():
        publication = sorted(item["providerPublicationFieldNames"])
        market.append(
            {
                **item,
                "observedDateFieldNames": sorted(item["observedDateFieldNames"]),
                "providerPublicationFieldNames": publication,
                "providerPublicationMetadataPresent": bool(publication),
                "historicalPitRemediationClass": (
                    "NEEDS_PARSER_EXTENSION"
                    if publication
                    else "NEEDS_PROVIDER_DOCUMENTATION_OR_NEW_SOURCE"
                ),
            }
        )
    payload = {
        "artifactType": "PROVIDER_CACHED_TRANSPORT_SEMANTIC_AUDIT",
        "schemaVersion": CACHE_AUDIT_SCHEMA_VERSION,
        "sourceAggregatePath": aggregate_path.as_posix(),
        "sourceAggregateSha256": aggregate_sha256.upper(),
        "formulaReadySecurityCount": len(ready_symbols),
        "verifiedResponseCount": len(response_hashes),
        "endpointResponseCounts": dict(sorted(endpoint_counts.items())),
        "endpointSecurityCounts": {
            endpoint: len(symbols)
            for endpoint, symbols in sorted(endpoint_symbols.items())
        },
        "securitiesWithoutCachedEodhdTransport": sorted(
            ready_symbols - endpoint_symbols["fundamentals"]
        ),
        "securitiesWithoutCachedSecCompanyFacts": sorted(
            ready_symbols - endpoint_symbols["company-facts"]
        ),
        "fieldAudits": field_audits,
        "marketEndpointAudits": sorted(market, key=lambda item: item["endpoint"]),
        "responseEvidence": response_hashes,
        "minimalLiveEndpoints": [],
        "liveRetestRequired": False,
        "liveRetestDecision": (
            "NONE_REPEATING_THE_SAME_ENDPOINTS_ADDS_NO_NEW_SEMANTIC_FIELDS"
        ),
        "remediationPolicy": {
            "cachedSecFactsWithStartEndFormAndAccession": "NEEDS_PARSER_EXTENSION",
            "eodhdDurationRecordsWithoutStartOrForm": (
                "NEEDS_PROVIDER_DOCUMENTATION_OR_NEW_SOURCE"
            ),
            "marketRecordsWithoutPublicationMetadata": (
                "NEEDS_PROVIDER_DOCUMENTATION_OR_NEW_SOURCE"
            ),
            "newSecConceptMappings": "NOT_AUTHORIZED_WITHOUT_EVIDENCE_AND_TESTS",
        },
        "networkRequestsExecuted": False,
        "objectiveRatingExecuted": False,
        "rawProviderValuesIncluded": False,
        "licensedResponsesIncluded": False,
        "credentialsIncluded": False,
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--aggregate-sha256", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit = build_cache_audit(
        aggregate_path=args.aggregate,
        aggregate_sha256=args.aggregate_sha256,
        repository_root=args.repository_root,
    )
    write_immutable_json(args.output, audit)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "verifiedResponseCount": audit["verifiedResponseCount"],
                "endpointResponseCounts": audit["endpointResponseCounts"],
                "liveRetestRequired": audit["liveRetestRequired"],
                "artifactContentHash": audit["artifactContentHash"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
