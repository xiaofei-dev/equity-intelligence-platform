"""Append-only V27 persistence for public-safe Quant v1.1 research decisions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .evidence_assembly_v11 import ASSEMBLY_VERSION
from .research_decision_v11 import (
    RESEARCH_DECISION_CONTRACT_VERSION,
    RESEARCH_DECISION_PROJECTION_VERSION,
    QuantResearchDecisionV11,
    research_decision_id_v11,
)
from .successor_v11 import (
    ENTRY_EXIT_POLICY_VERSION,
    FORMULA_VERSION,
    MODEL_EVIDENCE_LABEL,
    MODEL_VERSION,
    STRATEGY_VERSION,
)

_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?\Z")


class QuantResearchPersistenceViolation(ValueError):
    pass


class QuantResearchPersistenceConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class PersistedQuantResearchDecisionV11:
    decision_id: str
    content_hash: str
    payload_sha256: str
    payload: dict[str, Any]
    recorded_at: datetime | None = field(compare=False)

    def __post_init__(self) -> None:
        validated = validate_quant_research_wire_v11(self.payload)
        if validated["decisionId"] != self.decision_id:
            raise QuantResearchPersistenceViolation("PERSISTED_DECISION_ID_DRIFT")
        if validated["contentHash"] != self.content_hash:
            raise QuantResearchPersistenceViolation("PERSISTED_CONTENT_HASH_DRIFT")
        _hash(self.payload_sha256, "PERSISTED_PAYLOAD_HASH_INVALID")
        if self.payload_sha256 != _sha256(_canonical_text(validated).encode("utf-8")):
            raise QuantResearchPersistenceViolation("PERSISTED_PAYLOAD_HASH_DRIFT")
        if self.recorded_at is not None:
            _whole_second(self.recorded_at, "PERSISTED_RECORDED_AT_INVALID")


class QuantResearchDecisionRepositoryV11:
    def __init__(
        self,
        database_url: str,
        *,
        connect: Any = psycopg.connect,
    ) -> None:
        if type(database_url) is not str or not database_url.startswith(
            ("postgresql://", "postgres://")
        ):
            raise QuantResearchPersistenceViolation("QUANT_DATABASE_URL_INVALID")
        self._database_url = database_url
        self._connect = connect

    def persist(
        self, decision: QuantResearchDecisionV11
    ) -> PersistedQuantResearchDecisionV11:
        if type(decision) is not QuantResearchDecisionV11:
            raise QuantResearchPersistenceViolation("QUANT_DECISION_TYPE_INVALID")
        payload = validate_quant_research_wire_v11(decision.to_wire())
        body = decision.content_payload()
        canonical_body_text = _canonical_text(body)
        canonical_payload_text = _canonical_text(payload)
        payload_sha256 = _sha256(canonical_payload_text.encode("utf-8"))
        authority = payload["authority"]
        try:
            with self._connect(self._database_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL ROLE analytics_quant_research_writer_v1")
                        cursor.execute(
                            _INSERT_DECISION,
                            {
                                "decision_id": UUID(decision.decision_id),
                                "contract_version": RESEARCH_DECISION_CONTRACT_VERSION,
                                "projection_version": (
                                    RESEARCH_DECISION_PROJECTION_VERSION
                                ),
                                "assembly_version": ASSEMBLY_VERSION,
                                "model_version": MODEL_VERSION,
                                "strategy_version": STRATEGY_VERSION,
                                "formula_version": FORMULA_VERSION,
                                "entry_exit_policy_version": (
                                    ENTRY_EXIT_POLICY_VERSION
                                ),
                                "model_evidence_label": MODEL_EVIDENCE_LABEL,
                                "decision_date": decision.decision_date,
                                "rebalance_ordinal": decision.rebalance_ordinal,
                                "expected_security_count": (
                                    decision.expected_security_count
                                ),
                                "assembly_manifest_hash": (
                                    decision.assembly_manifest_hash
                                ),
                                "decision_content_hash": decision.content_hash,
                                "canonical_body_text": canonical_body_text,
                                "payload_sha256": payload_sha256,
                                "canonical_payload_text": canonical_payload_text,
                                "canonical_payload": json.dumps(
                                    payload, separators=(",", ":"), ensure_ascii=True
                                ),
                                "deterministic_research_signal_authorized": (
                                    authority["deterministicResearchSignal"]
                                ),
                                "deterministic_final_weight_authorized": (
                                    authority["deterministicFinalPortfolioWeight"]
                                ),
                                "automatic_brokerage_execution_authorized": (
                                    authority["automaticBrokerageExecution"]
                                ),
                                "llm_signal_or_weight_authority": (
                                    authority["llmSignalOrWeightAuthority"]
                                ),
                                "future_return_guaranteed": (
                                    authority["futureReturnGuaranteed"]
                                ),
                            },
                        )
        except psycopg.errors.UniqueViolation as error:
            try:
                persisted = self.load(decision.decision_id)
            except (LookupError, ValueError, RuntimeError, psycopg.Error) as replay_error:
                raise QuantResearchPersistenceConflict(
                    "QUANT_DECISION_CONFLICT_NOT_EXACT_REPLAY"
                ) from replay_error
            expected = PersistedQuantResearchDecisionV11(
                decision_id=decision.decision_id,
                content_hash=decision.content_hash,
                payload_sha256=payload_sha256,
                payload=payload,
                recorded_at=persisted.recorded_at,
            )
            if persisted != expected:
                raise QuantResearchPersistenceConflict(
                    "QUANT_DECISION_CONFLICT_NOT_EXACT_REPLAY"
                ) from error
            return persisted
        return self.load(decision.decision_id)

    def load(self, decision_id: str) -> PersistedQuantResearchDecisionV11:
        _canonical_uuid(decision_id, "QUANT_DECISION_LOOKUP_ID_INVALID")
        with self._connect(self._database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(_LOAD_DECISION, {"decision_id": UUID(decision_id)})
                row = cursor.fetchone()
        if row is None:
            raise LookupError(f"Quant research decision {decision_id} was not found")
        payload = row["canonical_payload"]
        if type(payload) is str:
            payload = json.loads(payload)
        if _canonical_text(payload) != row["canonical_payload_text"]:
            raise QuantResearchPersistenceConflict("QUANT_CANONICAL_PAYLOAD_TEXT_DRIFT")
        body = dict(payload)
        body.pop("decisionId")
        body.pop("contentHash")
        if _canonical_text(body) != row["canonical_body_text"]:
            raise QuantResearchPersistenceConflict("QUANT_CANONICAL_BODY_TEXT_DRIFT")
        if _sha256(row["canonical_body_text"].encode("utf-8")) != row[
            "decision_content_hash"
        ]:
            raise QuantResearchPersistenceConflict("QUANT_CONTENT_HASH_DRIFT")
        return PersistedQuantResearchDecisionV11(
            decision_id=str(row["decision_id"]),
            content_hash=row["decision_content_hash"],
            payload_sha256=row["payload_sha256"],
            payload=payload,
            recorded_at=row["recorded_at"],
        )


def validate_quant_research_wire_v11(payload: Any) -> dict[str, Any]:
    if type(payload) is not dict:
        raise QuantResearchPersistenceViolation("QUANT_PROJECTION_MUST_BE_OBJECT")
    expected_root = {
        "decisionId",
        "contractVersion",
        "projectionVersion",
        "assemblyVersion",
        "modelVersion",
        "strategyVersion",
        "formulaVersion",
        "entryExitPolicyVersion",
        "modelEvidenceLabel",
        "decisionDate",
        "rebalanceOrdinal",
        "expectedSecurityCount",
        "assemblyManifestHash",
        "signals",
        "authority",
        "contentHash",
    }
    _exact_keys(payload, expected_root, "QUANT_PROJECTION_FIELDS_INVALID")
    _canonical_uuid(payload["decisionId"], "QUANT_DECISION_ID_INVALID")
    exact_values = {
        "contractVersion": RESEARCH_DECISION_CONTRACT_VERSION,
        "projectionVersion": RESEARCH_DECISION_PROJECTION_VERSION,
        "assemblyVersion": ASSEMBLY_VERSION,
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "formulaVersion": FORMULA_VERSION,
        "entryExitPolicyVersion": ENTRY_EXIT_POLICY_VERSION,
        "modelEvidenceLabel": MODEL_EVIDENCE_LABEL,
    }
    if any(payload[name] != value for name, value in exact_values.items()):
        raise QuantResearchPersistenceViolation("QUANT_PROJECTION_VERSION_DRIFT")
    try:
        datetime.strptime(payload["decisionDate"], "%Y-%m-%d")
    except (TypeError, ValueError) as error:
        raise QuantResearchPersistenceViolation("QUANT_DECISION_DATE_INVALID") from error
    if (
        type(payload["rebalanceOrdinal"]) is not int
        or payload["rebalanceOrdinal"] < 0
        or payload["rebalanceOrdinal"] % 5 != 0
        or type(payload["expectedSecurityCount"]) is not int
        or payload["expectedSecurityCount"] < 20
    ):
        raise QuantResearchPersistenceViolation("QUANT_DENOMINATOR_OR_SCHEDULE_INVALID")
    _hash(payload["assemblyManifestHash"], "QUANT_ASSEMBLY_HASH_INVALID")
    _hash(payload["contentHash"], "QUANT_CONTENT_HASH_INVALID")
    authority = payload["authority"]
    if authority != {
        "deterministicResearchSignal": True,
        "deterministicFinalPortfolioWeight": False,
        "automaticBrokerageExecution": False,
        "llmSignalOrWeightAuthority": False,
        "futureReturnGuaranteed": False,
    }:
        raise QuantResearchPersistenceViolation("QUANT_AUTHORITY_INVALID")
    signals = payload["signals"]
    if type(signals) is not list or len(signals) != payload["expectedSecurityCount"]:
        raise QuantResearchPersistenceViolation("QUANT_SIGNAL_DENOMINATOR_MISMATCH")
    security_ids = tuple(_validate_signal(item) for item in signals)
    if security_ids != tuple(sorted(set(security_ids))):
        raise QuantResearchPersistenceViolation("QUANT_SIGNAL_IDS_NOT_CANONICAL")
    _reject_forbidden_keys(payload)
    body = dict(payload)
    decision_id = body.pop("decisionId")
    content_hash = body.pop("contentHash")
    if _sha256(_canonical_text(body).encode("utf-8")) != content_hash:
        raise QuantResearchPersistenceViolation("QUANT_CONTENT_HASH_DRIFT")
    if research_decision_id_v11(content_hash) != decision_id:
        raise QuantResearchPersistenceViolation("QUANT_DECISION_ID_CONTENT_DRIFT")
    return payload


def _validate_signal(value: Any) -> str:
    if type(value) is not dict:
        raise QuantResearchPersistenceViolation("QUANT_SIGNAL_MUST_BE_OBJECT")
    _exact_keys(
        value,
        {
            "securityId",
            "assemblyState",
            "applicability",
            "assemblyReasonCodes",
            "rawSignal",
            "ranking",
            "entryPlan",
            "researchClassification",
        },
        "QUANT_SIGNAL_FIELDS_INVALID",
    )
    security_id = _canonical_uuid(value["securityId"], "QUANT_SIGNAL_ID_INVALID")
    if value["assemblyState"] not in {
        "VALID",
        "MISSING",
        "STALE",
        "INVALID",
        "NOT_APPLICABLE",
        "EXCLUDED",
    }:
        raise QuantResearchPersistenceViolation("QUANT_ASSEMBLY_STATE_INVALID")
    if value["applicability"] not in {
        "APPLICABLE",
        "NOT_APPLICABLE",
        "INSUFFICIENT_EVIDENCE",
    }:
        raise QuantResearchPersistenceViolation("QUANT_APPLICABILITY_INVALID")
    _string_list(value["assemblyReasonCodes"], "QUANT_ASSEMBLY_REASONS_INVALID")
    raw = value["rawSignal"]
    ranking = value["ranking"]
    _validate_raw_signal(raw)
    _validate_ranking(ranking)
    classification = value["researchClassification"]
    if classification not in {
        "ENTRY_CANDIDATE",
        "HOLD_REVIEW",
        "EXIT_REVIEW",
        "NO_SIGNAL",
        "NOT_APPLICABLE",
        "INSUFFICIENT_EVIDENCE",
    }:
        raise QuantResearchPersistenceViolation("QUANT_CLASSIFICATION_INVALID")
    expected = _classification_for_wire(value["assemblyState"], raw["state"], ranking["state"])
    if classification != expected:
        raise QuantResearchPersistenceViolation("QUANT_CLASSIFICATION_DRIFT")
    entry_plan = value["entryPlan"]
    if ranking["state"] == "ENTRY_ELIGIBLE":
        _validate_entry_plan(entry_plan)
    elif entry_plan is not None:
        raise QuantResearchPersistenceViolation("QUANT_ENTRY_PLAN_AUTHORITY_INVALID")
    return security_id


def _validate_raw_signal(value: Any) -> None:
    if type(value) is not dict:
        raise QuantResearchPersistenceViolation("QUANT_RAW_SIGNAL_INVALID")
    _exact_keys(
        value,
        {"state", "reasonCodes", "inputHash", "contentHash", "signalClose", "features"},
        "QUANT_RAW_SIGNAL_FIELDS_INVALID",
    )
    if value["state"] not in {"ELIGIBLE", "INELIGIBLE", "MISSING", "INVALID"}:
        raise QuantResearchPersistenceViolation("QUANT_RAW_SIGNAL_STATE_INVALID")
    _string_list(value["reasonCodes"], "QUANT_RAW_SIGNAL_REASONS_INVALID")
    _hash(value["inputHash"], "QUANT_RAW_INPUT_HASH_INVALID")
    _hash(value["contentHash"], "QUANT_RAW_CONTENT_HASH_INVALID")
    if value["state"] == "ELIGIBLE":
        _decimal(value["signalClose"], "QUANT_SIGNAL_CLOSE_INVALID")
        features = value["features"]
        if type(features) is not dict or set(features) != {
            "atr14",
            "sma100",
            "sma200",
            "marketSma200",
            "momentum252Skip20",
            "momentum126Skip20",
            "marketMomentum252Skip20",
            "marketMomentum126Skip20",
            "relative252Skip20",
            "relative126Skip20",
            "medianAdtv20",
            "atrPercent",
        }:
            raise QuantResearchPersistenceViolation("QUANT_FEATURES_INVALID")
        for numeric in features.values():
            _decimal(numeric, "QUANT_FEATURE_DECIMAL_INVALID")
    elif value["signalClose"] is not None or value["features"] is not None:
        raise QuantResearchPersistenceViolation("QUANT_NONELIGIBLE_SIGNAL_VALUES_INVALID")


def _validate_ranking(value: Any) -> None:
    if type(value) is not dict:
        raise QuantResearchPersistenceViolation("QUANT_RANKING_INVALID")
    _exact_keys(
        value,
        {
            "state",
            "rank",
            "crossSectionCount",
            "momentum252Percentile",
            "momentum126Percentile",
            "compositeScore",
            "crossSectionHash",
            "contentHash",
        },
        "QUANT_RANKING_FIELDS_INVALID",
    )
    if value["state"] not in {
        "ENTRY_ELIGIBLE",
        "HOLD_ELIGIBLE",
        "EXIT_ELIGIBLE",
        "NOT_RANKED",
    }:
        raise QuantResearchPersistenceViolation("QUANT_RANKING_STATE_INVALID")
    if type(value["crossSectionCount"]) is not int or value["crossSectionCount"] < 0:
        raise QuantResearchPersistenceViolation("QUANT_CROSS_SECTION_COUNT_INVALID")
    _hash(value["crossSectionHash"], "QUANT_CROSS_SECTION_HASH_INVALID")
    _hash(value["contentHash"], "QUANT_RANKED_CONTENT_HASH_INVALID")
    numeric_fields = (
        "momentum252Percentile",
        "momentum126Percentile",
        "compositeScore",
    )
    if value["state"] == "NOT_RANKED":
        if value["rank"] is not None or any(value[name] is not None for name in numeric_fields):
            raise QuantResearchPersistenceViolation("QUANT_NOT_RANKED_VALUES_INVALID")
    else:
        if (
            type(value["rank"]) is not int
            or not 1 <= value["rank"] <= value["crossSectionCount"]
        ):
            raise QuantResearchPersistenceViolation("QUANT_RANK_INVALID")
        for name in numeric_fields:
            numeric = _decimal(value[name], "QUANT_RANK_DECIMAL_INVALID")
            if not Decimal("0") <= numeric <= Decimal("100"):
                raise QuantResearchPersistenceViolation("QUANT_RANK_DECIMAL_DOMAIN_INVALID")


def _validate_entry_plan(value: Any) -> None:
    if type(value) is not dict or set(value) != {
        "signalClose",
        "initialStop",
        "maximumEntryPrice",
        "atr14",
        "maximumHoldingSessions",
    }:
        raise QuantResearchPersistenceViolation("QUANT_ENTRY_PLAN_INVALID")
    close = _decimal(value["signalClose"], "QUANT_ENTRY_CLOSE_INVALID")
    stop = _decimal(value["initialStop"], "QUANT_ENTRY_STOP_INVALID")
    maximum = _decimal(value["maximumEntryPrice"], "QUANT_ENTRY_MAXIMUM_INVALID")
    atr = _decimal(value["atr14"], "QUANT_ENTRY_ATR_INVALID")
    if not Decimal("0") < stop < close < maximum or atr <= 0:
        raise QuantResearchPersistenceViolation("QUANT_ENTRY_PLAN_GEOMETRY_INVALID")
    if value["maximumHoldingSessions"] != 126:
        raise QuantResearchPersistenceViolation("QUANT_ENTRY_HOLDING_POLICY_DRIFT")


def _classification_for_wire(assembly: str, raw: str, ranking: str) -> str:
    if assembly == "NOT_APPLICABLE":
        return "NOT_APPLICABLE"
    if assembly != "VALID" or raw in {"MISSING", "INVALID"}:
        return "INSUFFICIENT_EVIDENCE"
    if raw == "INELIGIBLE":
        return "NO_SIGNAL"
    return {
        "ENTRY_ELIGIBLE": "ENTRY_CANDIDATE",
        "HOLD_ELIGIBLE": "HOLD_REVIEW",
        "EXIT_ELIGIBLE": "EXIT_REVIEW",
        "NOT_RANKED": "NO_SIGNAL",
    }[ranking]


def _reject_forbidden_keys(value: Any) -> None:
    forbidden = {"finalWeight", "orderQuantity", "brokerageInstruction"}
    if type(value) is dict:
        if forbidden.intersection(value):
            raise QuantResearchPersistenceViolation("QUANT_FORBIDDEN_AUTHORITY_FIELD")
        for child in value.values():
            _reject_forbidden_keys(child)
    elif type(value) is list:
        for child in value:
            _reject_forbidden_keys(child)


def _decimal(value: Any, reason: str) -> Decimal:
    if type(value) is not str or _DECIMAL_PATTERN.fullmatch(value) is None:
        raise QuantResearchPersistenceViolation(reason)
    try:
        numeric = Decimal(value)
    except InvalidOperation as error:
        raise QuantResearchPersistenceViolation(reason) from error
    if not numeric.is_finite() or (numeric.is_zero() and value != "0"):
        raise QuantResearchPersistenceViolation(reason)
    canonical = format(numeric, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical == "-0":
        canonical = "0"
    if value != canonical:
        raise QuantResearchPersistenceViolation(reason)
    return numeric


def _string_list(value: Any, reason: str) -> None:
    if type(value) is not list or any(type(item) is not str or not item.strip() for item in value):
        raise QuantResearchPersistenceViolation(reason)


def _exact_keys(value: dict[str, Any], expected: set[str], reason: str) -> None:
    if set(value) != expected:
        raise QuantResearchPersistenceViolation(reason)


def _canonical_uuid(value: Any, reason: str) -> str:
    if type(value) is not str or _UUID_PATTERN.fullmatch(value) is None:
        raise QuantResearchPersistenceViolation(reason)
    try:
        canonical = str(UUID(value))
    except ValueError as error:
        raise QuantResearchPersistenceViolation(reason) from error
    if value != canonical:
        raise QuantResearchPersistenceViolation(reason)
    return value


def _hash(value: Any, reason: str) -> str:
    if type(value) is not str or _HASH_PATTERN.fullmatch(value) is None:
        raise QuantResearchPersistenceViolation(reason)
    return value


def _whole_second(value: Any, reason: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise QuantResearchPersistenceViolation(reason)
    normalized = value.astimezone(UTC)
    if normalized.microsecond != 0:
        raise QuantResearchPersistenceViolation(reason)
    return normalized


def _canonical_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


_INSERT_DECISION = """
INSERT INTO analytics.quant_research_decision_v1 (
    decision_id, contract_version, projection_version, assembly_version,
    model_version, strategy_version, formula_version,
    entry_exit_policy_version, model_evidence_label, decision_date,
    rebalance_ordinal, expected_security_count, assembly_manifest_hash,
    decision_content_hash, canonical_body_text, payload_sha256,
    canonical_payload_text, canonical_payload,
    deterministic_research_signal_authorized,
    deterministic_final_weight_authorized,
    automatic_brokerage_execution_authorized,
    llm_signal_or_weight_authority, future_return_guaranteed
) VALUES (
    %(decision_id)s, %(contract_version)s, %(projection_version)s,
    %(assembly_version)s, %(model_version)s, %(strategy_version)s,
    %(formula_version)s, %(entry_exit_policy_version)s,
    %(model_evidence_label)s, %(decision_date)s, %(rebalance_ordinal)s,
    %(expected_security_count)s, %(assembly_manifest_hash)s,
    %(decision_content_hash)s, %(canonical_body_text)s,
    %(payload_sha256)s, %(canonical_payload_text)s,
    %(canonical_payload)s::jsonb,
    %(deterministic_research_signal_authorized)s,
    %(deterministic_final_weight_authorized)s,
    %(automatic_brokerage_execution_authorized)s,
    %(llm_signal_or_weight_authority)s, %(future_return_guaranteed)s
)
"""

_LOAD_DECISION = """
SELECT decision_id, decision_content_hash, canonical_body_text,
       payload_sha256, canonical_payload_text, canonical_payload, recorded_at
FROM analytics.quant_research_decision_v1
WHERE decision_id = %(decision_id)s
"""
