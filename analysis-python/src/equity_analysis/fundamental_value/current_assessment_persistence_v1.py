"""Append-only V26 persistence for current Fundamental Value assessments.

V26 stores a complete, immutable private assessment graph.  PostgreSQL owns
relational provenance, cardinality, and sealing; Python remains the only owner
of the Fundamental Value formulas and replays the typed model both before a
write and after every read.
"""

from __future__ import annotations

import hashlib
import json
import re
import types
from dataclasses import dataclass, field, fields, is_dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal, DecimalException
from enum import StrEnum
from typing import Any, get_args, get_origin, get_type_hints
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from equity_analysis.fundamental_value.current_assessment_v1 import (
    CurrentFundamentalAssessmentV1,
    current_fundamental_assessment_to_wire_v1,
    current_producer_contracts_v1,
    validate_current_fundamental_assessment_v1,
)

PERSISTENCE_VERSION = "FV-CURRENT-ASSESSMENT-PERSISTENCE-v1.0.0"
AUTHORITY_CONTRACT_VERSION = "FV-CURRENT-ASSESSMENT-AUTHORITY-v1.0.0"
AUTHORIZATION_REFERENCE = "CODEX_THREAD_USER_APPROVAL_2026-08-12_UTF8_SHA256"
AUTHORIZATION_CONTENT_HASH = (
    "sha256:8cbe697b157364a5b13646285b38409dc53ec5287deeb7913493e65b275cd14d"
)
AUTHORIZED_SYMBOLS = ("GOOG", "FOX", "MSFT")
_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)


class CurrentAssessmentPersistenceViolation(ValueError):
    """Raised when a V26 wire value cannot be verified exactly."""


class CurrentAssessmentPersistenceConflict(RuntimeError):
    """Raised when durable V26 state conflicts or is incomplete."""


@dataclass(frozen=True)
class PersistedCurrentAssessmentV1:
    assessment_id: str
    assessment_content_hash: str
    payload_sha256: str
    payload: dict[str, Any]
    recorded_at: datetime | None = field(compare=False)

    def __post_init__(self) -> None:
        _canonical_uuid(self.assessment_id, "CURRENT_ASSESSMENT_ID_INVALID")
        _canonical_hash(
            self.assessment_content_hash,
            "CURRENT_ASSESSMENT_CONTENT_HASH_INVALID",
        )
        _canonical_hash(self.payload_sha256, "CURRENT_ASSESSMENT_PAYLOAD_HASH_INVALID")
        if type(self.payload) is not dict:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_PAYLOAD_INVALID"
            )
        if self.recorded_at is not None:
            _instant_value(
                self.recorded_at, "CURRENT_ASSESSMENT_RECORDED_AT_INVALID"
            )
        canonical_text = _payload_text(self.payload)
        if _sha256(canonical_text.encode()) != self.payload_sha256:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_PAYLOAD_HASH_DRIFT"
            )
        if self.payload.get("content_hash") != self.assessment_content_hash:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_PAYLOAD_CONTENT_DRIFT"
            )
        if self.assessment_id != current_assessment_id_v1(
            self.assessment_content_hash
        ):
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_ID_CONTENT_DRIFT"
            )


def current_assessment_id_v1(content_hash: str) -> str:
    _canonical_hash(content_hash, "CURRENT_ASSESSMENT_CONTENT_HASH_INVALID")
    return str(uuid5(NAMESPACE_URL, f"{PERSISTENCE_VERSION}:{content_hash}"))


def current_assessment_authority_id_v1(
    identity_projection_content_hash: str,
) -> str:
    _canonical_hash(
        identity_projection_content_hash,
        "CURRENT_ASSESSMENT_IDENTITY_PROJECTION_HASH_INVALID",
    )
    return str(
        uuid5(
            NAMESPACE_URL,
            ":".join(
                (
                    AUTHORITY_CONTRACT_VERSION,
                    identity_projection_content_hash,
                    AUTHORIZATION_CONTENT_HASH,
                )
            ),
        )
    )


