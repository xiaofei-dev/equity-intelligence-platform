import argparse
import json
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

V3_CONTRACT_VERSION = "provider-neutral-scoring-input-v3.0.0"
DURATION_POLICY_VERSION = "financial-duration-semantics-v1.0.0"
DISCRETE_DERIVATION_POLICY_VERSION = "discrete-quarter-subtraction-v1.0.0"
MARKET_AVAILABILITY_POLICY_VERSION = "market-availability-policy-v1.0.0"
CLASSIFICATION_SNAPSHOT_VERSION = "provider-classification-snapshot-v1.0.0"
ALLOWED_DURATION_SEMANTICS = frozenset(
    {"DISCRETE_QUARTER", "YTD", "ANNUAL", "INSTANT"}
)
INSTANT_FINANCIAL_FIELDS = frozenset(
    {
        "cash_and_equivalents",
        "long_term_debt",
        "market_capitalization",
        "shares_outstanding",
        "stockholders_equity",
        "total_assets",
        "total_debt",
        "total_liabilities",
    }
)


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def derive_discrete_quarter(
    current_ytd: dict[str, Any],
    prior_ytd: dict[str, Any],
) -> dict[str, Any]:
    identity_fields = ("taxonomy", "unit", "entity", "periodStart", "fiscalYear")
    if any(current_ytd.get(key) != prior_ytd.get(key) for key in identity_fields):
        raise ValueError("DISCRETE_DERIVATION_IDENTITY_MISMATCH")
    if (
        current_ytd.get("durationSemantic") != "YTD"
        or prior_ytd.get("durationSemantic") != "YTD"
    ):
        raise ValueError("DISCRETE_DERIVATION_REQUIRES_YTD")
    current_end = date.fromisoformat(current_ytd["periodEnd"])
    prior_end = date.fromisoformat(prior_ytd["periodEnd"])
    if prior_end >= current_end:
        raise ValueError("DISCRETE_DERIVATION_PERIOD_CHRONOLOGY_INVALID")
    current_available = _timestamp(current_ytd["availableAt"])
    prior_available = _timestamp(prior_ytd["availableAt"])
    if prior_available > current_available:
        raise ValueError("DISCRETE_DERIVATION_ACCESSION_CHRONOLOGY_INVALID")
    if (
        not current_ytd.get("accessionNumber")
        or not prior_ytd.get("accessionNumber")
        or current_ytd["accessionNumber"] == prior_ytd["accessionNumber"]
    ):
        raise ValueError("DISCRETE_DERIVATION_ACCESSION_EVIDENCE_INVALID")
    value = Decimal(str(current_ytd["value"])) - Decimal(str(prior_ytd["value"]))
    lineage = {
        "derivationPolicyVersion": DISCRETE_DERIVATION_POLICY_VERSION,
        "operation": "CURRENT_YTD_MINUS_PRIOR_YTD",
        "componentContentHashes": [
            prior_ytd["contentHash"],
            current_ytd["contentHash"],
        ],
        "taxonomy": current_ytd["taxonomy"],
        "unit": current_ytd["unit"],
        "entity": current_ytd["entity"],
        "accessionChronology": [
            prior_ytd["accessionNumber"],
            current_ytd["accessionNumber"],
        ],
    }
    return {
        "value": str(value),
        "periodStart": (prior_end + timedelta(days=1)).isoformat(),
        "periodEnd": current_ytd["periodEnd"],
        "durationSemantic": "DISCRETE_QUARTER",
        "derivationLineage": {
            **lineage,
            "derivationHash": canonical_hash(lineage),
        },
    }


