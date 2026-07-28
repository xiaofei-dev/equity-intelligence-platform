from __future__ import annotations

import argparse
import gzip
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

CURRENT_SNAPSHOT_SUPPLEMENT_VERSION = "eodhd-current-snapshot-supplement-v1.2.0"
CURRENT_SNAPSHOT_POLICY_VERSION = "objective-rating-current-snapshot-policy-v1.2.0"
DEFAULT_CUTOFF = datetime(2026, 7, 27, 23, 59, 59, tzinfo=UTC)


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def _verify_event(path: Path) -> dict[str, Any]:
    event = json.loads(path.read_text(encoding="utf-8"))
    expected = event.get("eventHash")
    actual = canonical_hash(
        {key: value for key, value in event.items() if key != "eventHash"}
    )
    if expected != actual:
        raise ValueError(f"CACHE_EVENT_HASH_MISMATCH[{path}]")
    return event


def _load_response(event: dict[str, Any], repository_root: Path) -> Any:
    path = repository_root / event["detail"]["responseCheckpointPath"]
    body = path.read_bytes()
    if _file_sha256(path) != event["detail"]["responseContentHash"]:
        raise ValueError(f"CACHE_RESPONSE_HASH_MISMATCH[{path}]")
    if body.startswith(b"\x1f\x8b"):
        body = gzip.decompress(body)
    return json.loads(body.decode("utf-8"), parse_float=Decimal)


def _intent_for_completed(path: Path) -> tuple[dict[str, Any], Path]:
    candidates = sorted(path.parent.glob("*-INTENT.json"))
    if len(candidates) != 1:
        raise ValueError(f"CACHE_INTENT_NOT_UNIQUE[{path}]")
    intent_path = candidates[0]
    return _verify_event(intent_path), intent_path