def provision_current_assessment_authority_v1(
    database_url: str,
    *,
    identity_projection_content_hash: str,
    authorization_reference: str,
    authorization_content_hash: str,
    authority_write_authorized: bool,
    connect: Any = psycopg.connect,
) -> str:
    """Explicitly provision the narrow V26 persistence/publication authority."""

    if type(database_url) is not str or not database_url.startswith(
        ("postgresql://", "postgres://")
    ):
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_ASSESSMENT_DATABASE_URL_INVALID"
        )
    _canonical_hash(
        identity_projection_content_hash,
        "CURRENT_ASSESSMENT_IDENTITY_PROJECTION_HASH_INVALID",
    )
    if (
        authorization_reference != AUTHORIZATION_REFERENCE
        or authorization_content_hash != AUTHORIZATION_CONTENT_HASH
        or authority_write_authorized is not True
    ):
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_ASSESSMENT_AUTHORITY_NOT_EXPLICITLY_AUTHORIZED"
        )
    authority_id = current_assessment_authority_id_v1(
        identity_projection_content_hash
    )
    try:
        with connect(database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SET LOCAL ROLE "
                        "analytics_fv_current_assessment_authority_writer_v1"
                    )
                    cursor.execute(
                        """
                        INSERT INTO analytics.fv_current_assessment_authority_v1 (
                          authority_id,contract_version,identity_authority_id,
                          identity_projection_content_hash,authorized_symbols,
                          evidence_track,model_evidence_label,
                          authorization_reference,authorization_content_hash,
                          assessment_persistence_authorized,
                          read_only_publication_authorized,
                          deterministic_action_authorized,
                          deterministic_ranking_authorized,
                          final_portfolio_weight_authorized,
                          automatic_brokerage_execution_authorized,
                          evidence_label_upgrade_authorized,recorded_at
                        )
                        SELECT %s,%s,a.authority_id,a.projection_content_hash,
                          %s::jsonb,
                          'EODHD_PROVIDER_NORMALIZED_CURRENT_REVISION_APPROXIMATION',
                          'NOT_VALIDATED',%s,%s,true,true,false,false,false,false,false,
                          TIMESTAMPTZ '2001-01-01 00:00:00+00'
                        FROM analytics.fv_identity_authority_v2 a
                        WHERE a.projection_content_hash=%s
                          AND a.model_evidence_label='NOT_VALIDATED'
                        ON CONFLICT (identity_authority_id) DO NOTHING
                        """,
                        (
                            authority_id,
                            AUTHORITY_CONTRACT_VERSION,
                            json.dumps(AUTHORIZED_SYMBOLS, separators=(",", ":")),
                            authorization_reference,
                            authorization_content_hash,
                            identity_projection_content_hash,
                        ),
                    )
                    cursor.execute(
                        """SELECT authority_id::text AS authority_id,
                                  contract_version,identity_projection_content_hash,
                                  authorized_symbols,evidence_track,model_evidence_label,
                                  authorization_reference,authorization_content_hash,
                                  assessment_persistence_authorized,
                                  read_only_publication_authorized,
                                  deterministic_action_authorized,
                                  deterministic_ranking_authorized,
                                  final_portfolio_weight_authorized,
                                  automatic_brokerage_execution_authorized,
                                  evidence_label_upgrade_authorized
                           FROM analytics.fv_current_assessment_authority_v1
                           WHERE identity_projection_content_hash=%s""",
                        (identity_projection_content_hash,),
                    )
                    row = cursor.fetchone()
                    expected = {
                        "authority_id": authority_id,
                        "contract_version": AUTHORITY_CONTRACT_VERSION,
                        "identity_projection_content_hash": identity_projection_content_hash,
                        "authorized_symbols": list(AUTHORIZED_SYMBOLS),
                        "evidence_track": (
                            "EODHD_PROVIDER_NORMALIZED_"
                            "CURRENT_REVISION_APPROXIMATION"
                        ),
                        "model_evidence_label": "NOT_VALIDATED",
                        "authorization_reference": authorization_reference,
                        "authorization_content_hash": authorization_content_hash,
                        "assessment_persistence_authorized": True,
                        "read_only_publication_authorized": True,
                        "deterministic_action_authorized": False,
                        "deterministic_ranking_authorized": False,
                        "final_portfolio_weight_authorized": False,
                        "automatic_brokerage_execution_authorized": False,
                        "evidence_label_upgrade_authorized": False,
                    }
                    if row != expected:
                        raise CurrentAssessmentPersistenceConflict(
                            "CURRENT_ASSESSMENT_AUTHORITY_CONFLICT"
                        )
                    return authority_id
    except (
        CurrentAssessmentPersistenceConflict,
        CurrentAssessmentPersistenceViolation,
    ):
        raise
    except (psycopg.Error, KeyError, TypeError, ValueError) as error:
        raise CurrentAssessmentPersistenceConflict(
            "CURRENT_ASSESSMENT_AUTHORITY_DATABASE_CONFLICT"
        ) from error


def _canonical_uuid(value: object, code: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise CurrentAssessmentPersistenceViolation(code)
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise CurrentAssessmentPersistenceViolation(code) from error
    if str(parsed) != value:
        raise CurrentAssessmentPersistenceViolation(code)
    return value


def _canonical_hash(value: object, code: str) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise CurrentAssessmentPersistenceViolation(code)
    return value


def _payload_text(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_ASSESSMENT_PAYLOAD_NOT_CANONICAL"
        ) from error


def _body_text(payload: dict[str, Any]) -> str:
    if type(payload) is not dict or "content_hash" not in payload:
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_ASSESSMENT_BODY_INVALID"
        )
    body = dict(payload)
    body.pop("content_hash")
    return _payload_text(body)


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _plain(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_ASSESSMENT_NUMERIC_WIRE_INVALID"
        )
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _decimal_wire(value: str, code: str) -> Decimal:
    if type(value) is not str:
        raise CurrentAssessmentPersistenceViolation(code)
    try:
        result = Decimal(value)
    except (DecimalException, ValueError) as error:
        raise CurrentAssessmentPersistenceViolation(code) from error
    if not result.is_finite():
        raise CurrentAssessmentPersistenceViolation(code)
    canonical = "0" if result.is_zero() else format(result, "f")
    if canonical != value:
        raise CurrentAssessmentPersistenceViolation(code)
    return result


def _decimal(payload: dict[str, Any], *path: str) -> Decimal:
    value: object = payload
    for item in path:
        if type(value) is not dict or item not in value:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_NUMERIC_PATH_MISSING"
            )
        value = value[item]
    if type(value) is not str:
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_ASSESSMENT_NUMERIC_WIRE_INVALID"
        )
    try:
        result = Decimal(value)
    except (DecimalException, ValueError) as error:
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_ASSESSMENT_NUMERIC_WIRE_INVALID"
        ) from error
    # The current-assessment wire intentionally preserves Decimal scale
    # because the Stage 2 input hash binds the Decimal exponent.  V26 stores
    # these values in unconstrained NUMERIC and restores that scale before
    # replay, so an ordinary finite string such as ``2.00`` is valid here.
    if not result.is_finite() or format(result, "f") != value:
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_ASSESSMENT_NUMERIC_WIRE_INVALID"
        )
    return result