def _duration_evidence(record: dict[str, Any]) -> dict[str, Any]:
    dataset = record["dataset"]
    field = record["normalizedField"]
    period_type = record["periodType"]
    if dataset in {"DAILY_PRICE", "HISTORICAL_MARKET_CAP"} or field in (
        INSTANT_FINANCIAL_FIELDS
    ):
        return {
            "periodStart": record["fiscalPeriodEnd"],
            "periodEnd": record["fiscalPeriodEnd"],
            "durationSemantic": "INSTANT",
            "semanticStatus": "VERIFIED_FROM_INSTANT_FIELD_POLICY",
            "blocker": None,
        }
    if record["providerCode"] == "sec_edgar" and period_type == "QUARTERLY":
        return {
            "periodStart": None,
            "periodEnd": record["fiscalPeriodEnd"],
            "durationSemantic": "DISCRETE_QUARTER",
            "semanticStatus": "SOURCE_SELECTION_VERIFIED_PERIOD_START_NOT_RETAINED",
            "blocker": "PERIOD_START_NOT_RETAINED",
        }
    if period_type == "ANNUAL":
        return {
            "periodStart": None,
            "periodEnd": record["fiscalPeriodEnd"],
            "durationSemantic": "ANNUAL",
            "semanticStatus": "PROVIDER_BUCKET_VERIFIED_PERIOD_START_NOT_RETAINED",
            "blocker": "PERIOD_START_NOT_RETAINED",
        }
    return {
        "periodStart": None,
        "periodEnd": record["fiscalPeriodEnd"],
        "durationSemantic": None,
        "semanticStatus": "UNPROVEN_DISCRETE_QUARTER_OR_YTD",
        "blocker": "DURATION_SEMANTIC_UNPROVEN",
    }


def _market_availability(
    record: dict[str, Any],
    as_of_cutoff: str,
) -> dict[str, Any]:
    dataset = record["dataset"]
    financial_pit = (
        dataset == "FINANCIAL"
        and bool(record.get("accessionNumber"))
        and record.get("availableAt") is not None
    )
    historical_market = dataset in {"DAILY_PRICE", "HISTORICAL_MARKET_CAP"}
    return {
        "policyVersion": MARKET_AVAILABILITY_POLICY_VERSION,
        "observedAt": record["effectiveAt"],
        "providerPublishedAt": (
            record["availableAt"]
            if record["providerCode"] == "sec_edgar"
            else None
        ),
        "publicAvailableAt": record["availableAt"],
        "ingestedAt": record["ingestedAt"],
        "currentRankingEligible": (
            _timestamp(record["availableAt"]) <= _timestamp(as_of_cutoff)
        ),
        "historicalPitEligible": financial_pit and not historical_market,
        "historicalPitBlocker": (
            "PROVIDER_PUBLICATION_TIME_UNPROVEN"
            if historical_market
            else (None if financial_pit else "DEFENSIBLE_AVAILABILITY_UNPROVEN")
        ),
    }


def _classification_snapshot(
    ledger_item: dict[str, Any],
    *,
    universe_version: str,
    as_of_cutoff: str,
    source_path: Path,
    source_sha256: str,
    source_content_hash: str,
) -> dict[str, Any]:
    payload = {
        "version": CLASSIFICATION_SNAPSHOT_VERSION,
        "symbol": ledger_item["symbol"],
        "sector": ledger_item["sector"],
        "marketCapBand": ledger_item["marketCapBand"],
        "companyType": ledger_item["companyType"],
        "applicability": (
            "GENERAL_COMPANY_MODEL"
            if ledger_item["companyType"] == "MATURE_OPERATING_COMPANY"
            else "NOT_APPLICABLE"
        ),
        "universeVersion": universe_version,
        "asOfCutoff": as_of_cutoff,
        "sourcePath": source_path.as_posix(),
        "sourceSha256": source_sha256,
        "sourceContentHash": source_content_hash,
    }
    return {**payload, "snapshotHash": canonical_hash(payload)}


