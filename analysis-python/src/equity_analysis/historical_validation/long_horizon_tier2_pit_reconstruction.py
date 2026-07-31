from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

from equity_analysis.historical_validation.long_horizon_tier1_retrospective import (
    MODEL_FREEZE_PATH,
    MODEL_VERSION,
    PRICE_MANIFEST_PATH,
    UNIVERSE_PATH,
    _load_prices,
    _role_map,
    _verified_artifact_hash,
)
from equity_analysis.historical_validation.model_freeze_v1 import (
    canonical_hash,
    file_sha256,
    verify_model_freeze_artifact,
)

LONG_HORIZON_TIER2_VERSION = (
    "LONG-HORIZON-v1.1-TIER2-PIT-RECONSTRUCTION-v1.0.0"
)
SEC_V4_MANIFEST_PATH = Path(
    "docs/generated/scoring-input-v4-sec-offline-manifest-v2.json"
)
CONTROLLED_STORAGE_ROOT = Path(
    "storage/historical-validation/long-horizon-v11-tier2"
)
ANCHOR_SESSION_OFFSETS = {
    "ONE_YEAR_AGO": 252,
    "TWO_YEARS_AGO": 504,
    "THREE_YEARS_AGO": 756,
    "FIVE_YEARS_AGO": 1260,
}
DIMENSION_FACTORS = {
    "BUSINESS_QUALITY": (
        "return_on_invested_capital",
        "operating_margin",
        "free_cash_flow_margin",
        "earnings_stability",
        "cash_flow_stability",
    ),
    "SECURITY_ATTRACTIVENESS": (
        "free_cash_flow_yield",
        "earnings_yield",
        "enterprise_value_to_ebitda",
        "own_history_valuation_attractiveness",
    ),
    "DOWNSIDE_RISK": (
        "net_debt_to_ebitda",
        "interest_coverage",
        "earnings_stability",
        "cash_flow_stability",
        "diluted_share_growth",
        "cyclicality_risk",
        "concentration_risk",
        "event_risk",
    ),
}
FACTOR_REQUIREMENTS = {
    "operating_margin": (("operating_income", "revenue"), 4),
    "free_cash_flow_margin": (
        ("operating_cash_flow", "capital_expenditure", "revenue"),
        4,
    ),
    "earnings_stability": (("net_income",), 8),
    "cash_flow_stability": (("operating_cash_flow",), 8),
    "diluted_share_growth": (
        ("diluted_weighted_average_shares",),
        8,
    ),
}
PARTIAL_FACTOR_REQUIREMENTS = {
    "return_on_invested_capital": (
        (
            "operating_income",
            "income_tax",
            "cash_and_equivalents",
            "stockholders_equity",
        ),
        4,
        "TOTAL_DEBT_COMPONENT_NON_OVERLAP_NOT_PROVEN",
    ),
    "free_cash_flow_yield": (
        ("operating_cash_flow", "capital_expenditure"),
        4,
        "HISTORICAL_MARKET_CAP_SHARE_CLASS_MATCH_NOT_PROVEN",
    ),
    "earnings_yield": (
        ("net_income",),
        4,
        "HISTORICAL_MARKET_CAP_SHARE_CLASS_MATCH_NOT_PROVEN",
    ),
}
STRUCTURAL_BLOCKERS = {
    "enterprise_value_to_ebitda": (
        "HISTORICAL_ENTERPRISE_VALUE_PIT_UNPROVEN",
        "HISTORICAL_EBITDA_PIT_UNPROVEN",
    ),
    "own_history_valuation_attractiveness": (
        "HISTORICAL_VALUATION_DISTRIBUTION_PIT_UNPROVEN",
    ),
    "net_debt_to_ebitda": (
        "TOTAL_DEBT_COMPONENT_NON_OVERLAP_NOT_PROVEN",
        "HISTORICAL_EBITDA_PIT_UNPROVEN",
    ),
    "interest_coverage": (
        "HISTORICAL_GROSS_INTEREST_TTM_SCOPE_UNPROVEN",
    ),
    "cyclicality_risk": ("HISTORICAL_CYCLICALITY_EVIDENCE_MISSING",),
    "concentration_risk": (
        "HISTORICAL_CONCENTRATION_EVIDENCE_MISSING",
    ),
    "event_risk": ("HISTORICAL_EVENT_RISK_EVIDENCE_MISSING",),
}


