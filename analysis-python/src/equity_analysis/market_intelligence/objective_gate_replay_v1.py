from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import canonical_hash

REPLAY_VERSION = "objective-current-gate-replay-v1.1.0"
CURRENT_SCOPE = "CURRENT_DECISION_ONLY"
EXPECTED_MANIFEST_SCHEMA = "objective-rating-current-decision-input-manifest-v1.0.0"
EXPECTED_GATE_SCHEMA = "objective-rating-current-snapshot-algorithm-gate-v1.0.0"
EXPECTED_AUDIT_SCHEMA = "market-intelligence-eligibility-root-cause-audit-v1.0.0"
EXPECTED_PAYLOAD_SCHEMA = "objective-rating-current-decision-input-v1.0.0"
EXPECTED_WINDOW_POLICY = "objective-rating-current-factor-window-v1.4.0"
EXPECTED_SOURCE_POLICY = "eodhd-current-snapshot-qc-v1.0.0"
EXPECTED_STRATEGY = "QC-v1.0.0"
FROZEN_MINIMUM = 20
EXPECTED_MANIFEST_HASH = (
    "19ED019C6B36E9DE0CA0C2A17A053851851C5044F6BC6FF2FEEA90E774FA6D1E"
)
EXPECTED_GATE_HASH = (
    "131FD6C59A596056CB6A329FDA3BB73404CADDF2976826B2CDD211D5CB593F4B"
)
EXPECTED_AUDIT_HASH = (
    "4871644C8FEEAC321CCD905C7475204135C94CAD32A3D44A65171E563EC88BF3"
)


class ObjectiveGateReplayError(ValueError):
    """Raised when immutable Objective evidence cannot be replayed safely."""


@dataclass(frozen=True)
class ObjectiveGateReplaySecurity:
    symbol: str
    security_id: str
    membership_status: str
    company_type: str
    objective_state: str
    input_payload_hash: str | None


@dataclass(frozen=True)
class ObjectiveGateReplayPlan:
    version: str
    scope: str
    as_of_time: str
    strategy_version: str
    source_snapshot_id: str
    universe_version: str
    manifest_content_hash: str
    gate_content_hash: str
    source_profile_count: int
    included_count: int
    objective_scored_count: int
    insufficient_data_count: int
    non_applicable_count: int
    frozen_minimum: int
    threshold_reached: bool
    network_requests_required: bool
    full_market_intelligence_eligibility_claimed: bool
    securities: tuple[ObjectiveGateReplaySecurity, ...]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def _verify_content_hash(
    artifact: dict[str, Any],
    *,
    path: Path,
    field: str = "artifactContentHash",
) -> str:
    expected = artifact.get(field)
    if not isinstance(expected, str) or not expected:
        raise ObjectiveGateReplayError(f"ARTIFACT_CONTENT_HASH_MISSING[{path.name}]")
    payload = dict(artifact)
    del payload[field]
    actual = canonical_hash(payload)
    if actual.upper() != expected.removeprefix("sha256:").upper():
        raise ObjectiveGateReplayError(f"ARTIFACT_CONTENT_HASH_MISMATCH[{path.name}]")
    return expected.removeprefix("sha256:").upper()


