from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v21 import (
    BenchmarkConstructionRequestV21,
    BenchmarkConstructionState,
    BenchmarkHoldingV21,
    BenchmarkKindEvidenceV21,
    BenchmarkLiquidityEvidence,
    BenchmarkPriceBar,
    BenchmarkUniverseSecurity,
    BenchmarkVariantEvidenceV21,
    UniverseRole,
    _equal_weight_variant,
    _holding,
    _kind_evidence,
    _liquidity_payload,
    _market_variant,
    _member_sources,
    _momentum_variant,
    _price_index,
    _price_sources,
    _sector_variants,
    _validate_request,
    _validated_liquidity,
    _validated_prices,
    _variant,
)
from equity_analysis.forward_validation.benchmark_controlled_ledger_v22 import (
    ControlledBenchmarkLedgerSetV22,
    build_controlled_benchmark_ledger_set_v22,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

BENCHMARK_CONSTRUCTION_V22 = "FORWARD-BENCHMARK-CONSTRUCTION-v2.2.0"
PURE_VALUE_CONSTRUCTION_V22 = "PURE-VALUE-EBITDA-TO-EV-TOP-QUINTILE-v2.2.0"
PURE_QUALITY_CONSTRUCTION_V22 = (
    "PURE-QUALITY-GROSS-PROFIT-TO-REVENUE-TOP-QUINTILE-v2.2.0"
)
SUCCESSOR_BENCHMARK_MANIFEST_V22 = "FORWARD-BENCHMARK-MANIFEST-v2.2.0"

PARENT_PREREGISTRATION_HASH = (
    "sha256:cb63d2600b42c9003be8a99a76de967e5921ef68440bcd3a0d6dd8934efac966"
)
BENCHMARK_PREREGISTRATION_V22_HASH = (
    "sha256:cbeaa8e2fbb524a2e16084e80c0e52a47948e4ec208fa20ec37864a7ed2b5444"
)
PREREGISTRATION_SEAL_V22_HASH = (
    "sha256:ed3e796290c3509c94429b7273346612c40f2b4db4b94889e0db7d583c7c8e0d"
)
CANDIDATE_POLICY_V22_HASH = (
    "sha256:6f03ed3c092983d691ef8f32a71384ef329528b0a69a85e84579587901ee69d8"
)
EXTERNAL_REFERENCE_UNIVERSE_V22_HASH = (
    "sha256:20885e4ca21345f152220430966141303b26ff7b49e9361825702471779e7a05"
)
INPUT_CAPTURE_V22_HASH = (
    "sha256:6421f584a5e1e8adf9e35ee88eb259982f72956dd475bc6897570e5d158b0693"
)
INPUT_COVERAGE_V22_HASH = (
    "sha256:03ec8cfa4a923a5b2c53ce2fef68b80e5a7cad165c97f4259ec0a914411327f1"
)
CANDIDATE_CONSTRUCTION_V22_HASH = (
    "sha256:f5c23ad459349a7aa125d0cd492094d016ae3471affc8cce560facea5da91385"
)

MINIMUM_VALID_COUNT = 44
EXPECTED_INCLUDED_COUNT = 55
EXPECTED_REFERENCE_COUNT = 12
EXPECTED_SELECTION_RATE = Decimal("0.20")
_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_KINDS = tuple(BenchmarkKind)


class BenchmarkConstructionV22Error(RuntimeError):
    pass


@dataclass(frozen=True)
class BenchmarkActionEvidenceV22:
    public_security_id: str
    completed_session: date
    state: str
    adjustment_policy_version: str
    action_binding_hash: str
    source_hash: str
    available_at: datetime
    ingested_at: datetime


@dataclass(frozen=True)
class BenchmarkPriceSeriesBindingV22:
    public_security_id: str
    symbol: str
    completed_session: date
    bars_hash: str
    receipt_hash: str
    controlled_artifact_hash: str
    action_binding_hash: str
    adtv_observation_hash: str


@dataclass(frozen=True)
class BenchmarkEvidenceBundleV22:
    version: str
    decision_cutoff: datetime
    completed_session: date
    universe_version: str
    universe_hash: str
    preregistration_seal_hash: str
    future_price_execution_hash: str
    candidate_construction_hash: str
    benchmark_contract_hash: str
    parent_liquidity_cost_policy_hash: str
    cost_hash: str
    benchmarks: tuple[BenchmarkKindEvidenceV21, ...]
    bundle_hash: str


@dataclass(frozen=True)
class BenchmarkConstructionRequestV22:
    parent_preregistration: dict[str, Any]
    benchmark_preregistration: dict[str, Any]
    preregistration_seal: dict[str, Any]
    external_reference_universe: dict[str, Any]
    input_capture: dict[str, Any]
    input_coverage: dict[str, Any]
    candidate_construction: dict[str, Any]
    future_price_execution: dict[str, Any]
    price_series_bindings: tuple[BenchmarkPriceSeriesBindingV22, ...]
    action_evidence: tuple[BenchmarkActionEvidenceV22, ...]
    base_request: BenchmarkConstructionRequestV21


@dataclass(frozen=True)
class BenchmarkConstructionResultV22:
    bundle: BenchmarkEvidenceBundleV22
    controlled_ledger_set: ControlledBenchmarkLedgerSetV22
    git_safe_manifest: dict[str, Any]


def _verified(payload: dict[str, Any], label: str) -> str:
    fields = (
        "artifactContentHash",
        "preregistrationContentHash",
        "sealContentHash",
    )
    for field in fields:
        claim = payload.get(field)
        if claim is None:
            continue
        body = {key: value for key, value in payload.items() if key != field}
        if canonical_hash(body) != claim:
            raise BenchmarkConstructionV22Error(f"{label}_CANONICAL_HASH_MISMATCH")
        return str(claim)
    raise BenchmarkConstructionV22Error(f"{label}_CANONICAL_HASH_MISSING")


def _require_exact(
    payload: dict[str, Any],
    *,
    label: str,
    expected_hash: str,
) -> str:
    observed = _verified(payload, label)
    if observed != expected_hash:
        raise BenchmarkConstructionV22Error(f"{label}_FROZEN_HASH_MISMATCH")
    return observed


def _require_hash(value: str, label: str) -> None:
    if _HASH_PATTERN.fullmatch(value) is None:
        raise BenchmarkConstructionV22Error(f"{label}_SHA256_INVALID")


def _aware_before(
    value: datetime,
    cutoff: datetime,
    *,
    reason: str,
) -> None:
    if value.tzinfo is None or value.utcoffset() is None or value > cutoff:
        raise BenchmarkConstructionV22Error(reason)


def _bars_hash(rows: tuple[BenchmarkPriceBar, ...]) -> str:
    return canonical_hash(
        tuple(
            {
                "publicSecurityId": row.public_security_id,
                "sessionDate": row.session_date,
                "openPrice": row.open_price,
                "closePrice": row.close_price,
                "completedSession": row.completed_session,
                "qualityStatus": row.quality_status,
                "adjustmentMode": row.adjustment_mode,
                "priceEvidenceVersion": row.price_evidence_version,
                "validationDecisionHash": row.validation_decision_hash,
                "promotionEvidenceHash": row.promotion_evidence_hash,
                "availableAt": row.available_at,
                "ingestedAt": row.ingested_at,
                "sourceHash": row.source_hash,
            }
            for row in sorted(rows, key=lambda item: item.session_date)
        )
    )


def _validate_frozen_artifacts(
    request: BenchmarkConstructionRequestV22,
) -> tuple[str, str]:
    parent_hash = _require_exact(
        request.parent_preregistration,
        label="PARENT_PREREGISTRATION",
        expected_hash=PARENT_PREREGISTRATION_HASH,
    )
    prereg_hash = _require_exact(
        request.benchmark_preregistration,
        label="BENCHMARK_PREREGISTRATION_V22",
        expected_hash=BENCHMARK_PREREGISTRATION_V22_HASH,
    )
    seal_hash = _require_exact(
        request.preregistration_seal,
        label="PREREGISTRATION_SEAL_V22",
        expected_hash=PREREGISTRATION_SEAL_V22_HASH,
    )
    external_hash = _require_exact(
        request.external_reference_universe,
        label="EXTERNAL_REFERENCE_UNIVERSE_V22",
        expected_hash=EXTERNAL_REFERENCE_UNIVERSE_V22_HASH,
    )
    capture_hash = _require_exact(
        request.input_capture,
        label="INPUT_CAPTURE_V22",
        expected_hash=INPUT_CAPTURE_V22_HASH,
    )
    coverage_hash = _require_exact(
        request.input_coverage,
        label="INPUT_COVERAGE_V22",
        expected_hash=INPUT_COVERAGE_V22_HASH,
    )
    construction_hash = _require_exact(
        request.candidate_construction,
        label="CANDIDATE_CONSTRUCTION_V22",
        expected_hash=CANDIDATE_CONSTRUCTION_V22_HASH,
    )
    if (
        request.benchmark_preregistration.get("parentPreregistrationContentHash")
        != parent_hash
        or request.preregistration_seal.get("benchmarkPreregistration", {}).get(
            "artifactContentHash"
        )
        != prereg_hash
        or request.preregistration_seal.get("externalReferenceUniverse", {}).get(
            "artifactContentHash"
        )
        != external_hash
        or request.input_coverage.get("captureArtifactContentHash") != capture_hash
        or request.candidate_construction.get("captureArtifactContentHash")
        != capture_hash
        or request.candidate_construction.get("coverageArtifactContentHash")
        != coverage_hash
        or request.candidate_construction.get("candidatePolicyHash")
        != CANDIDATE_POLICY_V22_HASH
        or request.input_coverage.get("candidatePolicyHash")
        != CANDIDATE_POLICY_V22_HASH
        or construction_hash != CANDIDATE_CONSTRUCTION_V22_HASH
    ):
        raise BenchmarkConstructionV22Error("V22_ARTIFACT_HASH_CHAIN_MISMATCH")
    if request.input_capture.get("physicalAttempts") != 55 or request.input_capture.get(
        "retryCount"
    ) != 0:
        raise BenchmarkConstructionV22Error("V22_INPUT_CAPTURE_NOT_TERMINAL")
    for family in ("pureValue", "pureQuality"):
        coverage = request.input_coverage.get(family) or {}
        construction = request.candidate_construction.get(family) or {}
        if (
            coverage.get("coverageGatePassed") is not True
            or coverage.get("validCount") != EXPECTED_INCLUDED_COUNT
            or construction.get("validCandidateCount") != EXPECTED_INCLUDED_COUNT
            or construction.get("selectedCount")
            != math.ceil(EXPECTED_INCLUDED_COUNT * float(EXPECTED_SELECTION_RATE))
            or construction.get("status")
            != "CANDIDATE_SET_READY_PRICE_LIQUIDITY_COST_PENDING"
        ):
            raise BenchmarkConstructionV22Error(f"{family.upper()}_CANDIDATE_GATE_INVALID")
    return seal_hash, construction_hash


def _validate_population(request: BenchmarkConstructionRequestV22) -> None:
    parent_rows = request.parent_preregistration.get("prospectiveUniverse", {}).get(
        "securities"
    ) or []
    expected_included = {
        str(item["publicSecurityId"]): str(item["symbol"]).upper()
        for item in parent_rows
        if item.get("role") in {"PRIMARY", "RESERVE"}
    }
    external_rows = request.external_reference_universe.get("references") or []
    expected_references = {
        str(item["publicSecurityId"]): str(item["symbol"]).upper()
        for item in external_rows
    }
    included = {
        item.public_security_id: item.symbol.upper()
        for item in request.base_request.members
        if item.role == UniverseRole.INCLUDED
    }
    references = {
        item.public_security_id: item.symbol.upper()
        for item in request.base_request.members
        if item.role == UniverseRole.REFERENCE_ONLY
    }
    if (
        len(expected_included) != EXPECTED_INCLUDED_COUNT
        or included != expected_included
        or len(expected_references) != EXPECTED_REFERENCE_COUNT
        or references != expected_references
    ):
        raise BenchmarkConstructionV22Error("V22_STABLE_POPULATION_BINDING_MISMATCH")
    if any(item.role == UniverseRole.EXCLUDED for item in request.base_request.members):
        raise BenchmarkConstructionV22Error("EXCLUDED_SECURITY_ENTERED_BENCHMARK_REQUEST")


def _validate_future_price_execution(
    request: BenchmarkConstructionRequestV22,
    *,
    seal_hash: str,
) -> str:
    execution_hash = _verified(
        request.future_price_execution,
        "FUTURE_PRICE_EXECUTION_V2",
    )
    payload = request.future_price_execution
    expected_symbols = {item.symbol.upper() for item in request.base_request.members}
    receipts = payload.get("symbols") or []
    receipts_by_symbol = {str(item.get("symbol")).upper(): item for item in receipts}
    if (
        payload.get("artifactType") != "FUTURE_COMPLETED_SESSION_PRICE_HISTORY_CAPTURE"
        or payload.get("schemaVersion") != "FUTURE-PRICE-HISTORY-CAPTURE-v2.0.0"
        or payload.get("status") != "READY"
        or payload.get("providerRetryLimit") != 0
        or payload.get("preregistrationSealHash") != seal_hash
        or payload.get("externalReferenceUniverseHash")
        != EXTERNAL_REFERENCE_UNIVERSE_V22_HASH
        or payload.get("priceSymbolCount") != len(expected_symbols)
        or payload.get("readySymbolCount") != len(expected_symbols)
        or set(receipts_by_symbol) != expected_symbols
    ):
        raise BenchmarkConstructionV22Error("FUTURE_PRICE_EXECUTION_CONTRACT_INCOMPLETE")
    completed_session = date.fromisoformat(str(payload.get("targetSession")))
    if completed_session != request.base_request.decision_session:
        raise BenchmarkConstructionV22Error("COMMON_COMPLETED_SESSION_MISMATCH")
    binding_by_id = {
        item.public_security_id: item for item in request.price_series_bindings
    }
    actions_by_id = {item.public_security_id: item for item in request.action_evidence}
    members = {item.public_security_id: item for item in request.base_request.members}
    prices_by_id = _price_index(request.base_request.prices)
    liquidity_by_id = {
        item.public_security_id: item for item in request.base_request.liquidity
    }
    if (
        set(binding_by_id) != set(members)
        or set(actions_by_id) != set(members)
        or set(liquidity_by_id) != set(members)
        or set(prices_by_id) != set(members)
    ):
        raise BenchmarkConstructionV22Error("PRICE_ACTION_ADTV_SECURITY_COVERAGE_INCOMPLETE")
    for security_id, member in members.items():
        binding = binding_by_id[security_id]
        action = actions_by_id[security_id]
        receipt = receipts_by_symbol[member.symbol.upper()]
        liquidity = liquidity_by_id[security_id]
        if (
            binding.symbol.upper() != member.symbol.upper()
            or binding.completed_session != completed_session
            or action.completed_session != completed_session
            or liquidity.as_of_session != completed_session
            or action.state != "RECONCILED"
            or binding.bars_hash != _bars_hash(prices_by_id[security_id])
            or binding.receipt_hash != receipt.get("receiptHash")
            or binding.controlled_artifact_hash
            != receipt.get("controlledArtifactContentHash")
            or binding.action_binding_hash != receipt.get("actionBindingHash")
            or action.action_binding_hash != receipt.get("actionBindingHash")
            or binding.adtv_observation_hash != receipt.get("adtvObservationHash")
            or liquidity.source_hash != receipt.get("adtvObservationHash")
            or receipt.get("targetSession") != completed_session.isoformat()
            or receipt.get("historyCoverageState") != "READY"
            or receipt.get("adjustmentMode") != "TOTAL_RETURN_ADJUSTED"
        ):
            raise BenchmarkConstructionV22Error(
                f"PRICE_ACTION_ADTV_BINDING_MISMATCH[{member.symbol.upper()}]"
            )
        _require_hash(action.action_binding_hash, "ACTION_BINDING_HASH")
        _require_hash(action.source_hash, "ACTION_SOURCE_HASH")
        _aware_before(
            action.available_at,
            request.base_request.decision_cutoff,
            reason="ACTION_NOT_AVAILABLE_AT_DECISION_CUTOFF",
        )
        _aware_before(
            action.ingested_at,
            request.base_request.decision_cutoff,
            reason="ACTION_NOT_INGESTED_AT_DECISION_CUTOFF",
        )
    return execution_hash


def _candidate_variant(
    *,
    kind: BenchmarkKind,
    request: BenchmarkConstructionRequestV22,
    included: tuple[BenchmarkUniverseSecurity, ...],
    prices: dict[str, tuple[BenchmarkPriceBar, ...]],
    liquidity_by_id: dict[str, BenchmarkLiquidityEvidence],
) -> BenchmarkVariantEvidenceV21:
    key = "pureValue" if kind == BenchmarkKind.PURE_VALUE else "pureQuality"
    construction = request.candidate_construction[key]
    selected_rows = construction.get("selected") or []
    selected_ids = tuple(str(item.get("publicSecurityId")) for item in selected_rows)
    selected_ranks = tuple(int(item.get("rank") or 0) for item in selected_rows)
    expected_count = math.ceil(EXPECTED_INCLUDED_COUNT * float(EXPECTED_SELECTION_RATE))
    included_by_id = {item.public_security_id: item for item in included}
    reasons: set[str] = set()
    if (
        len(included) != EXPECTED_INCLUDED_COUNT
        or construction.get("validCandidateCount") < MINIMUM_VALID_COUNT
    ):
        reasons.add("V22_VALID_COVERAGE_BELOW_44_OF_55")
    if (
        len(selected_ids) != expected_count
        or len(set(selected_ids)) != expected_count
        or selected_ranks != tuple(range(1, expected_count + 1))
        or any(security_id not in included_by_id for security_id in selected_ids)
    ):
        reasons.add("V22_TOP_QUINTILE_SELECTION_INVALID")
    selected_price_rows: list[BenchmarkPriceBar] = []
    selected_liquidity_rows: list[BenchmarkLiquidityEvidence] = []
    for security_id in selected_ids:
        rows, price_reasons = _validated_prices(
            security_id=security_id,
            prices=prices,
            request=request.base_request,
        )
        selected_price_rows.extend(rows)
        reasons.update(price_reasons)
        liquidity, liquidity_reasons = _validated_liquidity(
            security_id=security_id,
            liquidity_by_id=liquidity_by_id,
            request=request.base_request,
        )
        reasons.update(liquidity_reasons)
        if liquidity is not None:
            selected_liquidity_rows.append(liquidity)
    liquidity_map = {item.public_security_id: item for item in selected_liquidity_rows}
    holdings: tuple[BenchmarkHoldingV21, ...] = ()
    if len(liquidity_map) == len(selected_ids) and not reasons:
        holdings = tuple(
            _holding(
                included_by_id[security_id],
                rank=index,
                total=len(selected_ids),
                liquidity=liquidity_map[security_id],
                cost_policy=request.base_request.cost_policy,
            )
            for index, security_id in enumerate(selected_ids, start=1)
        )
    construction_version = (
        PURE_VALUE_CONSTRUCTION_V22
        if kind == BenchmarkKind.PURE_VALUE
        else PURE_QUALITY_CONSTRUCTION_V22
    )
    return _variant(
        identifier=f"{kind.value}-MECHANICAL-TOP-QUINTILE",
        construction_version=construction_version,
        sector=None,
        population_count=len(included),
        eligible_count=int(construction.get("validCandidateCount") or 0),
        holdings=holdings,
        reasons=tuple(sorted(reasons)),
        source_rows={
            "members": _member_sources(included),
            "candidateConstructionHash": CANDIDATE_CONSTRUCTION_V22_HASH,
            "selectedPrices": _price_sources(
                tuple(
                    sorted(
                        selected_price_rows,
                        key=lambda row: (
                            row.public_security_id,
                            row.session_date,
                        ),
                    )
                )
            ),
            "selectedLiquidity": tuple(
                _liquidity_payload(item)
                for item in sorted(
                    selected_liquidity_rows,
                    key=lambda row: row.public_security_id,
                )
            ),
        },
        selection_rows={
            "policy": construction_version,
            "validOnly": True,
            "minimumCoverage": "44_OF_55",
            "selectionRate": "0.20",
            "rounding": "CEILING",
            "tieBreak": "PUBLIC_SECURITY_ID_ASCENDING",
            "selectedSecurityIds": selected_ids,
        },
        cost_policy=request.base_request.cost_policy,
    )


def _kind_evidence_v22(
    kind: BenchmarkKind,
    variants: tuple[BenchmarkVariantEvidenceV21, ...],
) -> BenchmarkKindEvidenceV21:
    if kind not in {BenchmarkKind.PURE_VALUE, BenchmarkKind.PURE_QUALITY}:
        return _kind_evidence(kind, variants)
    reasons = tuple(
        sorted(
            {
                reason
                for variant in variants
                if variant.state != BenchmarkConstructionState.AVAILABLE
                for reason in variant.reason_codes
            }
        )
    )
    state = (
        BenchmarkConstructionState.AVAILABLE
        if variants and all(item.state == BenchmarkConstructionState.AVAILABLE for item in variants)
        else BenchmarkConstructionState.MISSING
    )
    method = (
        PURE_VALUE_CONSTRUCTION_V22
        if kind == BenchmarkKind.PURE_VALUE
        else PURE_QUALITY_CONSTRUCTION_V22
    )
    terminal = {
        "kind": kind.value,
        "benchmarkId": f"{kind.value}-MECHANICAL-TOP-QUINTILE",
        "constructionMethod": method,
        "state": state.value,
        "reasonCodes": reasons,
        "variants": tuple(item.evidence_hash for item in variants),
    }
    terminal_hash = canonical_hash(terminal)
    if state != BenchmarkConstructionState.AVAILABLE:
        return BenchmarkKindEvidenceV21(
            kind=kind,
            benchmark_id=f"{kind.value}-MECHANICAL-TOP-QUINTILE",
            construction_method=method,
            state=state,
            reason_codes=reasons,
            variants=variants,
            evidence_hash=None,
            source_evidence_hash=None,
            constituent_set_hash=None,
            weight_hash=None,
            selection_hash=None,
            cost_evidence_hash=None,
            sector_assignment_hash=None,
            terminal_hash=terminal_hash,
        )
    source_hash = canonical_hash(tuple(item.source_evidence_hash for item in variants))
    constituent_hash = canonical_hash(tuple(item.constituent_set_hash for item in variants))
    weight_hash = canonical_hash(tuple(item.weight_hash for item in variants))
    selection_hash = canonical_hash(tuple(item.selection_hash for item in variants))
    cost_hash = canonical_hash(tuple(item.cost_evidence_hash for item in variants))
    evidence_hash = canonical_hash(
        {
            **terminal,
            "sourceEvidenceHash": source_hash,
            "constituentSetHash": constituent_hash,
            "weightHash": weight_hash,
            "selectionHash": selection_hash,
            "costEvidenceHash": cost_hash,
            "sectorAssignmentHash": None,
        }
    )
    return BenchmarkKindEvidenceV21(
        kind=kind,
        benchmark_id=f"{kind.value}-MECHANICAL-TOP-QUINTILE",
        construction_method=method,
        state=state,
        reason_codes=reasons,
        variants=variants,
        evidence_hash=evidence_hash,
        source_evidence_hash=source_hash,
        constituent_set_hash=constituent_hash,
        weight_hash=weight_hash,
        selection_hash=selection_hash,
        cost_evidence_hash=cost_hash,
        sector_assignment_hash=None,
        terminal_hash=terminal_hash,
    )


def _git_safe_family(item: BenchmarkKindEvidenceV21) -> dict[str, Any]:
    return {
        "kind": item.kind.value,
        "benchmarkId": item.benchmark_id,
        "constructionMethod": item.construction_method,
        "state": item.state.value,
        "reasonCodes": list(item.reason_codes),
        "variantCount": len(item.variants),
        "holdingCount": sum(len(variant.holdings) for variant in item.variants),
        "constituentSetHash": item.constituent_set_hash,
        "weightHash": item.weight_hash,
        "selectionHash": item.selection_hash,
        "costEvidenceHash": item.cost_evidence_hash,
        "sourceEvidenceHash": item.source_evidence_hash,
        "sectorAssignmentHash": item.sector_assignment_hash,
        "evidenceHash": item.evidence_hash,
        "terminalHash": item.terminal_hash,
    }


def build_benchmark_evidence_bundle_v22(
    request: BenchmarkConstructionRequestV22,
) -> BenchmarkConstructionResultV22:
    seal_hash, candidate_hash = _validate_frozen_artifacts(request)
    _validate_request(request.base_request)
    _validate_population(request)
    price_execution_hash = _validate_future_price_execution(
        request,
        seal_hash=seal_hash,
    )
    members_by_id = {
        item.public_security_id: item for item in request.base_request.members
    }
    included = tuple(
        sorted(
            (
                item
                for item in request.base_request.members
                if item.role == UniverseRole.INCLUDED
            ),
            key=lambda item: item.public_security_id,
        )
    )
    prices = _price_index(request.base_request.prices)
    liquidity_by_id = {
        item.public_security_id: item for item in request.base_request.liquidity
    }
    benchmarks = (
        _kind_evidence(
            BenchmarkKind.SPY,
            (
                _market_variant(
                    request.base_request,
                    members_by_id,
                    prices,
                    liquidity_by_id,
                ),
            ),
        ),
        _kind_evidence(
            BenchmarkKind.SECTOR,
            _sector_variants(
                request.base_request,
                included,
                members_by_id,
                prices,
                liquidity_by_id,
            ),
        ),
        _kind_evidence(
            BenchmarkKind.EQUAL_WEIGHT,
            (
                _equal_weight_variant(
                    request.base_request,
                    included,
                    prices,
                    liquidity_by_id,
                ),
            ),
        ),
        _kind_evidence(
            BenchmarkKind.PURE_MOMENTUM,
            (
                _momentum_variant(
                    request.base_request,
                    included,
                    prices,
                    liquidity_by_id,
                ),
            ),
        ),
        _kind_evidence_v22(
            BenchmarkKind.PURE_VALUE,
            (
                _candidate_variant(
                    kind=BenchmarkKind.PURE_VALUE,
                    request=request,
                    included=included,
                    prices=prices,
                    liquidity_by_id=liquidity_by_id,
                ),
            ),
        ),
        _kind_evidence_v22(
            BenchmarkKind.PURE_QUALITY,
            (
                _candidate_variant(
                    kind=BenchmarkKind.PURE_QUALITY,
                    request=request,
                    included=included,
                    prices=prices,
                    liquidity_by_id=liquidity_by_id,
                ),
            ),
        ),
    )
    if tuple(item.kind for item in benchmarks) != _REQUIRED_KINDS:
        raise BenchmarkConstructionV22Error("EXACT_SIX_BENCHMARK_KINDS_REQUIRED")
    cost_hash = canonical_hash(request.base_request.cost_policy)
    contract_hash = canonical_hash(
        {
            "version": BENCHMARK_CONSTRUCTION_V22,
            "requiredKinds": tuple(kind.value for kind in _REQUIRED_KINDS),
            "predecessorConstruction": "FORWARD-BENCHMARK-CONSTRUCTION-v2.1.0",
            "pureValuePolicy": PURE_VALUE_CONSTRUCTION_V22,
            "pureQualityPolicy": PURE_QUALITY_CONSTRUCTION_V22,
            "minimumValidCount": MINIMUM_VALID_COUNT,
            "includedCount": EXPECTED_INCLUDED_COUNT,
            "selectionRate": EXPECTED_SELECTION_RATE,
            "tieBreak": "PUBLIC_SECURITY_ID_ASCENDING",
            "parentLiquidityCostPolicyHash": (
                request.base_request.parent_liquidity_cost_policy_hash
            ),
            "costPolicyHash": cost_hash,
        }
    )
    bundle_body = {
        "version": BENCHMARK_CONSTRUCTION_V22,
        "decisionCutoff": request.base_request.decision_cutoff,
        "completedSession": request.base_request.decision_session,
        "universeVersion": request.base_request.universe_version,
        "universeHash": request.base_request.universe_hash,
        "preregistrationSealHash": seal_hash,
        "futurePriceExecutionHash": price_execution_hash,
        "candidateConstructionHash": candidate_hash,
        "benchmarkContractHash": contract_hash,
        "parentLiquidityCostPolicyHash": (
            request.base_request.parent_liquidity_cost_policy_hash
        ),
        "costHash": cost_hash,
        "benchmarks": tuple(item.terminal_hash for item in benchmarks),
    }
    bundle_hash = canonical_hash(bundle_body)
    bundle = BenchmarkEvidenceBundleV22(
        version=BENCHMARK_CONSTRUCTION_V22,
        decision_cutoff=request.base_request.decision_cutoff,
        completed_session=request.base_request.decision_session,
        universe_version=request.base_request.universe_version,
        universe_hash=request.base_request.universe_hash,
        preregistration_seal_hash=seal_hash,
        future_price_execution_hash=price_execution_hash,
        candidate_construction_hash=candidate_hash,
        benchmark_contract_hash=contract_hash,
        parent_liquidity_cost_policy_hash=(
            request.base_request.parent_liquidity_cost_policy_hash
        ),
        cost_hash=cost_hash,
        benchmarks=benchmarks,
        bundle_hash=bundle_hash,
    )
    controlled_ledger = build_controlled_benchmark_ledger_set_v22(
        bundle=bundle,
        request=request,
    )
    family_rows = [_git_safe_family(item) for item in benchmarks]
    manifest_body = {
        "artifactType": "FORWARD_BENCHMARK_CONSTRUCTION_MANIFEST",
        "schemaVersion": SUCCESSOR_BENCHMARK_MANIFEST_V22,
        "status": (
            "READY"
            if all(
                item.state == BenchmarkConstructionState.AVAILABLE
                for item in benchmarks
            )
            else "BLOCKED"
        ),
        "completedSession": request.base_request.decision_session.isoformat(),
        "decisionCutoff": request.base_request.decision_cutoff.isoformat(),
        "universeVersion": request.base_request.universe_version,
        "universeHash": request.base_request.universe_hash,
        "preregistrationSealHash": seal_hash,
        "futurePriceExecutionHash": price_execution_hash,
        "inputCaptureHash": INPUT_CAPTURE_V22_HASH,
        "inputCoverageHash": INPUT_COVERAGE_V22_HASH,
        "candidateConstructionHash": candidate_hash,
        "benchmarkContractHash": contract_hash,
        "parentLiquidityCostPolicyHash": (
            request.base_request.parent_liquidity_cost_policy_hash
        ),
        "costHash": cost_hash,
        "controlledBundleHash": bundle_hash,
        "controlledLedgerSetHash": controlled_ledger.ledger_content_hash,
        "controlledLedgerSetReference": controlled_ledger.controlled_reference,
        "families": family_rows,
        "requiredKinds": [kind.value for kind in _REQUIRED_KINDS],
        "allSixAvailable": all(
            item.state == BenchmarkConstructionState.AVAILABLE
            for item in benchmarks
        ),
        "includedPopulationCount": EXPECTED_INCLUDED_COUNT,
        "externalReferenceCount": EXPECTED_REFERENCE_COUNT,
        "providerNetworkRequestsExecuted": 0,
        "databaseWritesExecuted": 0,
        "enrollmentExecuted": False,
        "scoresOrRanksComputed": False,
        "rawProviderValuesIncluded": False,
        "automaticTradingAuthorized": False,
    }
    manifest = {
        **manifest_body,
        "artifactContentHash": canonical_hash(manifest_body),
    }
    return BenchmarkConstructionResultV22(
        bundle=bundle,
        controlled_ledger_set=controlled_ledger,
        git_safe_manifest=manifest,
    )


def file_sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