def _instant(value: object, code: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise CurrentAssessmentPersistenceViolation(code)
    try:
        result = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise CurrentAssessmentPersistenceViolation(code) from error
    return _instant_value(result, code)


def _instant_value(value: object, code: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise CurrentAssessmentPersistenceViolation(code)
    normalized = value.astimezone(UTC)
    if normalized.microsecond:
        raise CurrentAssessmentPersistenceViolation(code)
    return normalized


def _date(value: object, code: str) -> date:
    if type(value) is not str:
        raise CurrentAssessmentPersistenceViolation(code)
    try:
        result = date.fromisoformat(value)
    except ValueError as error:
        raise CurrentAssessmentPersistenceViolation(code) from error
    if result.isoformat() != value:
        raise CurrentAssessmentPersistenceViolation(code)
    return result


def _decode_typed(value: object, annotation: object, path: str) -> object:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (types.UnionType, getattr(types, "UnionType", object)) or (
        origin is not None and type(None) in args
    ):
        if value is None and type(None) in args:
            return None
        candidates = tuple(item for item in args if item is not type(None))
        if len(candidates) != 1:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_TYPED_WIRE_UNSUPPORTED"
            )
        return _decode_typed(value, candidates[0], path)
    if origin is tuple:
        if type(value) is not list or len(args) != 2 or args[1] is not Ellipsis:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_TYPED_COLLECTION_INVALID"
            )
        return tuple(_decode_typed(item, args[0], f"{path}[]") for item in value)
    if annotation is Decimal:
        return _decimal_wire(value, "CURRENT_ASSESSMENT_TYPED_DECIMAL_INVALID")
    if annotation is datetime:
        return _instant(value, "CURRENT_ASSESSMENT_TYPED_INSTANT_INVALID")
    if annotation is date:
        return _date(value, "CURRENT_ASSESSMENT_TYPED_DATE_INVALID")
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        if type(value) is not str:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_TYPED_ENUM_INVALID"
            )
        try:
            return annotation(value)
        except ValueError as error:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_TYPED_ENUM_INVALID"
            ) from error
    if isinstance(annotation, type) and is_dataclass(annotation):
        if type(value) is not dict:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_TYPED_OBJECT_INVALID"
            )
        hints = get_type_hints(annotation)
        expected = {item.name for item in fields(annotation)}
        if set(value) != expected:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_TYPED_OBJECT_KEYS_INVALID"
            )
        return annotation(
            **{
                item.name: _decode_typed(
                    value[item.name], hints[item.name], f"{path}.{item.name}"
                )
                for item in fields(annotation)
            }
        )
    if annotation is str:
        if type(value) is not str:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_TYPED_STRING_INVALID"
            )
        return value
    if annotation is bool:
        if type(value) is not bool:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_TYPED_BOOLEAN_INVALID"
            )
        return value
    if annotation is int:
        if type(value) is not int:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_TYPED_INTEGER_INVALID"
            )
        return value
    raise CurrentAssessmentPersistenceViolation(
        f"CURRENT_ASSESSMENT_TYPED_WIRE_UNSUPPORTED:{path}"
    )


def _assessment_from_payload(
    payload: dict[str, Any],
    *,
    durable_operand_values: dict[str, Decimal | None] | None = None,
) -> CurrentFundamentalAssessmentV1:
    result = _decode_typed(payload, CurrentFundamentalAssessmentV1, "assessment")
    if type(result) is not CurrentFundamentalAssessmentV1:
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_ASSESSMENT_TYPED_WIRE_INVALID"
        )
    if durable_operand_values is not None:
        if set(durable_operand_values) != {
            item.operand_code for item in result.input_evidence
        }:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_DURABLE_OPERAND_SET_DRIFT"
            )
        input_changes = {
            code: replace(
                getattr(result.inputs, code), value=durable_operand_values[code]
            )
            for code in durable_operand_values
        }
        result = replace(
            result,
            inputs=replace(result.inputs, **input_changes),
            input_evidence=tuple(
                replace(item, value=durable_operand_values[item.operand_code])
                for item in result.input_evidence
            ),
        )
    validate_current_fundamental_assessment_v1(result)
    if current_fundamental_assessment_to_wire_v1(result) != payload:
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_ASSESSMENT_TYPED_ROUND_TRIP_DRIFT"
        )
    return result


def _expected_record(payload: dict[str, Any]) -> PersistedCurrentAssessmentV1:
    text = _payload_text(payload)
    body_text = _body_text(payload)
    content_hash = payload.get("content_hash")
    _canonical_hash(content_hash, "CURRENT_ASSESSMENT_CONTENT_HASH_INVALID")
    if _sha256(body_text.encode()) != content_hash:
        raise CurrentAssessmentPersistenceViolation(
            "CURRENT_ASSESSMENT_BODY_HASH_DRIFT"
        )
    return PersistedCurrentAssessmentV1(
        assessment_id=current_assessment_id_v1(content_hash),
        assessment_content_hash=content_hash,
        payload_sha256=_sha256(text.encode()),
        payload=payload,
        recorded_at=None,
    )