def _verify_payload(
    repository_root: Path,
    item: dict[str, Any],
    *,
    cutoff: str,
) -> dict[str, Any]:
    reference = item.get("storageReference")
    expected = item.get("payloadContentHash")
    if not isinstance(reference, str) or not isinstance(expected, str):
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_REFERENCE_MISSING[{item.get('symbol', 'UNKNOWN')}]"
        )
    path = (repository_root / reference).resolve()
    try:
        path.relative_to(repository_root.resolve())
    except ValueError as error:
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_OUTSIDE_REPOSITORY[{item.get('symbol', 'UNKNOWN')}]"
        ) from error
    if not path.is_file():
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_MISSING[{item.get('symbol', 'UNKNOWN')}]"
        )
    payload = _load(path)
    embedded = payload.get("contentHash")
    if not isinstance(embedded, str):
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_HASH_MISSING[{item.get('symbol', 'UNKNOWN')}]"
        )
    candidate = dict(payload)
    del candidate["contentHash"]
    actual = canonical_hash(candidate)
    expected_hash = expected.removeprefix("sha256:").upper()
    if embedded.removeprefix("sha256:").upper() != expected_hash:
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_MANIFEST_HASH_MISMATCH[{item['symbol']}]"
        )
    if actual != expected_hash:
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_CANONICAL_HASH_MISMATCH[{item['symbol']}]"
        )
    symbol = item.get("symbol")
    if payload.get("symbol") != symbol:
        raise ObjectiveGateReplayError(f"CONTROLLED_PAYLOAD_SYMBOL_MISMATCH[{symbol}]")
    if payload.get("schemaVersion") != EXPECTED_PAYLOAD_SCHEMA:
        raise ObjectiveGateReplayError(f"CONTROLLED_PAYLOAD_SCHEMA_MISMATCH[{symbol}]")
    if payload.get("windowPolicyVersion") != EXPECTED_WINDOW_POLICY:
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_WINDOW_POLICY_MISMATCH[{symbol}]"
        )
    if payload.get("sourcePolicyVersion") != EXPECTED_SOURCE_POLICY:
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_SOURCE_POLICY_MISMATCH[{symbol}]"
        )
    if payload.get("scope") != CURRENT_SCOPE or payload.get("cutoff") != cutoff:
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_CURRENT_SCOPE_MISMATCH[{symbol}]"
        )
    if (
        payload.get("formulaOrWeightChanges") is not False
        or payload.get("scoresOrRanksIncluded") is not False
        or payload.get("historicalPitEligible") is not False
        or payload.get("backtestEligible") is not False
    ):
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_METHODOLOGY_BOUNDARY_MISMATCH[{symbol}]"
        )
    current_ready = payload.get("currentQcInputReady")
    algorithm_eligible = payload.get("algorithmQcEligible")
    if not isinstance(current_ready, bool) or not isinstance(algorithm_eligible, bool):
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_READINESS_INVALID[{symbol}]"
        )
    if payload.get("forwardObservationEligible") is not current_ready:
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_FORWARD_ELIGIBILITY_MISMATCH[{symbol}]"
        )
    expected_status = (
        "CURRENT_QC_INPUT_READY" if algorithm_eligible else "INSUFFICIENT_DATA"
    )
    if item.get("status") != expected_status:
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_STATUS_MISMATCH[{symbol}]"
        )
    if algorithm_eligible and (
        current_ready is not True or not isinstance(payload.get("qcRawFactors"), dict)
    ):
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_ALGORITHM_INPUT_MISSING[{symbol}]"
        )
    return payload


