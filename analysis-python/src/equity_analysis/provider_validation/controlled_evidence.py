import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.combined_backfill_cli import (
    FORMULA_MARKET_CAP_FIELDS,
    FORMULA_PRICE_FIELDS,
    formula_coverage,
)
from equity_analysis.provider_validation.expansion_gate import (
    FORMULA_HISTORY_REQUIREMENTS,
    FORMULA_INPUT_FIELDS,
    canonical_hash,
    write_immutable_json,
)
from equity_analysis.provider_validation.scoring_backfill_cli import (
    ScoringInputV2Record,
)

EVIDENCE_SCHEMA_VERSION = "formula-ready-controlled-evidence-v1.0.0"
FROZEN_SLICE_SCHEMA_VERSION = "formula-ready-frozen-slice-v1.0.0"
SEC_REQUIRED_FIELDS = frozenset(
    {"diluted_weighted_average_shares", "interest_expense"}
)
EODHD_REQUIRED_FIELDS = (
    FORMULA_INPUT_FIELDS - SEC_REQUIRED_FIELDS
) | FORMULA_PRICE_FIELDS | FORMULA_MARKET_CAP_FIELDS


def _verified_candidate(path: Path, symbol: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.stem.upper() != canonical_hash(payload):
        raise ValueError(f"CONTROLLED_PAYLOAD_HASH_MISMATCH[{symbol}:{path.name}]")
    if payload.get("symbol") != symbol:
        raise ValueError(f"CONTROLLED_PAYLOAD_SYMBOL_MISMATCH[{symbol}:{path.name}]")
    records = tuple(
        ScoringInputV2Record.model_validate(item) for item in payload.get("records", ())
    )
    if not records:
        raise ValueError(f"CONTROLLED_PAYLOAD_EMPTY[{symbol}:{path.name}]")
    latest_ingested_at = max(item.ingested_at for item in records)
    return {
        "path": path,
        "contentHash": path.stem.upper(),
        "records": records,
        "latestIngestedAt": latest_ingested_at,
    }


def _select_latest(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        raise ValueError("NO_VALID_CONTROLLED_PAYLOAD")
    return max(
        candidates,
        key=lambda item: (item["latestIngestedAt"], item["contentHash"]),
    )


def _sec_supplement_coverage(
    records: tuple[ScoringInputV2Record, ...],
) -> dict[str, Any]:
    required = FORMULA_HISTORY_REQUIREMENTS["quarterlyFinancialPeriods"]
    periods = {
        field: {
            item.fiscal_period_end
            for item in records
            if item.provider_code == "sec_edgar"
            and item.dataset == "FINANCIAL"
            and item.period_type == "QUARTERLY"
            and item.normalized_field == field
        }
        for field in sorted(SEC_REQUIRED_FIELDS)
    }
    counts = {field: len(values) for field, values in periods.items()}
    return {
        "requiredQuarterlyPeriods": required,
        "quarterlyPeriodCounts": counts,
        "complete": all(count >= required for count in counts.values()),
    }


def _eodhd_coverage(
    records: tuple[ScoringInputV2Record, ...],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    present = {
        item.normalized_field
        for item in records
        if item.provider_code == "eodhd"
    }
    missing = sorted(EODHD_REQUIRED_FIELDS - present)
    history_complete = (
        coverage["historicalMarketCapObservations"]
        >= FORMULA_HISTORY_REQUIREMENTS["historicalValuationObservations"]
        and coverage["dailyPriceObservationDates"]
        >= coverage["minimumDailyPriceObservationDates"]
    )
    return {
        "requiredFields": sorted(EODHD_REQUIRED_FIELDS),
        "missingFields": missing,
        "historyComplete": history_complete,
        "complete": not missing and history_complete,
    }


def build_symbol_evidence(symbol: str, directory: Path) -> dict[str, Any]:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        return {
            "symbol": symbol,
            "v2StorageExists": False,
            "formulaCoverageComplete": False,
            "eodhdCoverageComplete": False,
            "secSupplementCoverageComplete": False,
            "candidatePayloadCount": 0,
        }
    candidates = [_verified_candidate(path, symbol) for path in paths]
    selected = _select_latest(candidates)
    records = selected["records"]
    coverage = formula_coverage(records)
    sec = _sec_supplement_coverage(records)
    eodhd = _eodhd_coverage(records, coverage)
    receipt = {
        "symbol": symbol,
        "contentHash": selected["contentHash"],
        "storageReference": selected["path"].as_posix(),
        "recordCount": len(records),
        "datasetCoverage": dict(
            sorted(Counter(item.dataset for item in records).items())
        ),
    }
    return {
        "symbol": symbol,
        "v2StorageExists": True,
        "v2ContentHash": selected["contentHash"],
        "v2PayloadPath": selected["path"].as_posix(),
        "v2Receipt": receipt,
        "selectedLatestIngestedAt": selected["latestIngestedAt"].isoformat(),
        "candidatePayloadCount": len(candidates),
        "formulaCoverageComplete": coverage["complete"],
        "eodhdCoverageComplete": eodhd["complete"],
        "secSupplementCoverageComplete": sec["complete"],
        "formulaCoverage": coverage,
        "eodhdCoverage": eodhd,
        "secSupplementCoverage": sec,
    }


def build_controlled_evidence(
    symbols: list[str],
    storage_root: Path,
) -> dict[str, Any]:
    if len(symbols) != len(set(symbols)):
        raise ValueError("DUPLICATE_EVIDENCE_SYMBOL")
    records = {
        symbol: build_symbol_evidence(symbol, storage_root / symbol)
        for symbol in symbols
    }
    payload = {
        "artifactType": "FORMULA_READY_CONTROLLED_EVIDENCE",
        "schemaVersion": EVIDENCE_SCHEMA_VERSION,
        "symbols": symbols,
        "records": records,
        "selectionRule": "MAX_RECORD_INGESTED_AT_THEN_CONTENT_HASH",
        "networkRequestsExecuted": False,
        "objectiveRatingExecuted": False,
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def build_frozen_slices(remaining_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    expected = remaining_manifest.get("artifactContentHash")
    if expected != canonical_hash(
        {
            key: value
            for key, value in remaining_manifest.items()
            if key != "artifactContentHash"
        }
    ):
        raise ValueError("REMAINING_MANIFEST_HASH_MISMATCH")
    frozen = []
    for item in remaining_manifest["slices"]:
        payload = {
            "schemaVersion": FROZEN_SLICE_SCHEMA_VERSION,
            "sourceManifestContentHash": remaining_manifest["artifactContentHash"],
            "sliceId": item["sliceId"],
            "sequence": item["sequence"],
            "symbols": item["symbols"],
            "automaticSelection": False,
            "automaticReplacement": False,
        }
        frozen.append({**payload, "contentHash": canonical_hash(payload)})
    return frozen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remaining-manifest", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--frozen-slice-directory", type=Path, required=True)
    args = parser.parse_args()
    remaining = json.loads(args.remaining_manifest.read_text(encoding="utf-8"))
    symbols = [
        symbol for item in remaining["slices"] for symbol in item["symbols"]
    ]
    evidence = build_controlled_evidence(symbols, args.storage_root)
    write_immutable_json(args.evidence_output, evidence)
    for frozen in build_frozen_slices(remaining):
        path = args.frozen_slice_directory / f"{frozen['sliceId']}.json"
        write_immutable_json(path, frozen)
    print(
        json.dumps(
            {
                "evidenceOutput": str(args.evidence_output),
                "symbolCount": len(symbols),
                "existingEvidenceCount": sum(
                    item["v2StorageExists"]
                    for item in evidence["records"].values()
                ),
                "frozenSliceCount": len(remaining["slices"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