def migrate_payload(
    v2_payload: dict[str, Any],
    classification: dict[str, Any],
    *,
    as_of_cutoff: str,
) -> tuple[dict[str, Any], list[str]]:
    blockers = set()
    migrated_records = []
    for source in v2_payload["records"]:
        duration = _duration_evidence(source)
        if duration["blocker"]:
            blockers.add(duration["blocker"])
        availability = _market_availability(source, as_of_cutoff)
        if availability["historicalPitBlocker"] and source["dataset"] in {
            "DAILY_PRICE",
            "HISTORICAL_MARKET_CAP",
        }:
            blockers.add("HISTORICAL_VALUATION_PIT_UNPROVEN")
        raw = {
            **{key: value for key, value in source.items() if key != "contentHash"},
            **duration,
            "sourceV2RecordContentHash": source["contentHash"],
            "derivationLineage": {
                "status": "DIRECT_SOURCE_RECORD",
                "derivationPolicyVersion": None,
                "componentContentHashes": [source["contentHash"]],
            },
            "marketAvailability": availability,
        }
        raw["contentHash"] = canonical_hash(raw)
        migrated_records.append(raw)
    payload = {
        "inputContractVersion": V3_CONTRACT_VERSION,
        "symbol": v2_payload["symbol"],
        "sourceV2ContractVersion": v2_payload["inputContractVersion"],
        "sourceV2PayloadHash": canonical_hash(v2_payload),
        "durationPolicyVersion": DURATION_POLICY_VERSION,
        "discreteDerivationPolicyVersion": DISCRETE_DERIVATION_POLICY_VERSION,
        "marketAvailabilityPolicyVersion": MARKET_AVAILABILITY_POLICY_VERSION,
        "classificationSnapshot": classification,
        "records": migrated_records,
        "contractBlockers": sorted(blockers),
    }
    return payload, sorted(blockers)


def _sha256(path: Path) -> str:
    from hashlib import sha256

    return sha256(path.read_bytes()).hexdigest().upper()