def build_objective_gate_replay_plan(
    *,
    repository_root: Path,
    input_manifest_path: Path,
    algorithm_gate_path: Path,
    closed_pool_audit_path: Path,
) -> ObjectiveGateReplayPlan:
    """Validate immutable evidence and map it to the closed 66-security pool.

    This function is intentionally offline and side-effect free. It establishes
    only Objective QC score availability. It never promotes that status to the
    broader Market Intelligence ranking eligibility contract.
    """

    root = repository_root.resolve()
    manifest = _load(input_manifest_path)
    gate = _load(algorithm_gate_path)
    audit = _load(closed_pool_audit_path)
    manifest_hash = _verify_content_hash(manifest, path=input_manifest_path)
    gate_hash = _verify_content_hash(gate, path=algorithm_gate_path)
    audit_hash = _verify_content_hash(audit, path=closed_pool_audit_path)

    if manifest_hash != EXPECTED_MANIFEST_HASH:
        raise ObjectiveGateReplayError("INPUT_MANIFEST_NOT_ACCEPTED")
    if gate_hash != EXPECTED_GATE_HASH:
        raise ObjectiveGateReplayError("OBJECTIVE_GATE_NOT_ACCEPTED")
    if audit_hash != EXPECTED_AUDIT_HASH:
        raise ObjectiveGateReplayError("CLOSED_POOL_AUDIT_NOT_ACCEPTED")

    if manifest.get("schemaVersion") != EXPECTED_MANIFEST_SCHEMA:
        raise ObjectiveGateReplayError("INPUT_MANIFEST_SCHEMA_NOT_APPROVED")
    if manifest.get("policyVersion") != EXPECTED_SOURCE_POLICY:
        raise ObjectiveGateReplayError("INPUT_MANIFEST_POLICY_NOT_APPROVED")
    if gate.get("schemaVersion") != EXPECTED_GATE_SCHEMA:
        raise ObjectiveGateReplayError("OBJECTIVE_GATE_SCHEMA_NOT_APPROVED")
    if audit.get("schemaVersion") != EXPECTED_AUDIT_SCHEMA:
        raise ObjectiveGateReplayError("CLOSED_POOL_AUDIT_SCHEMA_NOT_APPROVED")
    if gate.get("strategyVersion") != EXPECTED_STRATEGY:
        raise ObjectiveGateReplayError("OBJECTIVE_GATE_STRATEGY_NOT_APPROVED")
    if gate.get("scope") != CURRENT_SCOPE or manifest.get("scope") != CURRENT_SCOPE:
        raise ObjectiveGateReplayError("OBJECTIVE_GATE_SCOPE_NOT_CURRENT_ONLY")
    if gate.get("status") != "PASS":
        raise ObjectiveGateReplayError("OBJECTIVE_GATE_NOT_PASSED")
    if (
        manifest.get("gateStatus") != "READY_FOR_OFFLINE_QC_SCORING"
        or manifest.get("evaluatedSecurityCount") != 216
        or manifest.get("currentQcInputReadyCount") != 190
        or manifest.get("algorithmQcEligibleCount") != 136
        or manifest.get("currentQcMinimum") != FROZEN_MINIMUM
        or manifest.get("networkRequestsExecuted") is not False
        or manifest.get("scoresOrRanksIncluded") is not False
        or manifest.get("forwardValidationExecuted") is not False
    ):
        raise ObjectiveGateReplayError("INPUT_MANIFEST_ACCEPTANCE_COUNTS_INVALID")
    if (
        gate.get("scoredSecurityCount") != 136
        or gate.get("networkRequestsExecuted") is not False
        or gate.get("licensedProviderValuesIncluded") is not False
    ):
        raise ObjectiveGateReplayError("OBJECTIVE_GATE_ACCEPTANCE_COUNTS_INVALID")
    if gate.get("asOfTime") != manifest.get("cutoff"):
        raise ObjectiveGateReplayError("OBJECTIVE_GATE_CUTOFF_MISMATCH")
    linked_manifest_hash = str(gate.get("inputManifestContentHash", ""))
    if linked_manifest_hash.removeprefix("sha256:").upper() != manifest_hash:
        raise ObjectiveGateReplayError("OBJECTIVE_GATE_MANIFEST_HASH_MISMATCH")
    boundaries = gate.get("methodologyBoundaries", {})
    if boundaries.get("historicalPitClaim") is not False:
        raise ObjectiveGateReplayError("HISTORICAL_PIT_BOUNDARY_NOT_PRESERVED")
    for field in (
        "formulaOrWeightChanges",
        "historicalBacktestAuthorized",
        "forwardDecisionQualityValidationExecuted",
        "automaticTradingAuthorized",
    ):
        if boundaries.get(field) is not False:
            raise ObjectiveGateReplayError(
                f"OBJECTIVE_GATE_BOUNDARY_NOT_PRESERVED[{field}]"
            )

    manifest_by_symbol: dict[str, dict[str, Any]] = {}
    current_ready_count = 0
    algorithm_eligible_symbols: set[str] = set()
    verified_payload_count = 0
    cutoff = str(manifest.get("cutoff"))
    for item in manifest.get("securities", []):
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or symbol in manifest_by_symbol:
            raise ObjectiveGateReplayError("INPUT_MANIFEST_SYMBOL_INVALID_OR_DUPLICATE")
        manifest_by_symbol[symbol] = item
        if item.get("storageReference") is not None:
            payload = _verify_payload(root, item, cutoff=cutoff)
            verified_payload_count += 1
            if payload["currentQcInputReady"]:
                current_ready_count += 1
            if payload["algorithmQcEligible"]:
                algorithm_eligible_symbols.add(symbol)
    if len(manifest_by_symbol) != 216:
        raise ObjectiveGateReplayError(
            f"INPUT_MANIFEST_SECURITY_COUNT_UNEXPECTED[{len(manifest_by_symbol)}]"
        )
    if verified_payload_count != 216:
        raise ObjectiveGateReplayError(
            f"CONTROLLED_PAYLOAD_COVERAGE_UNEXPECTED[{verified_payload_count}]"
        )
    if current_ready_count != 190 or len(algorithm_eligible_symbols) != 136:
        raise ObjectiveGateReplayError("CONTROLLED_PAYLOAD_READINESS_COUNTS_INVALID")
    declared_eligible = manifest.get("algorithmQcEligibleSymbols")
    if (
        not isinstance(declared_eligible, list)
        or len(declared_eligible) != len(set(declared_eligible))
        or set(declared_eligible) != algorithm_eligible_symbols
    ):
        raise ObjectiveGateReplayError("INPUT_MANIFEST_ELIGIBLE_SYMBOLS_MISMATCH")

    gate_by_symbol: dict[str, dict[str, Any]] = {}
    for item in gate.get("securities", []):
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or symbol in gate_by_symbol:
            raise ObjectiveGateReplayError("OBJECTIVE_GATE_SYMBOL_INVALID_OR_DUPLICATE")
        source = manifest_by_symbol.get(symbol)
        if source is None:
            raise ObjectiveGateReplayError(f"GATE_SYMBOL_NOT_IN_MANIFEST[{symbol}]")
        expected = str(source.get("payloadContentHash", "")).removeprefix(
            "sha256:"
        ).upper()
        actual = str(item.get("inputPayloadHash", "")).removeprefix("sha256:").upper()
        if actual != expected:
            raise ObjectiveGateReplayError(f"GATE_INPUT_HASH_MISMATCH[{symbol}]")
        gate_by_symbol[symbol] = item
    if len(gate_by_symbol) != 136:
        raise ObjectiveGateReplayError(
            f"OBJECTIVE_GATE_SECURITY_COUNT_UNEXPECTED[{len(gate_by_symbol)}]"
        )
    if set(gate_by_symbol) != algorithm_eligible_symbols:
        raise ObjectiveGateReplayError("OBJECTIVE_GATE_ELIGIBLE_SYMBOLS_MISMATCH")

    profiles = audit.get("profiles")
    if not isinstance(profiles, list) or len(profiles) != 66:
        raise ObjectiveGateReplayError("CLOSED_POOL_PROFILE_COUNT_UNEXPECTED")
    planned: list[ObjectiveGateReplaySecurity] = []
    seen: set[str] = set()
    included_count = 0
    scored_count = 0
    insufficient_count = 0
    non_applicable_count = 0
    for profile in profiles:
        symbol = profile.get("symbol")
        if not isinstance(symbol, str) or symbol in seen:
            raise ObjectiveGateReplayError("CLOSED_POOL_SYMBOL_INVALID_OR_DUPLICATE")
        seen.add(symbol)
        membership = str(profile.get("membershipStatus"))
        company_type = str(profile.get("companyType"))
        gate_item = gate_by_symbol.get(symbol)
        if membership == "INCLUDED":
            included_count += 1
            if gate_item is not None:
                state = "OBJECTIVE_QC_SCORED"
                payload_hash = str(gate_item["inputPayloadHash"]).removeprefix(
                    "sha256:"
                ).upper()
                scored_count += 1
            else:
                state = "INSUFFICIENT_DATA"
                payload_hash = None
                insufficient_count += 1
        else:
            state = "NOT_APPLICABLE"
            payload_hash = None
            non_applicable_count += 1
        planned.append(
            ObjectiveGateReplaySecurity(
                symbol=symbol,
                security_id=str(profile["securityId"]),
                membership_status=membership,
                company_type=company_type,
                objective_state=state,
                input_payload_hash=payload_hash,
            )
        )
    if included_count != 55 or non_applicable_count != 11:
        raise ObjectiveGateReplayError("CLOSED_POOL_MEMBERSHIP_COUNTS_UNEXPECTED")
    if scored_count != 32 or insufficient_count != 23:
        raise ObjectiveGateReplayError("CLOSED_POOL_OBJECTIVE_OVERLAP_UNEXPECTED")
    audit_scope = audit.get("scope")
    if not isinstance(audit_scope, dict):
        raise ObjectiveGateReplayError("CLOSED_POOL_SCOPE_MISSING")
    if (
        audit_scope.get("profileCount") != 66
        or audit_scope.get("includedCount") != 55
        or audit_scope.get("nonRankableByDesignCount") != 11
        or audit_scope.get("snapshotStatus") != "READY"
    ):
        raise ObjectiveGateReplayError("CLOSED_POOL_SCOPE_COUNTS_INVALID")
    source_snapshot_id = str(audit_scope.get("dataSnapshotId", ""))
    universe_version = str(audit_scope.get("universeVersion", ""))
    if not source_snapshot_id or not universe_version:
        raise ObjectiveGateReplayError("CLOSED_POOL_SCOPE_IDENTITY_MISSING")

    return ObjectiveGateReplayPlan(
        version=REPLAY_VERSION,
        scope=CURRENT_SCOPE,
        as_of_time=str(gate["asOfTime"]),
        strategy_version=str(gate["strategyVersion"]),
        source_snapshot_id=source_snapshot_id,
        universe_version=universe_version,
        manifest_content_hash=manifest_hash,
        gate_content_hash=gate_hash,
        source_profile_count=len(planned),
        included_count=included_count,
        objective_scored_count=scored_count,
        insufficient_data_count=insufficient_count,
        non_applicable_count=non_applicable_count,
        frozen_minimum=FROZEN_MINIMUM,
        threshold_reached=scored_count >= FROZEN_MINIMUM,
        network_requests_required=False,
        full_market_intelligence_eligibility_claimed=False,
        securities=tuple(sorted(planned, key=lambda item: item.symbol)),
    )
