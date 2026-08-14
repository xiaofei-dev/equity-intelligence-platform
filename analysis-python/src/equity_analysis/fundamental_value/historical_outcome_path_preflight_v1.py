"""Outcome-blind Stage 7C-6 structural inventory and fail-closed preflight."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .historical_quarterly_semantics_support_v1 import canonical_hash

SCHEMA_VERSION = "FV-STAGE7C6-OUTCOME-PATH-PREFLIGHT-v1.0.0"
C5_FILE_SHA256 = "6136495A50D4EF99C642D1C30CA9FA3823675CDADF88870ADBD05DEE5C340B66"
C5_CONTENT_HASH = "848ED7DE1A55F3EBE56B6DAB4E5BF8E347C303BF803A0FAC1F096FDA7E09DB4C"
C5_CHECKPOINT_SHA256 = "F96E6DE65D77D4263B52F46F605AEF9844C0A755EE7CFCD433F7AB1FB4E43B85"
C5_CHECKPOINT_CONTENT_HASH = "D9BF09661416214C1FF9788D41AC9E1FD6505FB72E02C091B762DA4F98CCA712"
YAHOO_MANIFEST_SHA256 = "E322AC57C00BB4018AC883A2F0EF3461299D7D97725B0791C75EA01846D08E27"
EODHD_AUDIT_SHA256 = "2AE865EA4EC446F3FBED8BC5B1BC80F669B6967988BAA74FB01A0E55DED1C027"


def _read_bound(path: Path, expected_hash: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper() != expected_hash:
        raise ValueError(f"Structural source hash drift: {path.name}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"Structural source must be an object: {path.name}")
    return value


def build_outcome_path_preflight(repository: Path) -> dict[str, Any]:
    contract_root = repository / "contracts/fundamental-value-historical-validation-v1"
    c5 = _read_bound(
        contract_root / "stage7c5-provider-native-company-quality-coverage.json",
        C5_FILE_SHA256,
    )
    if c5.get("contentHash") != C5_CONTENT_HASH or c5.get("outcomesRead") is not False:
        raise ValueError("C5 coverage identity or outcome-blind assertion drift")
    checkpoint = _read_bound(
        repository / "storage/fundamental-value-historical-validation-v1"
        / "stage7c5-provider-native/sealed-predictors.json",
        C5_CHECKPOINT_SHA256,
    )
    if checkpoint.get("contentHash") != C5_CHECKPOINT_CONTENT_HASH:
        raise ValueError("C5 predictor checkpoint identity drift")
    records = checkpoint.get("records")
    if not isinstance(records, list) or len(records) != 1804:
        raise ValueError("C5 predictor population must contain exactly 1,804 records")
    identities = sorted({str(item["securityId"]) for item in records})
    dates = sorted({str(item["decisionDate"]) for item in records})
    pairs = {(str(item["securityId"]), str(item["decisionDate"])) for item in records}
    if len(identities) != 191 or len(dates) != 12 or len(pairs) != 1804:
        raise ValueError("C5 sealed population cardinality drift")

    yahoo = _read_bound(
        repository / "docs/generated"
        / "historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json",
        YAHOO_MANIFEST_SHA256,
    )
    eodhd = _read_bound(
        repository / "docs/generated/provider-cached-transport-semantic-audit-v1.2.json",
        EODHD_AUDIT_SHA256,
    )
    inventory = {
        "c5Population": {
            "predictorRecordCount": len(records),
            "distinctSecurityCount": len(identities),
            "distinctDecisionDateCount": len(dates),
            "identitySetHash": canonical_hash(identities),
            "securityDateSetHash": canonical_hash(sorted([list(item) for item in pairs])),
            "populationLabel": "CONTROLLED_OVERLAP_CURRENT_UNIVERSE_RETROSPECTIVE",
            "survivorshipLimitation": True,
            "notA310UniverseClaim": True,
        },
        "controlledCaches": {
            "yahoo": {
                "manifestSha256": YAHOO_MANIFEST_SHA256,
                "status": yahoo.get("status"),
                "symbolCount": yahoo.get("completedSecurityCount"),
                "includesSpy": True,
                "includesAllSectorEtfs": False,
                "identityBinding": "SYMBOL_ONLY",
            },
            "eodhd": {
                "auditSha256": EODHD_AUDIT_SHA256,
                "eodSecurityCount": eodhd.get("endpointSecurityCounts", {}).get("eod"),
                "includesBenchmarks": False,
                "includesCorporateActions": False,
                "identityBinding": "SYMBOL_ONLY",
            },
        },
    }
    blockers = [
        "CANONICAL_SECURITY_LISTING_SHARE_CLASS_AND_TICKER_INTERVALS_UNPROVEN",
        "EXACT_COMPLETED_SESSION_CALENDAR_AND_OUTCOME_CUTOFF_UNBOUND",
        "PER_SECURITY_ENTRY_EXIT_MATURITY_UNPROVEN",
        "ADJUSTMENT_ACTION_DOUBLE_COUNT_PREVENTION_UNBOUND",
        "DELISTING_ACQUISITION_TERMINAL_CASH_TREATMENT_UNPROVEN",
        "NUMERIC_COST_SLIPPAGE_LIQUIDITY_POLICY_UNFROZEN",
        "ELEVEN_SECTOR_ETF_PATHS_ABSENT",
        "DATED_SECTOR_CLASSIFICATION_UNPROVEN",
        "OUTCOME_TERMINAL_POPULATION_REGISTRY_ABSENT",
        "EXECUTION_RUNNER_BLOCKED_EXECUTION_CONTRACT_INCOMPLETE",
    ]
    body: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "state": "BLOCKED_OUTCOME_PATH_INCOMPLETE",
        "c5CoverageContentHash": C5_CONTENT_HASH,
        "c5PredictorCheckpointContentHash": C5_CHECKPOINT_CONTENT_HASH,
        "inventory": inventory,
        "outcomeContractSealed": False,
        "numericOutcomesRead": False,
        "acquisitionPlanGenerated": False,
        "networkAuthorized": False,
        "physicalRequestsExecuted": 0,
        "requestWeightConsumed": 0,
        "retryLimit": 0,
        "unknownRequestsRetried": 0,
        "blockers": blockers,
        "stopRationale": (
            "A complete accepted-registry request matrix cannot be derived until "
            "stable identities, benchmark/action requirements, and terminal policies "
            "are bound; an arbitrary partial plan is forbidden."
        ),
        "stage8State": "CLOSED_STAGE7_INCOMPLETE",
        "providerValuesIncluded": False,
    }
    body["contentHash"] = canonical_hash(body)
    return body