def migrate_formula_ready_population(
    *,
    aggregate_path: Path,
    aggregate_sha256: str,
    classification_path: Path,
    classification_sha256: str,
    repository_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    if _sha256(aggregate_path) != aggregate_sha256.upper():
        raise ValueError("V3_SOURCE_AGGREGATE_SHA_MISMATCH")
    if _sha256(classification_path) != classification_sha256.upper():
        raise ValueError("V3_CLASSIFICATION_SOURCE_SHA_MISMATCH")
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    classification_source = json.loads(classification_path.read_text(encoding="utf-8"))
    ledger = {item["symbol"]: item for item in classification_source["ledger"]}
    ready = [
        item for item in aggregate["securities"] if item["status"] == "FORMULA_READY"
    ]
    if len(ready) != 223:
        raise ValueError("V3_MIGRATION_REQUIRES_223_FORMULA_READY_INPUTS")

    def source_path(item: dict[str, Any]) -> Path:
        reference = item.get("storageReference")
        if reference:
            return repository_root / reference
        return (
            repository_root
            / "storage/provider-validation/scoring-inputs-v2"
            / item["symbol"]
            / f"{item['contentHash']}.json"
        )

    maximum_ingested_at = max(
        _timestamp(record["ingestedAt"])
        for item in ready
        for record in json.loads(
            source_path(item).read_text(encoding="utf-8")
        )["records"]
    ).isoformat()
    manifest_records = []
    blocker_counts = Counter()
    for item in ready:
        v2_path = source_path(item)
        v2_payload = json.loads(v2_path.read_text(encoding="utf-8"))
        if canonical_hash(v2_payload) != item["contentHash"]:
            raise ValueError(f"V3_SOURCE_PAYLOAD_HASH_MISMATCH[{item['symbol']}]")
        ledger_item = ledger.get(item["symbol"])
        if ledger_item is None:
            raise ValueError(f"V3_CLASSIFICATION_MISSING[{item['symbol']}]")
        classification = _classification_snapshot(
            ledger_item,
            universe_version=classification_source["universeVersion"],
            as_of_cutoff=maximum_ingested_at,
            source_path=classification_path,
            source_sha256=classification_sha256.upper(),
            source_content_hash=classification_source["artifactContentHash"],
        )
        migrated, blockers = migrate_payload(
            v2_payload,
            classification,
            as_of_cutoff=maximum_ingested_at,
        )
        v3_hash = canonical_hash(migrated)
        destination = output_root / item["symbol"] / f"{v3_hash}.json"
        if destination.exists():
            if json.loads(destination.read_text(encoding="utf-8")) != migrated:
                raise ValueError(f"V3_CONTENT_HASH_COLLISION[{item['symbol']}]")
        else:
            write_immutable_json(destination, migrated)
        blocker_counts.update(blockers)
        manifest_records.append(
            {
                "symbol": item["symbol"],
                "sourceV2Path": v2_path.as_posix(),
                "sourceV2Hash": item["contentHash"],
                "v3Path": destination.as_posix(),
                "v3Hash": v3_hash,
                "classificationSnapshotHash": classification["snapshotHash"],
                "currentRankingEligible": not any(
                    reason
                    in {
                        "DURATION_SEMANTIC_UNPROVEN",
                        "PERIOD_START_NOT_RETAINED",
                    }
                    for reason in blockers
                ),
                "historicalPitEligible": not blockers,
                "blockers": blockers,
                "recordCount": len(migrated["records"]),
            }
        )
    current_eligible = sum(item["currentRankingEligible"] for item in manifest_records)
    historical_eligible = sum(item["historicalPitEligible"] for item in manifest_records)
    payload = {
        "artifactType": "SCORING_INPUT_V3_OFFLINE_MIGRATION_MANIFEST",
        "schemaVersion": "scoring-input-v3-migration-manifest-v1.0.0",
        "inputContractVersion": V3_CONTRACT_VERSION,
        "sourceAggregatePath": aggregate_path.as_posix(),
        "sourceAggregateSha256": aggregate_sha256.upper(),
        "classificationSourcePath": classification_path.as_posix(),
        "classificationSourceSha256": classification_sha256.upper(),
        "classificationSourceContentHash": classification_source[
            "artifactContentHash"
        ],
        "universeVersion": classification_source["universeVersion"],
        "asOfCutoff": maximum_ingested_at,
        "sourceFormulaReadyCount": 223,
        "migratedPayloadCount": len(manifest_records),
        "currentRankingEligibleCount": current_eligible,
        "historicalPitEligibleCount": historical_eligible,
        "blockedCurrentRankingCount": 223 - current_eligible,
        "blockedHistoricalPitCount": 223 - historical_eligible,
        "blockerCounts": dict(sorted(blocker_counts.items())),
        "records": manifest_records,
        "implicitYtdConversionUsed": False,
        "objectiveRatingExecuted": False,
        "networkRequestsExecuted": False,
        "rawProviderValuesIncluded": False,
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--aggregate-sha256", required=True)
    parser.add_argument("--classification-source", type=Path, required=True)
    parser.add_argument("--classification-sha256", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()
    manifest = migrate_formula_ready_population(
        aggregate_path=args.aggregate,
        aggregate_sha256=args.aggregate_sha256,
        classification_path=args.classification_source,
        classification_sha256=args.classification_sha256,
        repository_root=args.repository_root,
        output_root=args.output_root,
    )
    write_immutable_json(args.manifest_output, manifest)
    print(
        json.dumps(
            {
                "manifestOutput": str(args.manifest_output),
                "migratedPayloadCount": manifest["migratedPayloadCount"],
                "currentRankingEligibleCount": manifest[
                    "currentRankingEligibleCount"
                ],
                "historicalPitEligibleCount": manifest[
                    "historicalPitEligibleCount"
                ],
                "blockerCounts": manifest["blockerCounts"],
                "artifactContentHash": manifest["artifactContentHash"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