class LongHorizonTier2Error(RuntimeError):
    pass


@dataclass(frozen=True)
class EvidencePoint:
    operand: str
    period_start: str
    period_end: str
    duration_class: str
    available_at: datetime
    observation_id: str
    content_hash: str
    source_kind: str
    mapping_priority: int

    @property
    def period_key(self) -> tuple[str, str]:
        return (self.period_start, self.period_end)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LongHorizonTier2Error(f"Expected JSON object: {path}")
    return value


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise LongHorizonTier2Error("Evidence availability timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LongHorizonTier2Error("Evidence timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _verify_sec_manifest(manifest: dict[str, Any]) -> str:
    claim = manifest.get("artifactContentHash")
    if not isinstance(claim, str):
        raise LongHorizonTier2Error("SEC v4 manifest hash missing")
    body = dict(manifest)
    body.pop("artifactContentHash")
    if canonical_hash(body) != claim:
        raise LongHorizonTier2Error("SEC v4 manifest hash mismatch")
    if manifest.get("networkRequestsExecuted") is not False:
        raise LongHorizonTier2Error("SEC v4 manifest must be offline")
    return claim


def _load_verified_sec_payload(
    repository_root: Path,
    record: dict[str, Any],
) -> dict[str, Any]:
    reference = record.get("storageReference")
    expected = record.get("payloadContentHash")
    if not isinstance(reference, str) or not isinstance(expected, str):
        raise LongHorizonTier2Error("SEC payload binding missing")
    path = repository_root / reference
    payload = _load_object(path)
    if canonical_hash(payload) != expected:
        raise LongHorizonTier2Error(
            f"SEC payload content hash mismatch: {record.get('symbol')}"
        )
    if path.stem.upper() != expected.upper():
        raise LongHorizonTier2Error(
            f"SEC payload filename hash mismatch: {record.get('symbol')}"
        )
    if str(payload.get("symbol", "")).upper() != str(
        record.get("symbol", "")
    ).upper():
        raise LongHorizonTier2Error("SEC payload symbol mismatch")
    return payload


def _candidate_points(
    payload: dict[str, Any],
    cutoff: datetime,
) -> tuple[EvidencePoint, ...]:
    points: list[EvidencePoint] = []
    for source_kind, records in (
        ("SEC_OBSERVATION", payload.get("observations") or []),
        ("SEC_APPROVED_DERIVATION", payload.get("derivations") or []),
    ):
        if not isinstance(records, list):
            raise LongHorizonTier2Error("SEC evidence collection is invalid")
        for record in records:
            if not isinstance(record, dict):
                raise LongHorizonTier2Error("SEC evidence row is invalid")
            available_at = _parse_datetime(record.get("availableAt"))
            if available_at > cutoff:
                continue
            duration = record.get("durationClass")
            start = record.get("periodStart")
            end = record.get("periodEnd")
            operand = record.get("normalizedOperand")
            observation_id = record.get("observationId")
            content_hash = record.get("contentHash")
            if not all(
                isinstance(item, str) and item
                for item in (
                    duration,
                    start,
                    end,
                    operand,
                    observation_id,
                    content_hash,
                )
            ):
                continue
            body = dict(record)
            body.pop("contentHash", None)
            body.pop("observationId", None)
            if canonical_hash(body) != content_hash:
                raise LongHorizonTier2Error(
                    f"SEC evidence row hash mismatch: {observation_id}"
                )
            expected_prefix = (
                "sec-derived:"
                if source_kind == "SEC_APPROVED_DERIVATION"
                else "sec-fact:"
            )
            if observation_id != expected_prefix + content_hash:
                raise LongHorizonTier2Error(
                    f"SEC evidence ID mismatch: {observation_id}"
                )
            points.append(
                EvidencePoint(
                    operand=operand,
                    period_start=start,
                    period_end=end,
                    duration_class=duration,
                    available_at=available_at,
                    observation_id=observation_id,
                    content_hash=content_hash,
                    source_kind=source_kind,
                    mapping_priority=int(record.get("mappingPriority", 999)),
                )
            )
    return tuple(points)


def _latest_pre_cutoff_points(
    points: Iterable[EvidencePoint],
) -> dict[str, dict[tuple[str, str], EvidencePoint]]:
    selected: dict[
        tuple[str, str, str, str], EvidencePoint
    ] = {}
    for point in points:
        key = (
            point.operand,
            point.period_start,
            point.period_end,
            point.duration_class,
        )
        previous = selected.get(key)
        if previous is None:
            selected[key] = point
            continue
        candidate_order = (
            -point.mapping_priority,
            point.available_at,
            point.observation_id,
        )
        previous_order = (
            -previous.mapping_priority,
            previous.available_at,
            previous.observation_id,
        )
        if candidate_order > previous_order:
            selected[key] = point
    by_operand: dict[str, dict[tuple[str, str], EvidencePoint]] = {}
    for point in selected.values():
        if point.duration_class != "DISCRETE_QUARTER":
            continue
        by_operand.setdefault(point.operand, {})[point.period_key] = point
    return by_operand


def _aligned_evidence(
    by_operand: dict[str, dict[tuple[str, str], EvidencePoint]],
    operands: tuple[str, ...],
    required_periods: int,
) -> dict[str, Any]:
    if not operands:
        raise ValueError("At least one operand is required")
    period_sets = [
        set(by_operand.get(operand, {}))
        for operand in operands
    ]
    operand_counts = {
        operand: len(by_operand.get(operand, {}))
        for operand in operands
    }
    common = set.intersection(*period_sets) if period_sets else set()
    ordered = sorted(common, key=lambda item: (item[1], item[0]))
    selected = ordered[-required_periods:]
    evidence = [
        {
            "periodStart": period_start,
            "periodEnd": period_end,
            "operands": [
                {
                    "operand": operand,
                    "observationId": by_operand[operand][
                        (period_start, period_end)
                    ].observation_id,
                    "contentHash": by_operand[operand][
                        (period_start, period_end)
                    ].content_hash,
                    "availableAt": by_operand[operand][
                        (period_start, period_end)
                    ].available_at.isoformat(),
                    "sourceKind": by_operand[operand][
                        (period_start, period_end)
                    ].source_kind,
                }
                for operand in operands
            ],
        }
        for period_start, period_end in selected
    ]
    return {
        "requiredAlignedPeriods": required_periods,
        "operandAvailablePeriodCounts": operand_counts,
        "availableAlignedPeriods": len(ordered),
        "selectedPeriods": evidence,
        "inputSetComplete": len(selected) == required_periods,
    }


def _alignment_reason_codes(evidence: dict[str, Any]) -> list[str]:
    required = int(evidence["requiredAlignedPeriods"])
    insufficient = [
        str(operand)
        for operand, count in evidence[
            "operandAvailablePeriodCounts"
        ].items()
        if int(count) < required
    ]
    reasons = [
        f"INSUFFICIENT_PIT_QUARTERS_{operand.upper()}"
        for operand in insufficient
    ]
    if (
        not reasons
        and int(evidence["availableAlignedPeriods"]) < required
    ):
        reasons.append("PIT_PERIOD_ALIGNMENT_INCOMPLETE")
    return reasons


def _factor_evidence(
    by_operand: dict[str, dict[tuple[str, str], EvidencePoint]],
    factor: str,
) -> dict[str, Any]:
    if factor in FACTOR_REQUIREMENTS:
        operands, periods = FACTOR_REQUIREMENTS[factor]
        evidence = _aligned_evidence(by_operand, operands, periods)
        return {
            "factor": factor,
            "state": (
                "RECONSTRUCTABLE_INPUT_SET"
                if evidence["inputSetComplete"]
                else "MISSING"
            ),
            "reasonCodes": (
                []
                if evidence["inputSetComplete"]
                else _alignment_reason_codes(evidence)
            ),
            "evidence": evidence,
            "factorValueComputed": False,
        }
    if factor in PARTIAL_FACTOR_REQUIREMENTS:
        operands, periods, blocker = PARTIAL_FACTOR_REQUIREMENTS[factor]
        evidence = _aligned_evidence(by_operand, operands, periods)
        state = (
            "PARTIAL_PRIMITIVES"
            if evidence["inputSetComplete"]
            else "MISSING"
        )
        reasons = [blocker]
        if not evidence["inputSetComplete"]:
            reasons.extend(_alignment_reason_codes(evidence))
        return {
            "factor": factor,
            "state": state,
            "reasonCodes": reasons,
            "evidence": evidence,
            "factorValueComputed": False,
        }
    return {
        "factor": factor,
        "state": "MISSING",
        "reasonCodes": list(
            STRUCTURAL_BLOCKERS.get(
                factor,
                ("UPSTREAM_FACTOR_ASSEMBLY_CONTRACT_NOT_AVAILABLE",),
            )
        ),
        "evidence": None,
        "factorValueComputed": False,
    }


def _dimension_evidence(
    by_operand: dict[str, dict[tuple[str, str], EvidencePoint]],
    dimension: str,
) -> dict[str, Any]:
    factors = [
        _factor_evidence(by_operand, factor)
        for factor in DIMENSION_FACTORS[dimension]
    ]
    states = {item["state"] for item in factors}
    if states == {"RECONSTRUCTABLE_INPUT_SET"}:
        state = "RECONSTRUCTABLE_INPUT_SET"
    elif states & {"RECONSTRUCTABLE_INPUT_SET", "PARTIAL_PRIMITIVES"}:
        state = "PARTIAL_PRIMITIVES"
    else:
        state = "MISSING"
    return {
        "dimension": dimension,
        "state": state,
        "dimensionScoreComputed": False,
        "factors": factors,
    }


def _anchor_dates(
    spy_bars: tuple[Any, ...],
) -> tuple[dict[str, Any], ...]:
    anchors: list[dict[str, Any]] = []
    for label, offset in ANCHOR_SESSION_OFFSETS.items():
        if len(spy_bars) <= offset:
            raise LongHorizonTier2Error(
                f"SPY history cannot support anchor: {label}"
            )
        trading_date = spy_bars[-(offset + 1)].trading_date
        cutoff = datetime.combine(
            datetime.fromisoformat(trading_date).date(),
            time(23, 59, 59),
            tzinfo=UTC,
        )
        anchors.append(
            {
                "label": label,
                "sessionsBeforeLatestCompleteSession": offset,
                "anchorTradingDate": trading_date,
                "cutoff": cutoff,
            }
        )
    return tuple(anchors)


def _terminal_dimension_counts(
    security_records: list[dict[str, Any]],
    dimension: str,
) -> dict[str, int]:
    counter = Counter(
        record["dimensions"][dimension]["state"]
        for record in security_records
    )
    return {
        state: counter.get(state, 0)
        for state in (
            "RECONSTRUCTABLE_INPUT_SET",
            "PARTIAL_PRIMITIVES",
            "MISSING",
        )
    }


def _factor_state_counts(
    security_records: list[dict[str, Any]],
    dimension: str,
) -> dict[str, dict[str, int]]:
    counters = {
        factor: Counter()
        for factor in DIMENSION_FACTORS[dimension]
    }
    for record in security_records:
        for factor in record["dimensions"][dimension]["factors"]:
            counters[factor["factor"]][factor["state"]] += 1
    return {
        factor: {
            state: counter.get(state, 0)
            for state in (
                "RECONSTRUCTABLE_INPUT_SET",
                "PARTIAL_PRIMITIVES",
                "MISSING",
            )
        }
        for factor, counter in counters.items()
    }


def build_long_horizon_tier2_pit_reconstruction(
    repository_root: Path,
    *,
    generated_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")

    universe_path = repository_root / UNIVERSE_PATH
    universe = _load_object(universe_path)
    roles = _role_map(universe)
    candidates = tuple(
        sorted(
            symbol
            for symbol, role in roles.items()
            if role in {"PRIMARY", "RESERVE"}
        )
    )

    freeze_path = repository_root / MODEL_FREEZE_PATH
    freeze = _load_object(freeze_path)
    verify_model_freeze_artifact(repository_root, freeze)
    if freeze.get("modelVersion") != MODEL_VERSION:
        raise LongHorizonTier2Error("Long Horizon model freeze mismatch")

    price_manifest_path = repository_root / PRICE_MANIFEST_PATH
    price_manifest = _load_object(price_manifest_path)
    price_manifest_hash = _verified_artifact_hash(
        price_manifest,
        "Historical Yahoo manifest",
    )
    if file_sha256(universe_path) != price_manifest.get(
        "universeFileSha256"
    ):
        raise LongHorizonTier2Error("Universe hash binding mismatch")
    prices, _ = _load_prices(repository_root, price_manifest)
    if "SPY" not in prices:
        raise LongHorizonTier2Error("SPY benchmark evidence is missing")
    anchors = _anchor_dates(prices["SPY"])

    sec_manifest_path = repository_root / SEC_V4_MANIFEST_PATH
    sec_manifest = _load_object(sec_manifest_path)
    sec_manifest_hash = _verify_sec_manifest(sec_manifest)
    sec_by_symbol = {
        str(record.get("symbol", "")).upper(): record
        for record in sec_manifest.get("securities") or []
        if isinstance(record, dict)
    }
    payloads: dict[str, dict[str, Any]] = {}
    missing_sec_reason: dict[str, str] = {}
    for symbol in candidates:
        record = sec_by_symbol.get(symbol)
        if record is None:
            missing_sec_reason[symbol] = (
                "SEC_V4_AUTHORITATIVE_MANIFEST_SECURITY_ABSENT"
            )
        elif record.get("status") != "SEC_TIMELINE_BUILT":
            missing_sec_reason[symbol] = str(
                (record.get("reasonCodes") or ["SEC_TIMELINE_NOT_BUILT"])[0]
            )
        else:
            payloads[symbol] = _load_verified_sec_payload(
                repository_root,
                record,
            )

    controlled_anchors: list[dict[str, Any]] = []
    for anchor in anchors:
        security_records: list[dict[str, Any]] = []
        cutoff = anchor["cutoff"]
        for symbol in candidates:
            if symbol not in payloads:
                dimensions = {
                    dimension: {
                        "dimension": dimension,
                        "state": "MISSING",
                        "dimensionScoreComputed": False,
                        "factors": [
                            {
                                "factor": factor,
                                "state": "MISSING",
                                "reasonCodes": [
                                    missing_sec_reason[symbol]
                                ],
                                "evidence": None,
                                "factorValueComputed": False,
                            }
                            for factor in DIMENSION_FACTORS[dimension]
                        ],
                    }
                    for dimension in DIMENSION_FACTORS
                }
                point_count = 0
                operand_count = 0
            else:
                points = _candidate_points(payloads[symbol], cutoff)
                by_operand = _latest_pre_cutoff_points(points)
                dimensions = {
                    dimension: _dimension_evidence(
                        by_operand,
                        dimension,
                    )
                    for dimension in DIMENSION_FACTORS
                }
                point_count = sum(len(values) for values in by_operand.values())
                operand_count = len(by_operand)
            security_records.append(
                {
                    "symbol": symbol,
                    "role": roles[symbol],
                    "secTimelineState": (
                        "HASH_VERIFIED"
                        if symbol in payloads
                        else "MISSING"
                    ),
                    "availableDiscreteQuarterEvidenceCount": point_count,
                    "availableOperandCount": operand_count,
                    "dimensions": dimensions,
                    "modelExecuted": False,
                    "aggregateRankComputed": False,
                }
            )

        reason_counter: Counter[str] = Counter()
        for record in security_records:
            for dimension in record["dimensions"].values():
                for factor in dimension["factors"]:
                    reason_counter.update(factor["reasonCodes"])
        controlled_anchors.append(
            {
                "label": anchor["label"],
                "sessionsBeforeLatestCompleteSession": anchor[
                    "sessionsBeforeLatestCompleteSession"
                ],
                "anchorTradingDate": anchor["anchorTradingDate"],
                "cutoff": cutoff.isoformat(),
                "cutoffPolicy": "DIAGNOSTIC_ANCHOR_SESSION_END_UTC",
                "securityRecords": security_records,
                "aggregate": {
                    "candidateCount": len(candidates),
                    "hashVerifiedSecTimelineCount": sum(
                        record["secTimelineState"] == "HASH_VERIFIED"
                        for record in security_records
                    ),
                    "missingSecTimelineCount": sum(
                        record["secTimelineState"] == "MISSING"
                        for record in security_records
                    ),
                    "dimensionStateCounts": {
                        dimension: _terminal_dimension_counts(
                            security_records,
                            dimension,
                        )
                        for dimension in DIMENSION_FACTORS
                    },
                    "factorStateCounts": {
                        dimension: _factor_state_counts(
                            security_records,
                            dimension,
                        )
                        for dimension in DIMENSION_FACTORS
                    },
                    "reasonCounts": dict(sorted(reason_counter.items())),
                    "modelDecisionCount": 0,
                    "aggregateRankCount": 0,
                },
            }
        )

    controlled_body: dict[str, Any] = {
        "schemaVersion": LONG_HORIZON_TIER2_VERSION,
        "modelVersion": MODEL_VERSION,
        "generatedAt": generated_at.astimezone(UTC).isoformat(),
        "evaluationRole": "DEVELOPMENT_OBSERVED",
        "evidenceTier": "TIER_2_HISTORICAL_PIT_INPUT_RECONSTRUCTION",
        "providerNetworkRequests": 0,
        "candidateCount": len(candidates),
        "anchorCount": len(anchors),
        "modelExecuted": False,
        "scoresOrRanksComputed": False,
        "currentFundamentalsProjectedBackwards": False,
        "dimensionValuePolicy": (
            "Evidence IDs and period alignment only; no new factor formula "
            "or model score is inferred."
        ),
        "anchors": controlled_anchors,
        "sourceEvidence": {
            "universe": {
                "path": UNIVERSE_PATH.as_posix(),
                "fileSha256": file_sha256(universe_path),
                "version": universe["universeVersion"],
            },
            "modelFreeze": {
                "path": MODEL_FREEZE_PATH.as_posix(),
                "fileSha256": file_sha256(freeze_path),
                "artifactContentHash": freeze["artifactContentHash"],
                "freezeHash": freeze["freezeHash"],
            },
            "historicalPrices": {
                "path": PRICE_MANIFEST_PATH.as_posix(),
                "fileSha256": file_sha256(price_manifest_path),
                "artifactContentHash": price_manifest_hash,
            },
            "secV4Timeline": {
                "path": SEC_V4_MANIFEST_PATH.as_posix(),
                "fileSha256": file_sha256(sec_manifest_path),
                "artifactContentHash": sec_manifest_hash,
                "hashVerifiedCandidatePayloadCount": len(payloads),
                "missingCandidatePayloadCount": (
                    len(candidates) - len(payloads)
                ),
            },
        },
        "claimBoundary": {
            "terminalConclusion": (
                "PARTIAL_TIER2_EVIDENCE_MODEL_VALIDATION_NOT_YET_AVAILABLE"
            ),
            "validatedClaimAllowed": False,
            "statement": (
                "The reconstruction proves which existing SEC primitives "
                "were available at four historical anchors. It does not "
                "construct complete Long Horizon v1.1 dimensions, rank "
                "securities, or validate future decision quality."
            ),
        },
    }
    controlled = {
        **controlled_body,
        "contentHash": canonical_hash(controlled_body),
    }

    git_anchors = [
        {
            "label": anchor["label"],
            "sessionsBeforeLatestCompleteSession": anchor[
                "sessionsBeforeLatestCompleteSession"
            ],
            "anchorTradingDate": anchor["anchorTradingDate"],
            "cutoff": anchor["cutoff"],
            "cutoffPolicy": anchor["cutoffPolicy"],
            "aggregate": anchor["aggregate"],
        }
        for anchor in controlled_anchors
    ]
    git_body: dict[str, Any] = {
        "artifactType": "LONG_HORIZON_V11_TIER2_PIT_RECONSTRUCTION",
        "schemaVersion": LONG_HORIZON_TIER2_VERSION,
        "modelVersion": MODEL_VERSION,
        "generatedAt": generated_at.astimezone(UTC).isoformat(),
        "status": "COMPLETE_PARTIAL_EVIDENCE_ONLY",
        "evaluationRole": "DEVELOPMENT_OBSERVED",
        "evidenceTier": "TIER_2_HISTORICAL_PIT_INPUT_RECONSTRUCTION",
        "providerNetworkRequests": 0,
        "candidateCount": len(candidates),
        "anchorCount": len(anchors),
        "modelExecuted": False,
        "scoresOrRanksComputed": False,
        "currentFundamentalsProjectedBackwards": False,
        "anchors": git_anchors,
        "sourceEvidence": controlled_body["sourceEvidence"],
        "controlledPayloadReference": None,
        "controlledPayloadContentHash": controlled["contentHash"],
        "rawProviderValuesIncluded": False,
        "perSecurityEvidenceIncluded": False,
        "claimBoundary": controlled_body["claimBoundary"],
    }
    git_artifact = {
        **git_body,
        "artifactContentHash": canonical_hash(git_body),
    }
    return controlled, git_artifact


def write_long_horizon_tier2_artifacts(
    *,
    repository_root: Path,
    controlled: dict[str, Any],
    git_artifact: dict[str, Any],
    git_path: Path,
) -> tuple[str, str]:
    controlled_claim = controlled.get("contentHash")
    controlled_body = dict(controlled)
    controlled_body.pop("contentHash", None)
    if canonical_hash(controlled_body) != controlled_claim:
        raise LongHorizonTier2Error("Controlled payload hash mismatch")
    relative_controlled = (
        CONTROLLED_STORAGE_ROOT
        / f"{str(controlled_claim).lower()}.json"
    )
    controlled_path = repository_root / relative_controlled
    controlled_encoded = (
        json.dumps(
            controlled,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    controlled_path.parent.mkdir(parents=True, exist_ok=True)
    if controlled_path.exists():
        if controlled_path.read_bytes() != controlled_encoded:
            raise LongHorizonTier2Error(
                "Immutable controlled payload conflict"
            )
    else:
        with controlled_path.open("xb") as handle:
            handle.write(controlled_encoded)

    candidate = dict(git_artifact)
    candidate["controlledPayloadReference"] = (
        relative_controlled.as_posix()
    )
    candidate.pop("artifactContentHash", None)
    candidate["artifactContentHash"] = canonical_hash(candidate)
    git_encoded = (
        json.dumps(
            candidate,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    output_path = repository_root / git_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if output_path.read_bytes() != git_encoded:
            raise LongHorizonTier2Error("Immutable Git artifact conflict")
    else:
        with output_path.open("xb") as handle:
            handle.write(git_encoded)
    return (
        "sha256:" + hashlib.sha256(controlled_encoded).hexdigest(),
        "sha256:" + hashlib.sha256(git_encoded).hexdigest(),
    )