class CurrentAssessmentRepositoryV1:
    """Typed V26 repository with exact replay and fail-closed readback."""

    def __init__(self, database_url: str, *, connect: Any = psycopg.connect) -> None:
        if type(database_url) is not str or not database_url.startswith(
            ("postgresql://", "postgres://")
        ):
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_DATABASE_URL_INVALID"
            )
        self._database_url = database_url
        self._connect = connect

    def persist(
        self, value: CurrentFundamentalAssessmentV1
    ) -> PersistedCurrentAssessmentV1:
        validate_current_fundamental_assessment_v1(value)
        payload = current_fundamental_assessment_to_wire_v1(value)
        expected = _expected_record(payload)
        try:
            with self._connect(self._database_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SET LOCAL ROLE analytics_fv_current_assessment_writer_v1"
                        )
                        cursor.execute(
                            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                            (value.content_hash,),
                        )
                        self._verify_producer_registry(cursor)
                        existing = self._load_by_hash(cursor, value.content_hash)
                        if existing is not None:
                            if existing != expected:
                                raise CurrentAssessmentPersistenceConflict(
                                    "CURRENT_ASSESSMENT_IMMUTABLE_REPLAY_CONFLICT"
                                )
                            return existing
                        self._insert(
                            cursor,
                            payload,
                            expected,
                            durable_operand_values={
                                item.operand_code: item.value
                                for item in value.input_evidence
                            },
                        )
                        result = self._load_by_id(cursor, expected.assessment_id)
                        if result is None or result != expected:
                            raise CurrentAssessmentPersistenceConflict(
                                "CURRENT_ASSESSMENT_READBACK_DRIFT"
                            )
                        return result
        except (
            CurrentAssessmentPersistenceConflict,
            CurrentAssessmentPersistenceViolation,
        ):
            raise
        except (psycopg.Error, KeyError, TypeError, ValueError) as error:
            raise CurrentAssessmentPersistenceConflict(
                "CURRENT_ASSESSMENT_DATABASE_INTEGRITY_CONFLICT"
            ) from error

    def load(self, assessment_id: str) -> PersistedCurrentAssessmentV1:
        _canonical_uuid(assessment_id, "CURRENT_ASSESSMENT_ID_INVALID")
        try:
            with self._connect(self._database_url, row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    self._verify_producer_registry(cursor)
                    result = self._load_by_id(cursor, assessment_id)
                    if result is None:
                        raise LookupError(assessment_id)
                    return result
        except (LookupError, CurrentAssessmentPersistenceViolation):
            raise
        except CurrentAssessmentPersistenceConflict:
            raise
        except (psycopg.Error, KeyError, TypeError, ValueError) as error:
            raise CurrentAssessmentPersistenceConflict(
                "CURRENT_ASSESSMENT_DATABASE_INTEGRITY_CONFLICT"
            ) from error

    def load_latest_for_security(self, security_id: str) -> PersistedCurrentAssessmentV1:
        _canonical_uuid(security_id, "CURRENT_ASSESSMENT_SECURITY_ID_INVALID")
        return self._load_latest("security_id", security_id)

    def load_latest_for_symbol(self, symbol: str) -> PersistedCurrentAssessmentV1:
        if type(symbol) is not str or re.fullmatch(
            r"[A-Z][A-Z0-9.-]{0,31}", symbol
        ) is None:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_SYMBOL_INVALID"
            )
        return self._load_latest("symbol", symbol)

    def _load_latest(self, field_name: str, value: str) -> PersistedCurrentAssessmentV1:
        try:
            with self._connect(self._database_url, row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    self._verify_producer_registry(cursor)
                    cursor.execute(
                        f"""SELECT assessment_id::text AS assessment_id,
                                   security_id::text AS security_id,symbol,
                                   decision_cutoff,recorded_at
                            FROM analytics.fv_current_assessment_v1
                            WHERE {field_name}=%s
                            ORDER BY decision_cutoff DESC,recorded_at DESC,assessment_id
                            LIMIT 2""",
                        (value,),
                    )
                    rows = cursor.fetchall()
                    if not rows:
                        raise LookupError(value)
                    row = rows[0]
                    if (
                        len(rows) > 1
                        and rows[1]["decision_cutoff"] == row["decision_cutoff"]
                    ):
                        raise CurrentAssessmentPersistenceConflict(
                            "CURRENT_ASSESSMENT_LATEST_DECISION_TIE"
                        )
                    result = self._load_by_id(cursor, row["assessment_id"])
                    if result is None:
                        raise CurrentAssessmentPersistenceConflict(
                            "CURRENT_ASSESSMENT_LATEST_READBACK_MISSING"
                        )
                    payload = result.payload
                    if (
                        payload.get(field_name) != value
                        or payload.get("security_id") != row["security_id"]
                        or payload.get("symbol") != row["symbol"]
                        or _instant(
                            payload.get("decision_cutoff"),
                            "CURRENT_ASSESSMENT_DECISION_CUTOFF_INVALID",
                        )
                        != row["decision_cutoff"]
                        or result.recorded_at != row["recorded_at"]
                    ):
                        raise CurrentAssessmentPersistenceConflict(
                            "CURRENT_ASSESSMENT_LATEST_READBACK_DRIFT"
                        )
                    return result
        except (
            LookupError,
            CurrentAssessmentPersistenceConflict,
            CurrentAssessmentPersistenceViolation,
        ):
            raise
        except (psycopg.Error, KeyError, TypeError, ValueError) as error:
            raise CurrentAssessmentPersistenceConflict(
                "CURRENT_ASSESSMENT_DATABASE_INTEGRITY_CONFLICT"
            ) from error

    @staticmethod
    def _verify_producer_registry(cursor: Any) -> None:
        cursor.execute(
            """SELECT operand_ordinal,operand_code,evaluator_version,evidence_kind,
                      source_roles,governance,producer_contract_hash
               FROM analytics.fv_current_producer_contract_v1
               ORDER BY operand_ordinal"""
        )
        rows = cursor.fetchall()
        expected = current_producer_contracts_v1()
        actual = {
            row["operand_code"]: (
                row["operand_ordinal"],
                row["evaluator_version"],
                row["evidence_kind"],
                tuple(row["source_roles"]),
                row["governance"],
                row["producer_contract_hash"],
            )
            for row in rows
        }
        wanted = {
            code: (
                ordinal,
                contract.evaluator_version,
                contract.evidence_kind,
                contract.source_roles,
                contract.governance,
                contract.content_hash,
            )
            for ordinal, (code, contract) in enumerate(expected.items(), 1)
        }
        if actual != wanted:
            raise CurrentAssessmentPersistenceConflict(
                "CURRENT_ASSESSMENT_PRODUCER_REGISTRY_DRIFT"
            )

    @staticmethod
    def _insert(
        cursor: Any,
        payload: dict[str, Any],
        expected: PersistedCurrentAssessmentV1,
        *,
        durable_operand_values: dict[str, Decimal | None],
    ) -> None:
        view = payload["investment_view"]
        session = payload["completed_session"]
        applicability = payload["applicability_seal"]
        price = payload["price_selection_seal"]
        body_text = _body_text(payload)
        payload_text = _payload_text(payload)
        cursor.execute(
            """
            INSERT INTO analytics.fv_current_assessment_v1 (
                assessment_id,current_assessment_authority_id,
                contract_version,producer_version,policy_version,
                evidence_track,claim_ceiling,model_evidence_label,
                identity_authority_id,identity_authority_member_ordinal,
                security_id,company_id,instrument_id,share_class_id,listing_id,
                ticker_assignment_id,symbol,mic,currency,decision_cutoff,
                price_session_date,latest_fundamental_period_end,
                completed_session_id,completed_session_hash,
                classification_routing_id,classification_routing_hash,
                classification_request_id,classification_request_hash,
                classification_result_hash,classification_policy_hash,
                classification_evidence_id,classification_evidence_hash,
                price_request_id,price_request_hash,price_result_hash,
                price_policy_hash,price_evidence_id,price_evidence_hash,
                state,investment_category,company_quality,financial_resilience,
                earnings_cash_flow_quality,capital_allocation_quality,downside_risk,
                fair_value_low,fair_value_central,fair_value_high,
                margin_of_safety_low,margin_of_safety_central,margin_of_safety_high,
                expected_return_low,expected_return_central,expected_return_high,
                risk_cap_ceiling,source_count,operand_count,parent_count,reason_count,
                assessment_content_hash,canonical_body_text,payload_sha256,
                canonical_payload_text,canonical_payload,
                deterministic_action_authorized,deterministic_ranking_authorized,
                final_portfolio_weight_authorized,
                automatic_brokerage_execution_authorized
            )
            SELECT
                %(assessment_id)s,assessment_authority.authority_id,
                %(contract_version)s,%(producer_version)s,
                %(policy_version)s,%(evidence_track)s,%(claim_ceiling)s,
                %(model_evidence_label)s,member.authority_id,member.member_ordinal,
                %(security_id)s::uuid,%(company_id)s::uuid,%(instrument_id)s::uuid,
                %(share_class_id)s::uuid,%(listing_id)s::uuid,
                %(ticker_assignment_id)s::uuid,%(symbol)s::varchar,
                %(mic)s::varchar,%(currency)s::varchar,%(decision_cutoff)s,
                %(price_session_date)s,
                %(latest_fundamental_period_end)s,%(completed_session_id)s,
                %(completed_session_hash)s,%(classification_routing_id)s,
                %(classification_routing_hash)s,%(classification_request_id)s,
                %(classification_request_hash)s,%(classification_result_hash)s,
                %(classification_policy_hash)s,%(classification_evidence_id)s,
                %(classification_evidence_hash)s,%(price_request_id)s,
                %(price_request_hash)s,%(price_result_hash)s,%(price_policy_hash)s,
                %(price_evidence_id)s,%(price_evidence_hash)s,%(state)s,
                %(investment_category)s,%(company_quality)s,%(financial_resilience)s,
                %(earnings_cash_flow_quality)s,%(capital_allocation_quality)s,
                %(downside_risk)s,%(fair_value_low)s,%(fair_value_central)s,
                %(fair_value_high)s,%(margin_of_safety_low)s,
                %(margin_of_safety_central)s,%(margin_of_safety_high)s,
                %(expected_return_low)s,%(expected_return_central)s,
                %(expected_return_high)s,%(risk_cap_ceiling)s,2,34,32,1,
                %(assessment_content_hash)s,%(canonical_body_text)s,
                %(payload_sha256)s,%(canonical_payload_text)s,
                %(canonical_payload)s::jsonb,false,false,false,false
            FROM analytics.fv_identity_authority_member_v2 member
            JOIN analytics.fv_identity_authority_v2 identity_authority
              ON identity_authority.authority_id=member.authority_id
            JOIN analytics.fv_current_assessment_authority_v1 assessment_authority
              ON assessment_authority.identity_authority_id=identity_authority.authority_id
             AND assessment_authority.identity_projection_content_hash=
                 identity_authority.projection_content_hash
            WHERE member.security_id=%(security_id)s::uuid
              AND member.company_id=%(company_id)s::uuid
              AND member.instrument_id=%(instrument_id)s::uuid
              AND member.share_class_id=%(share_class_id)s::uuid
              AND member.listing_id=%(listing_id)s::uuid
              AND member.ticker_assignment_id=%(ticker_assignment_id)s::uuid
              AND member.ticker=%(symbol)s::varchar
              AND member.mic=%(mic)s::varchar
              AND member.currency=%(currency)s::varchar
              AND identity_authority.model_evidence_label='NOT_VALIDATED'
              AND assessment_authority.assessment_persistence_authorized
              AND assessment_authority.read_only_publication_authorized
              AND assessment_authority.authorized_symbols ? member.ticker
              AND NOT assessment_authority.deterministic_action_authorized
              AND NOT assessment_authority.deterministic_ranking_authorized
              AND NOT assessment_authority.final_portfolio_weight_authorized
              AND NOT assessment_authority.automatic_brokerage_execution_authorized
              AND NOT assessment_authority.evidence_label_upgrade_authorized
            """,
            {
                "assessment_id": expected.assessment_id,
                **{
                    key: payload[key]
                    for key in (
                        "contract_version",
                        "producer_version",
                        "policy_version",
                        "evidence_track",
                        "claim_ceiling",
                        "model_evidence_label",
                        "security_id",
                        "company_id",
                        "instrument_id",
                        "share_class_id",
                        "listing_id",
                        "ticker_assignment_id",
                        "symbol",
                        "mic",
                        "currency",
                        "price_session_date",
                        "latest_fundamental_period_end",
                    )
                },
                "decision_cutoff": _instant(
                    payload["decision_cutoff"], "CURRENT_ASSESSMENT_CUTOFF_INVALID"
                ),
                "completed_session_id": session["completed_session_id"],
                "completed_session_hash": session["session_content_hash"],
                "classification_routing_id": applicability["routing_id"],
                "classification_routing_hash": applicability["routing_content_hash"],
                "classification_request_id": applicability["classification_request_id"],
                "classification_request_hash": applicability[
                    "classification_request_content_hash"
                ],
                "classification_result_hash": applicability[
                    "classification_result_content_hash"
                ],
                "classification_policy_hash": applicability[
                    "classification_policy_content_hash"
                ],
                "classification_evidence_id": applicability[
                    "classification_evidence_id"
                ],
                "classification_evidence_hash": applicability[
                    "classification_normalized_record_hash"
                ],
                "price_request_id": price["request_id"],
                "price_request_hash": price["request_content_hash"],
                "price_result_hash": price["result_content_hash"],
                "price_policy_hash": price["policy_content_hash"],
                "price_evidence_id": price["selected_evidence_id"],
                "price_evidence_hash": price[
                    "selected_evidence_normalized_record_hash"
                ],
                "state": view["state"],
                "investment_category": view["category"],
                "company_quality": _decimal(
                    payload, "assessment", "company_quality", "score"
                ),
                "financial_resilience": _decimal(
                    payload, "assessment", "financial_resilience", "score"
                ),
                "earnings_cash_flow_quality": _decimal(
                    payload,
                    "assessment",
                    "earnings_and_cash_flow_quality",
                    "score",
                ),
                "capital_allocation_quality": _decimal(
                    payload, "assessment", "capital_allocation_quality", "score"
                ),
                "downside_risk": _decimal(
                    payload, "assessment", "downside_risk", "score"
                ),
                **{
                    f"fair_value_{part}": _decimal(
                        payload, "assessment", "fair_value", part
                    )
                    for part in ("low", "central", "high")
                },
                **{
                    f"margin_of_safety_{part}": _decimal(
                        payload, "assessment", "margin_of_safety", part
                    )
                    for part in ("low", "central", "high")
                },
                **{
                    f"expected_return_{part}": _decimal(
                        payload, "assessment", "expected_return", part
                    )
                    for part in ("low", "central", "high")
                },
                "risk_cap_ceiling": _decimal(
                    payload, "assessment", "risk_cap", "ceiling"
                ),
                "assessment_content_hash": expected.assessment_content_hash,
                "canonical_body_text": body_text,
                "payload_sha256": expected.payload_sha256,
                "canonical_payload_text": payload_text,
                "canonical_payload": payload_text,
            },
        )
        if cursor.rowcount != 1:
            raise CurrentAssessmentPersistenceConflict(
                "CURRENT_ASSESSMENT_EXPLICIT_AUTHORITY_OR_IDENTITY_MISSING"
            )
        for ordinal, source in enumerate(payload["source_seals"], 1):
            cursor.execute(
                """INSERT INTO analytics.fv_current_assessment_source_v1 (
                    assessment_id,source_ordinal,source_role,raw_manifest_id,
                    provider_code,schema_version,source_reference,file_sha256,
                    source_content_hash,normalized_record_hash,available_at,
                    retrieved_at,ingested_at,source_revision,adapter_version,
                    normalization_version,freshness_policy_version,source_record_id,
                    request_identity,plan_hash,checkpoint_reference
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s
                )""",
                (
                    expected.assessment_id,
                    ordinal,
                    "FUNDAMENTALS" if ordinal == 1 else "PRICE",
                    source["raw_manifest_id"],
                    source["provider_code"],
                    source["schema_version"],
                    source["source_reference"],
                    source["file_sha256"],
                    source["source_content_hash"],
                    source["normalized_record_hash"],
                    _instant(source["available_at"], "CURRENT_SOURCE_AVAILABLE_INVALID"),
                    None
                    if source["retrieved_at"] is None
                    else _instant(
                        source["retrieved_at"], "CURRENT_SOURCE_RETRIEVED_INVALID"
                    ),
                    _instant(source["ingested_at"], "CURRENT_SOURCE_INGESTED_INVALID"),
                    source["source_revision"],
                    source["adapter_version"],
                    source["normalization_version"],
                    source["freshness_policy_version"],
                    source["source_record_id"],
                    source["request_identity"],
                    source["plan_hash"],
                    source["checkpoint_reference"],
                ),
            )
        manifest_to_source = {
            source["raw_manifest_id"]: ordinal
            for ordinal, source in enumerate(payload["source_seals"], 1)
        }
        if set(durable_operand_values) != {
            item["operand_code"] for item in payload["input_evidence"]
        }:
            raise CurrentAssessmentPersistenceViolation(
                "CURRENT_ASSESSMENT_DURABLE_OPERAND_SET_DRIFT"
            )
        for ordinal, operand in enumerate(payload["input_evidence"], 1):
            cursor.execute(
                """INSERT INTO analytics.fv_current_assessment_operand_v1 (
                    assessment_id,operand_ordinal,operand_code,state,numeric_value,
                    evidence_kind,source_roles,producer_contract_hash,
                    output_content_hash,parent_count,reason_count
                ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)""",
                (
                    expected.assessment_id,
                    ordinal,
                    operand["operand_code"],
                    operand["state"],
                    durable_operand_values[operand["operand_code"]],
                    operand["evidence_kind"],
                    json.dumps(operand["source_roles"], separators=(",", ":")),
                    operand["producer_contract_hash"],
                    operand["output_content_hash"],
                    len(operand["source_parent_ids"]),
                    len(operand["reason_codes"]),
                ),
            )
            for parent_ordinal, parent_id in enumerate(
                operand["source_parent_ids"], 1
            ):
                cursor.execute(
                    """INSERT INTO analytics.fv_current_assessment_operand_parent_v1 (
                        assessment_id,operand_ordinal,parent_ordinal,
                        raw_manifest_id,source_ordinal
                    ) VALUES (%s,%s,%s,%s,%s)""",
                    (
                        expected.assessment_id,
                        ordinal,
                        parent_ordinal,
                        parent_id,
                        manifest_to_source[parent_id],
                    ),
                )
            for reason_ordinal, reason in enumerate(operand["reason_codes"], 1):
                cursor.execute(
                    """INSERT INTO analytics.fv_current_assessment_operand_reason_v1 (
                        assessment_id,operand_ordinal,reason_ordinal,reason_code
                    ) VALUES (%s,%s,%s,%s)""",
                    (expected.assessment_id, ordinal, reason_ordinal, reason),
                )
        cursor.execute(
            """INSERT INTO analytics.fv_current_assessment_seal_v1 (
                assessment_id,source_count,operand_count,parent_count,reason_count,
                assessment_content_hash,payload_sha256
            ) VALUES (%s,2,34,32,1,%s,%s)""",
            (
                expected.assessment_id,
                expected.assessment_content_hash,
                expected.payload_sha256,
            ),
        )

    @staticmethod
    def _load_by_hash(cursor: Any, value: str) -> PersistedCurrentAssessmentV1 | None:
        cursor.execute(
            "SELECT assessment_id::text AS assessment_id FROM "
            "analytics.fv_current_assessment_v1 WHERE assessment_content_hash=%s",
            (value,),
        )
        row = cursor.fetchone()
        return (
            None
            if row is None
            else CurrentAssessmentRepositoryV1._load_by_id(cursor, row["assessment_id"])
        )

    @staticmethod
    def _load_by_id(
        cursor: Any, assessment_id: str
    ) -> PersistedCurrentAssessmentV1 | None:
        cursor.execute(
            """SELECT assessment_id::text AS assessment_id,
                      current_assessment_authority_id::text AS current_assessment_authority_id,
                      identity_authority_id::text AS identity_authority_id,
                      identity_authority_member_ordinal,
                      security_id::text AS durable_security_id,symbol AS durable_symbol,
                      decision_cutoff AS durable_decision_cutoff,
                      assessment_content_hash,
                      canonical_body_text,payload_sha256,canonical_payload,
                      canonical_payload_text,recorded_at,source_count,operand_count,
                      parent_count,reason_count
               FROM analytics.fv_current_assessment_v1 WHERE assessment_id=%s""",
            (assessment_id,),
        )
        root = cursor.fetchone()
        if root is None:
            return None
        cursor.execute(
            """SELECT source_ordinal,source_role,raw_manifest_id::text AS raw_manifest_id,
                      provider_code,schema_version,source_reference,file_sha256,
                      source_content_hash,normalized_record_hash,available_at,
                      retrieved_at,ingested_at,source_revision,adapter_version,
                      normalization_version,freshness_policy_version,
                      source_record_id::text AS source_record_id,request_identity,
                      plan_hash,checkpoint_reference
               FROM analytics.fv_current_assessment_source_v1
               WHERE assessment_id=%s ORDER BY source_ordinal""",
            (assessment_id,),
        )
        sources = cursor.fetchall()
        cursor.execute(
            """SELECT operand_ordinal,operand_code,state,numeric_value,evidence_kind,
                      source_roles,producer_contract_hash,output_content_hash,
                      parent_count,reason_count
               FROM analytics.fv_current_assessment_operand_v1
               WHERE assessment_id=%s ORDER BY operand_ordinal""",
            (assessment_id,),
        )
        operands = cursor.fetchall()
        cursor.execute(
            """SELECT operand_ordinal,parent_ordinal,
                      raw_manifest_id::text AS raw_manifest_id,source_ordinal
               FROM analytics.fv_current_assessment_operand_parent_v1
               WHERE assessment_id=%s ORDER BY operand_ordinal,parent_ordinal""",
            (assessment_id,),
        )
        parents = cursor.fetchall()
        cursor.execute(
            """SELECT operand_ordinal,reason_ordinal,reason_code
               FROM analytics.fv_current_assessment_operand_reason_v1
               WHERE assessment_id=%s ORDER BY operand_ordinal,reason_ordinal""",
            (assessment_id,),
        )
        reasons = cursor.fetchall()
        cursor.execute(
            """SELECT source_count,operand_count,parent_count,reason_count,
                      assessment_content_hash,payload_sha256
               FROM analytics.fv_current_assessment_seal_v1 WHERE assessment_id=%s""",
            (assessment_id,),
        )
        seal = cursor.fetchone()
        payload = root["canonical_payload"]
        if type(payload) is not dict or seal is None:
            raise CurrentAssessmentPersistenceConflict(
                "CURRENT_ASSESSMENT_DURABLE_GRAPH_INCOMPLETE"
            )
        counts = (len(sources), len(operands), len(parents), len(reasons))
        expected_counts = (2, 34, 32, 1)
        if (
            counts != expected_counts
            or tuple(
                root[key]
                for key in (
                    "source_count",
                    "operand_count",
                    "parent_count",
                    "reason_count",
                )
            )
            != expected_counts
            or tuple(
                seal[key]
                for key in (
                    "source_count",
                    "operand_count",
                    "parent_count",
                    "reason_count",
                )
            )
            != expected_counts
            or seal["assessment_content_hash"] != root["assessment_content_hash"]
            or seal["payload_sha256"] != root["payload_sha256"]
            or root["canonical_payload_text"] != _payload_text(payload)
            or root["canonical_body_text"] != _body_text(payload)
        ):
            raise CurrentAssessmentPersistenceConflict(
                "CURRENT_ASSESSMENT_DURABLE_CARDINALITY_DRIFT"
            )
        if (
            root["durable_security_id"] != payload.get("security_id")
            or root["durable_symbol"] != payload.get("symbol")
            or root["durable_decision_cutoff"]
            != _instant(
                payload.get("decision_cutoff"),
                "CURRENT_ASSESSMENT_DECISION_CUTOFF_INVALID",
            )
        ):
            raise CurrentAssessmentPersistenceConflict(
                "CURRENT_ASSESSMENT_ROOT_PROJECTION_DRIFT"
            )
        _verify_current_assessment_authority(cursor, root, payload)
        _verify_sources(payload, sources)
        _verify_operands(payload, operands, parents, reasons)
        _assessment_from_payload(
            payload,
            durable_operand_values={
                row["operand_code"]: row["numeric_value"] for row in operands
            },
        )
        return PersistedCurrentAssessmentV1(
            assessment_id=root["assessment_id"],
            assessment_content_hash=root["assessment_content_hash"],
            payload_sha256=root["payload_sha256"],
            payload=payload,
            recorded_at=root["recorded_at"],
        )


def _verify_current_assessment_authority(
    cursor: Any, root: dict[str, Any], payload: dict[str, Any]
) -> None:
    cursor.execute(
        """SELECT a.authority_id::text AS authority_id,
                  a.contract_version,a.identity_authority_id::text AS identity_authority_id,
                  a.identity_projection_content_hash,a.authorized_symbols,
                  a.evidence_track,a.model_evidence_label,
                  a.authorization_reference,a.authorization_content_hash,
                  a.assessment_persistence_authorized,
                  a.read_only_publication_authorized,
                  a.deterministic_action_authorized,
                  a.deterministic_ranking_authorized,
                  a.final_portfolio_weight_authorized,
                  a.automatic_brokerage_execution_authorized,
                  a.evidence_label_upgrade_authorized,
                  identity.projection_content_hash
           FROM analytics.fv_current_assessment_authority_v1 a
           JOIN analytics.fv_identity_authority_v2 identity
             ON identity.authority_id=a.identity_authority_id
           WHERE a.authority_id=%s""",
        (root["current_assessment_authority_id"],),
    )
    row = cursor.fetchone()
    if row is None:
        raise CurrentAssessmentPersistenceConflict(
            "CURRENT_ASSESSMENT_AUTHORITY_MISSING"
        )
    projection_hash = row["identity_projection_content_hash"]
    if (
        row["authority_id"]
        != current_assessment_authority_id_v1(projection_hash)
        or row["identity_authority_id"] != root["identity_authority_id"]
        or row["projection_content_hash"] != projection_hash
        or row["contract_version"] != AUTHORITY_CONTRACT_VERSION
        or tuple(row["authorized_symbols"]) != AUTHORIZED_SYMBOLS
        or payload.get("symbol") not in AUTHORIZED_SYMBOLS
        or row["evidence_track"] != payload.get("evidence_track")
        or row["model_evidence_label"] != "NOT_VALIDATED"
        or row["authorization_reference"] != AUTHORIZATION_REFERENCE
        or row["authorization_content_hash"] != AUTHORIZATION_CONTENT_HASH
        or row["assessment_persistence_authorized"] is not True
        or row["read_only_publication_authorized"] is not True
        or row["deterministic_action_authorized"] is not False
        or row["deterministic_ranking_authorized"] is not False
        or row["final_portfolio_weight_authorized"] is not False
        or row["automatic_brokerage_execution_authorized"] is not False
        or row["evidence_label_upgrade_authorized"] is not False
    ):
        raise CurrentAssessmentPersistenceConflict(
            "CURRENT_ASSESSMENT_AUTHORITY_DRIFT"
        )


def _verify_sources(payload: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    expected = payload.get("source_seals")
    if type(expected) is not list or len(expected) != len(rows):
        raise CurrentAssessmentPersistenceConflict("CURRENT_ASSESSMENT_SOURCE_DRIFT")
    actual = []
    for row in rows:
        actual.append(
            {
                "adapter_version": row["adapter_version"],
                "available_at": _wire_instant(row["available_at"]),
                "checkpoint_reference": row["checkpoint_reference"],
                "content_hash": row["normalized_record_hash"],
                "file_sha256": row["file_sha256"],
                "freshness_policy_version": row["freshness_policy_version"],
                "ingested_at": _wire_instant(row["ingested_at"]),
                "normalization_version": row["normalization_version"],
                "normalized_record_hash": row["normalized_record_hash"],
                "plan_hash": row["plan_hash"],
                "provider_code": row["provider_code"],
                "raw_manifest_id": row["raw_manifest_id"],
                "request_identity": row["request_identity"],
                "retrieved_at": None
                if row["retrieved_at"] is None
                else _wire_instant(row["retrieved_at"]),
                "schema_version": row["schema_version"],
                "source_content_hash": row["source_content_hash"],
                "source_record_id": row["source_record_id"],
                "source_reference": row["source_reference"],
                "source_revision": row["source_revision"],
            }
        )
    if actual != expected:
        raise CurrentAssessmentPersistenceConflict("CURRENT_ASSESSMENT_SOURCE_DRIFT")


def _verify_operands(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    parents: list[dict[str, Any]],
    reasons: list[dict[str, Any]],
) -> None:
    expected = payload.get("input_evidence")
    if type(expected) is not list or len(expected) != len(rows):
        raise CurrentAssessmentPersistenceConflict("CURRENT_ASSESSMENT_OPERAND_DRIFT")
    source_seals = payload.get("source_seals")
    if type(source_seals) is not list:
        raise CurrentAssessmentPersistenceConflict("CURRENT_ASSESSMENT_SOURCE_DRIFT")
    manifest_to_ordinal = {
        source["raw_manifest_id"]: ordinal
        for ordinal, source in enumerate(source_seals, 1)
    }
    parent_map: dict[int, list[str]] = {}
    for row in parents:
        expected_source_ordinal = manifest_to_ordinal.get(row["raw_manifest_id"])
        if (
            expected_source_ordinal is None
            or row["source_ordinal"] != expected_source_ordinal
        ):
            raise CurrentAssessmentPersistenceConflict(
                "CURRENT_ASSESSMENT_PARENT_SOURCE_DRIFT"
            )
        parent_map.setdefault(row["operand_ordinal"], []).append(row["raw_manifest_id"])
    reason_map: dict[int, list[str]] = {}
    for row in reasons:
        reason_map.setdefault(row["operand_ordinal"], []).append(row["reason_code"])
    actual = [
        {
            "evidence_kind": row["evidence_kind"],
            "operand_code": row["operand_code"],
            "output_content_hash": row["output_content_hash"],
            "producer_contract_hash": row["producer_contract_hash"],
            "reason_codes": reason_map.get(row["operand_ordinal"], []),
            "source_parent_ids": parent_map.get(row["operand_ordinal"], []),
            "source_roles": row["source_roles"],
            "state": row["state"],
            "value": None
            if row["numeric_value"] is None
            else _plain(row["numeric_value"]),
        }
        for row in rows
    ]
    if actual != expected:
        raise CurrentAssessmentPersistenceConflict("CURRENT_ASSESSMENT_OPERAND_DRIFT")


def _wire_instant(value: datetime) -> str:
    return _instant_value(value, "CURRENT_ASSESSMENT_DURABLE_INSTANT_INVALID").isoformat().replace(
        "+00:00", "Z"
    )


__all__ = [
    "AUTHORITY_CONTRACT_VERSION",
    "AUTHORIZATION_CONTENT_HASH",
    "AUTHORIZATION_REFERENCE",
    "AUTHORIZED_SYMBOLS",
    "CurrentAssessmentPersistenceConflict",
    "CurrentAssessmentPersistenceViolation",
    "CurrentAssessmentRepositoryV1",
    "PERSISTENCE_VERSION",
    "PersistedCurrentAssessmentV1",
    "current_assessment_authority_id_v1",
    "current_assessment_id_v1",
    "provision_current_assessment_authority_v1",
]