def _as_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _decimal_string(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    if not parsed.is_finite():
        return None
    return format(parsed, "f")


def _latest_balance_sheet_total_debt(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str] | None:
    balance_sheet = payload.get("Financials", {}).get("Balance_Sheet", {})
    candidates: list[tuple[str, dict[str, Any], str]] = []
    for bucket_name in ("quarterly", "yearly"):
        bucket = balance_sheet.get(bucket_name, {})
        rows = bucket.values() if isinstance(bucket, dict) else bucket
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            value = _decimal_string(row.get("shortLongTermDebtTotal"))
            period_end = row.get("date")
            if value is None or not period_end:
                continue
            candidates.append((str(period_end), row, bucket_name.upper()))
    if not candidates:
        return None
    _, row, bucket_name = max(candidates, key=lambda item: item[0])
    return row, bucket_name


def extract_current_snapshot_supplement(
    *,
    symbol: str,
    response: dict[str, Any],
    response_content_hash: str,
    retrieval_started_at: str,
    cutoff: datetime,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    highlights = response.get("Highlights", {})
    general = response.get("General", {})
    ebitda = _decimal_string(highlights.get("EBITDA"))
    market_cap = _decimal_string(highlights.get("MarketCapitalization"))
    enterprise_value = _decimal_string(
        response.get("Valuation", {}).get("EnterpriseValue")
    )
    debt = _latest_balance_sheet_total_debt(response)
    provider_updated_date = general.get("UpdatedAt")
    general_currency = general.get("CurrencyCode")
    if ebitda is None:
        reasons.append("HIGHLIGHTS_EBITDA_MISSING_OR_INVALID")
    if market_cap is None:
        reasons.append("HIGHLIGHTS_MARKET_CAPITALIZATION_MISSING_OR_INVALID")
    if enterprise_value is None:
        reasons.append("VALUATION_ENTERPRISE_VALUE_MISSING_OR_INVALID")
    if debt is None:
        reasons.append("SHORT_LONG_TERM_DEBT_TOTAL_MISSING_OR_INVALID")
    if not provider_updated_date:
        reasons.append("GENERAL_UPDATED_AT_MISSING")
    if not general_currency:
        reasons.append("GENERAL_CURRENCY_CODE_MISSING")
    retrieved_at = _as_utc(retrieval_started_at)
    if retrieved_at > cutoff:
        reasons.append("RETRIEVAL_AFTER_SEALED_CUTOFF")
    if reasons:
        return None, reasons

    debt_row, debt_bucket = debt
    statement_currency = (
        debt_row.get("currency_symbol")
        or response.get("Financials", {})
        .get("Balance_Sheet", {})
        .get("currency_symbol")
    )
    if not statement_currency:
        reasons.append("BALANCE_SHEET_CURRENCY_MISSING")
        return None, reasons

    cutoff_text = cutoff.isoformat().replace("+00:00", "Z")
    observations = [
        {
            "normalizedField": "ebitda",
            "providerPath": "Highlights.EBITDA",
            "value": ebitda,
            "unit": str(general_currency),
            "currency": str(general_currency),
            "periodType": "TTM",
            "effectiveAt": cutoff_text,
            "semanticPolicy": "OFFICIAL_HIGHLIGHTS_EBITDA_TTM",
        },
        {
            "normalizedField": "market_capitalization",
            "providerPath": "Highlights.MarketCapitalization",
            "value": market_cap,
            "unit": str(general_currency),
            "currency": str(general_currency),
            "periodType": "INSTANT_CURRENT_SNAPSHOT",
            "effectiveAt": cutoff_text,
            "semanticPolicy": "CURRENT_PROVIDER_MARKET_CAP",
        },
        {
            "normalizedField": "enterprise_value",
            "providerPath": "Valuation.EnterpriseValue",
            "value": enterprise_value,
            "unit": str(statement_currency),
            "currency": str(statement_currency),
            "periodType": "INSTANT_CURRENT_SNAPSHOT",
            "effectiveAt": cutoff_text,
            "semanticPolicy": (
                "OFFICIAL_PROVIDER_ENTERPRISE_VALUE_MATCHES_FROZEN_FORMULA"
            ),
        },
        {
            "normalizedField": "total_debt",
            "providerPath": (
                "Financials.Balance_Sheet."
                f"{debt_bucket.lower()}.*.shortLongTermDebtTotal"
            ),
            "value": _decimal_string(debt_row["shortLongTermDebtTotal"]),
            "unit": str(statement_currency),
            "currency": str(statement_currency),
            "periodType": "INSTANT",
            "periodEnd": str(debt_row["date"]),
            "filedAt": debt_row.get("filing_date"),
            "effectiveAt": cutoff_text,
            "semanticPolicy": "OFFICIAL_PROVIDER_NORMALIZED_TOTAL_DEBT",
        },
    ]
    minority_interest = _decimal_string(
        debt_row.get("noncontrollingInterestInConsolidatedEntity")
    )
    if minority_interest is not None:
        observations.append(
            {
                "normalizedField": "minority_interest",
                "providerPath": (
                    "Financials.Balance_Sheet."
                    f"{debt_bucket.lower()}.*."
                    "noncontrollingInterestInConsolidatedEntity"
                ),
                "value": minority_interest,
                "unit": str(statement_currency),
                "currency": str(statement_currency),
                "periodType": "INSTANT",
                "periodEnd": str(debt_row["date"]),
                "filedAt": debt_row.get("filing_date"),
                "effectiveAt": cutoff_text,
                "semanticPolicy": (
                    "OFFICIAL_BALANCE_SHEET_MINORITY_INTEREST_OBSERVATION"
                ),
            }
        )

    payload = {
        "schemaVersion": CURRENT_SNAPSHOT_SUPPLEMENT_VERSION,
        "policyVersion": CURRENT_SNAPSHOT_POLICY_VERSION,
        "scope": "CURRENT_SNAPSHOT_ONLY",
        "symbol": symbol,
        "asOfTime": cutoff_text,
        "providerUpdatedDate": str(provider_updated_date),
        "retrievalStartedAt": retrieved_at.isoformat().replace("+00:00", "Z"),
        "ingestedAt": cutoff_text,
        "ingestedAtEvidence": (
            "HASH_VERIFIED_COMPLETED_RESPONSE_PRESENT_BEFORE_SEALED_CUTOFF"
        ),
        "sourceResponseContentHash": response_content_hash,
        "observations": observations,
        "limitations": [
            "NO_FIELD_LEVEL_REVISION_IDENTITY",
            "NO_HISTORICAL_AVAILABILITY_CLAIM",
            "TOTAL_DEBT_COMPONENT_COMPOSITION_MAY_VARY_BY_ISSUER",
            "HIGHLIGHTS_EBITDA_HAS_NO_EXPLICIT_ECONOMIC_PERIOD_END",
            "ENTERPRISE_VALUE_COMPONENTS_ARE_NOT_EXPOSED_AS_SEPARATE_LINEAGE",
            (
                "MISSING_MINORITY_INTEREST_IS_NOT_ZERO_OR_NOT_APPLICABLE"
                if minority_interest is None
                else "MINORITY_INTEREST_IS_PROVIDER_NORMALIZED_CURRENT_ONLY"
            ),
        ],
    }
    payload["contentHash"] = canonical_hash(payload)
    return payload, []


def _write_controlled_payload(
    *,
    storage_root: Path,
    symbol: str,
    payload: dict[str, Any],
) -> tuple[Path, str]:
    content_hash = payload["contentHash"]
    path = storage_root / symbol / f"{content_hash}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if canonical_hash(
            {key: value for key, value in existing.items() if key != "contentHash"}
        ) != content_hash:
            raise ValueError(f"CONTROLLED_SUPPLEMENT_HASH_MISMATCH[{path}]")
        return path, content_hash
    write_immutable_json(path, payload)
    return path, content_hash


def build_current_snapshot_supplements(
    *,
    ready_symbols: set[str],
    repository_root: Path,
    storage_root: Path,
    cutoff: datetime = DEFAULT_CUTOFF,
) -> dict[str, Any]:
    journal_root = (
        repository_root
        / "storage/provider-validation/scoring-inputs-v2/physical-request-journals"
    )
    selected: dict[str, tuple[datetime, dict[str, Any], str]] = {}
    for path in sorted(journal_root.rglob("*-COMPLETED.json")):
        event = _verify_event(path)
        if (
            event["detail"]["endpointCategory"] != "fundamentals"
            or event["symbol"] not in ready_symbols
        ):
            continue
        intent, _ = _intent_for_completed(path)
        started_at = _as_utc(intent["detail"]["startedAt"])
        if started_at > cutoff:
            continue
        current = selected.get(event["symbol"])
        if current is None or started_at > current[0]:
            selected[event["symbol"]] = (
                started_at,
                event,
                intent["detail"]["startedAt"],
            )

    records = []
    for symbol in sorted(ready_symbols):
        selected_event = selected.get(symbol)
        if selected_event is None:
            records.append(
                {
                    "symbol": symbol,
                    "status": "INSUFFICIENT_DATA",
                    "reasonCodes": ["CACHED_FUNDAMENTALS_RESPONSE_NOT_FOUND"],
                }
            )
            continue
        _, event, retrieval_started_at = selected_event
        response = _load_response(event, repository_root)
        supplement, reasons = extract_current_snapshot_supplement(
            symbol=symbol,
            response=response,
            response_content_hash=event["detail"]["responseContentHash"],
            retrieval_started_at=retrieval_started_at,
            cutoff=cutoff,
        )
        if supplement is None:
            records.append(
                {
                    "symbol": symbol,
                    "status": "INSUFFICIENT_DATA",
                    "reasonCodes": reasons,
                    "sourceResponseContentHash": event["detail"][
                        "responseContentHash"
                    ],
                }
            )
            continue
        path, content_hash = _write_controlled_payload(
            storage_root=storage_root,
            symbol=symbol,
            payload=supplement,
        )
        records.append(
            {
                "symbol": symbol,
                "status": "CURRENT_SNAPSHOT_SUPPLEMENT_READY",
                "storageReference": path.relative_to(repository_root).as_posix(),
                "payloadContentHash": content_hash,
                "sourceResponseContentHash": event["detail"]["responseContentHash"],
                "providerUpdatedDate": supplement["providerUpdatedDate"],
                "retrievalStartedAt": supplement["retrievalStartedAt"],
                "currency": supplement["observations"][0]["currency"],
            }
        )

    status_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    minority_interest_observed_count = 0
    for record in records:
        status_counts[record["status"]] = status_counts.get(record["status"], 0) + 1
        for reason in record.get("reasonCodes", ()):
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if record["status"] == "CURRENT_SNAPSHOT_SUPPLEMENT_READY":
            payload = json.loads(
                (repository_root / record["storageReference"]).read_text(
                    encoding="utf-8"
                )
            )
            minority_interest_observed_count += int(
                any(
                    observation["normalizedField"] == "minority_interest"
                    for observation in payload["observations"]
                )
            )
    return {
        "schemaVersion": "eodhd-current-snapshot-supplement-manifest-v1.0.0",
        "policyVersion": CURRENT_SNAPSHOT_POLICY_VERSION,
        "scope": "CURRENT_SNAPSHOT_ONLY",
        "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "targetSecurityCount": len(ready_symbols),
        "statusCounts": dict(sorted(status_counts.items())),
        "reasonCounts": dict(sorted(reason_counts.items())),
        "minorityInterestObservedCount": minority_interest_observed_count,
        "minorityInterestMissingIsNotZero": True,
        "securities": records,
        "licensedValuesIncluded": False,
        "networkRequestsExecuted": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build current-only EODHD Objective Rating input supplements."
    )
    parser.add_argument(
        "--aggregate",
        type=Path,
        default=Path("docs/generated/formula-ready-243-final-aggregate-v1.json"),
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(
            "storage/provider-validation/current-snapshot-supplements-v3"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    repository_root = Path.cwd().resolve()
    aggregate = json.loads(
        (repository_root / arguments.aggregate).read_text(encoding="utf-8")
    )
    ready_symbols = {
        item["symbol"]
        for item in aggregate["securities"]
        if item["status"] == "FORMULA_READY"
    }
    manifest = build_current_snapshot_supplements(
        ready_symbols=ready_symbols,
        repository_root=repository_root,
        storage_root=(repository_root / arguments.storage_root).resolve(),
    )
    manifest["sourceAggregatePath"] = arguments.aggregate.as_posix()
    manifest["sourceAggregateSha256"] = _file_sha256(
        repository_root / arguments.aggregate
    )
    manifest["sourceAggregateContentHash"] = aggregate["artifactContentHash"]
    manifest["artifactContentHash"] = canonical_hash(manifest)
    write_immutable_json((repository_root / arguments.output).resolve(), manifest)


if __name__ == "__main__":
    main()
