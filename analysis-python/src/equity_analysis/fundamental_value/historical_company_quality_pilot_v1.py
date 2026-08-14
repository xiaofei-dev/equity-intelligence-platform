from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, DecimalException
from enum import StrEnum
from pathlib import Path

from equity_analysis.fundamental_value.core_v1 import MetricEvidence, evaluate_fundamental_value_v1
from equity_analysis.fundamental_value.historical_preparation_v1 import (
    COVERAGE_FILE_SHA256,
    COVERAGE_PATH,
    SEC_V4_PATH,
    build_diagnostic_inputs,
    build_predictor_registry,
    canonical_hash,
    extract_target_component,
)
from equity_analysis.historical_validation.provider_backtest_coverage_v1 import (
    _verify_artifact as verify_artifact,
)

PILOT_VERSION = "FV-STAGE7C2-COMPANY-QUALITY-PILOT-v1.0.0"
PRODUCER_VERSION = "FV-STAGE7-COMPANY-QUALITY-PRODUCERS-v1.1.0"
PRODUCER_CODES = (
    "return_on_invested_capital",
    "operating_margin",
    "free_cash_flow_margin",
    "earnings_stability",
    "cash_flow_stability",
)
FLOW_PARENTS = (
    "income_tax", "pretax_income", "operating_income", "revenue",
    "operating_cash_flow", "capital_expenditure", "net_income",
)
BALANCE_PARENTS = ("stockholders_equity", "total_debt", "cash_and_equivalents")
DATE_SEED = "FV-STAGE7-PRIMARY-Q2-DECISION-DATES-v1"


class AvailabilityStratum(StrEnum):
    STRICT_PIT = "STRICT_PIT"
    CURRENT_REVISION_APPROXIMATION = "CURRENT_REVISION_APPROXIMATION"


class PilotState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    INVALID = "INVALID"
    PARENT_COVERAGE_UNPROVEN = "PARENT_COVERAGE_UNPROVEN"


class PilotError(ValueError):
    pass


@dataclass(frozen=True)
class ProducerContractV1:
    producer_code: str
    producer_version: str
    parent_operands: tuple[str, ...]
    formula: str
    duration_policy: str
    period_count: int
    unit: str
    currency: str
    denominator_policy: str
    sign_policy: str
    outlier_policy: str
    revision_policy: str
    availability_stratum: AvailabilityStratum
    content_hash: str


@dataclass(frozen=True)
class ParentBindingV1:
    operand: str
    observation_id: str
    content_hash: str
    period_start: date
    period_end: date
    duration_class: str
    available_at: datetime


@dataclass(frozen=True)
class Stage7ProducedEvidenceV1:
    availability_stratum: AvailabilityStratum
    producer_code: str
    producer_version: str
    producer_content_hash: str
    security_id: str
    issuer_id: str
    listing_id: str
    decision_cutoff: datetime
    period_start: date | None
    period_end: date | None
    effective_at: datetime | None
    available_at: datetime | None
    ingested_at: datetime | None
    unit: str
    currency: str
    period_semantics: str
    ordered_parents: tuple[ParentBindingV1, ...]
    state: PilotState
    reason_code: str | None
    value: Decimal | None
    output_hash: str


@dataclass(frozen=True)
class RawPoint:
    operand: str
    value: Decimal
    unit: str
    currency: str
    period_start: date
    period_end: date
    duration_class: str
    available_at: datetime
    ingested_at: datetime
    observation_id: str
    content_hash: str
    mapping_priority: int

    @property
    def period_key(self) -> tuple[date, date]:
        return self.period_start, self.period_end


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise PilotError(f"{field}_REQUIRED")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PilotError(f"{field}_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(UTC)


def _nonblank(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PilotError(f"{field}_REQUIRED")


def _producer(
    code: str, parents: tuple[str, ...], formula: str, periods: int,
    denominator: str, sign: str, outlier: str,
) -> ProducerContractV1:
    body = {
        "producerCode": code, "producerVersion": PRODUCER_VERSION,
        "parentOperands": parents, "formula": formula,
        "durationPolicy": (
            "HASH_VERIFIED_SEC_DISTINCT_QUARTER_END_CHAIN_"
            "AVAILABLE_BY_CUTOFF-v1.0.0"
        ),
        "periodCount": periods, "unit": "RATIO", "currency": "USD",
        "denominatorPolicy": denominator, "signPolicy": sign,
        "outlierPolicy": outlier,
        "revisionPolicy": "LATEST_AVAILABLE_REVISION_PER_EXACT_PERIOD_FAIL_ON_TIE",
        "availabilityStratum": AvailabilityStratum.STRICT_PIT,
    }
    return ProducerContractV1(
        code, PRODUCER_VERSION, parents, formula,
        body["durationPolicy"], periods, "RATIO", "USD", denominator,
        sign, outlier, body["revisionPolicy"], AvailabilityStratum.STRICT_PIT,
        canonical_hash(body),
    )


def build_company_quality_producer_registry() -> dict[str, ProducerContractV1]:
    values = (
        _producer("return_on_invested_capital",
            ("income_tax", "pretax_income", "operating_income",
             "stockholders_equity", "total_debt", "cash_and_equivalents"),
            "SUM(operating_income)*(1-SUM(income_tax)/SUM(pretax_income))"
            "/AVG(beginning_and_ending_invested_capital)", 4,
            "pretax_income>0 and average_invested_capital>0",
            "tax and operating income preserve reported signs",
            "0<=tax_rate<=0.50 and -1<=ROIC<=2"),
        _producer("operating_margin", ("operating_income", "revenue"),
            "SUM(operating_income)/SUM(revenue)", 4, "revenue>0",
            "reported signs", "-1<=margin<=1"),
        _producer("free_cash_flow_margin",
            ("operating_cash_flow", "capital_expenditure", "revenue"),
            "(SUM(operating_cash_flow)-SUM(capital_expenditure))/SUM(revenue)",
            4, "revenue>0", "capital_expenditure must be nonnegative cash outflow",
            "-2<=margin<=2"),
        _producer("earnings_stability", ("net_income",),
            "CLAMP(1-POPULATION_STDDEV/ABS(MEAN),0,1)", 8,
            "ABS(mean)>0.000001", "reported signs", "0<=stability<=1"),
        _producer("cash_flow_stability", ("operating_cash_flow",),
            "CLAMP(1-POPULATION_STDDEV/ABS(MEAN),0,1)", 8,
            "ABS(mean)>0.000001", "reported signs", "0<=stability<=1"),
    )
    return {item.producer_code: item for item in values}


def _envelope_body(value: Stage7ProducedEvidenceV1) -> dict[str, object]:
    body = asdict(value)
    body.pop("output_hash")
    return body


def validate_produced_evidence(
    value: Stage7ProducedEvidenceV1, contract: ProducerContractV1,
) -> None:
    if value.producer_code != contract.producer_code:
        raise PilotError("PRODUCER_CODE_MISMATCH")
    if (value.producer_version != contract.producer_version
            or value.producer_content_hash != contract.content_hash):
        raise PilotError("PRODUCER_CONTRACT_MISMATCH")
    if value.availability_stratum != contract.availability_stratum:
        raise PilotError("AVAILABILITY_STRATUM_CONTRACT_MISMATCH")
    for item, field in ((value.security_id, "SECURITY_ID"),
                        (value.issuer_id, "ISSUER_ID"),
                        (value.listing_id, "LISTING_ID")):
        _nonblank(item, field)
    for timestamp, field in ((value.decision_cutoff, "DECISION_CUTOFF"),
                             (value.effective_at, "EFFECTIVE_AT"),
                             (value.available_at, "AVAILABLE_AT"),
                             (value.ingested_at, "INGESTED_AT")):
        if timestamp is not None and (timestamp.tzinfo is None
                                      or timestamp.utcoffset() is None):
            raise PilotError(f"{field}_MUST_BE_TIMEZONE_AWARE")
    if value.state == PilotState.VALID:
        if value.value is None or not value.value.is_finite():
            raise PilotError("VALID_EVIDENCE_REQUIRES_FINITE_VALUE")
        if value.reason_code is not None or not value.ordered_parents:
            raise PilotError("VALID_EVIDENCE_LINEAGE_INVALID")
        parent_ids = [item.observation_id for item in value.ordered_parents]
        if len(set(parent_ids)) != len(parent_ids):
            raise PilotError("DUPLICATE_PARENT_ID")
        for parent in value.ordered_parents:
            if (len(parent.content_hash) != 64
                    or any(c not in "0123456789ABCDEF" for c in parent.content_hash)
                    or not parent.observation_id.endswith(parent.content_hash)):
                raise PilotError("PARENT_ID_HASH_BINDING_INVALID")
            if parent.operand not in contract.parent_operands:
                raise PilotError("PARENT_OPERAND_ROLE_INVALID")
            if (parent.available_at.tzinfo is None
                    or parent.available_at.utcoffset() is None):
                raise PilotError("PARENT_AVAILABLE_AT_MUST_BE_AWARE")
            if parent.period_end > value.decision_cutoff.date():
                raise PilotError("PARENT_PERIOD_AFTER_CUTOFF")
            if parent.available_at > value.decision_cutoff:
                raise PilotError("PARENT_AVAILABLE_AFTER_CUTOFF")
        counts = Counter(item.operand for item in value.ordered_parents)
        for operand in contract.parent_operands:
            required = (2 if contract.producer_code == "return_on_invested_capital"
                        and operand in BALANCE_PARENTS else contract.period_count)
            if counts[operand] != required:
                raise PilotError("PARENT_OPERAND_MULTIPLICITY_INVALID")
        _validate_parent_period_semantics(contract, value.ordered_parents)
        if None in (value.period_start, value.period_end, value.effective_at,
                    value.available_at, value.ingested_at):
            raise PilotError("VALID_EVIDENCE_CHRONOLOGY_REQUIRED")
        assert value.period_end is not None and value.effective_at is not None
        assert value.available_at is not None and value.ingested_at is not None
        if value.period_end > value.decision_cutoff.date():
            raise PilotError("FUTURE_PERIOD_LEAKAGE")
        if not (value.effective_at <= value.available_at <= value.ingested_at):
            raise PilotError("EVIDENCE_CHRONOLOGY_INVALID")
        if (value.availability_stratum == AvailabilityStratum.STRICT_PIT
                and value.available_at > value.decision_cutoff):
            raise PilotError("STRICT_PIT_FUTURE_AVAILABILITY")
        if value.unit != contract.unit or value.currency != contract.currency:
            raise PilotError("OUTPUT_UNIT_OR_CURRENCY_MISMATCH")
    elif value.value is not None or not value.reason_code:
        raise PilotError("NON_VALID_EVIDENCE_MUST_BE_VALUELESS")
    if value.output_hash != canonical_hash(_envelope_body(value)):
        raise PilotError("OUTPUT_HASH_DRIFT")


def _continuous_period_keys(keys: Sequence[tuple[date, date]]) -> None:
    if len(keys) != len(set(keys)) or any(start > end for start, end in keys):
        raise PilotError("PARENT_PERIOD_KEYS_INVALID")
    ordered = sorted(keys, key=lambda item: (item[1], item[0]))
    if any(not (60 <= (current[1] - previous[1]).days <= 120
                   and abs((current[0] - previous[1]).days) <= 7)
           for previous, current in zip(ordered, ordered[1:], strict=False)):
        raise PilotError("PARENT_PERIOD_CONTINUITY_INVALID")


def _validate_parent_period_semantics(
    contract: ProducerContractV1, parents: Sequence[ParentBindingV1],
) -> None:
    for parent in parents:
        if parent.period_start > parent.period_end:
            raise PilotError("PARENT_PERIOD_KEYS_INVALID")
        if parent.available_at.tzinfo is None or parent.available_at.utcoffset() is None:
            raise PilotError("PARENT_AVAILABLE_AT_MUST_BE_AWARE")
    flow_operands = tuple(item for item in contract.parent_operands
                          if item not in BALANCE_PARENTS)
    flow_keys: set[tuple[date, date]] | None = None
    for operand in flow_operands:
        values = [item for item in parents if item.operand == operand]
        if any(item.duration_class != "DISCRETE_QUARTER" for item in values):
            raise PilotError("FLOW_PARENT_DURATION_INVALID")
        keys = {(item.period_start, item.period_end) for item in values}
        if len(keys) != contract.period_count:
            raise PilotError("FLOW_PARENT_PERIOD_DUPLICATE_OR_MISSING")
        if flow_keys is None:
            flow_keys = keys
        elif keys != flow_keys:
            raise PilotError("FLOW_PARENT_EXACT_PERIOD_MISMATCH")
    assert flow_keys is not None
    _continuous_period_keys(sorted(flow_keys))
    if contract.producer_code != "return_on_invested_capital":
        return
    flow_start = min(item[0] for item in flow_keys)
    flow_end = max(item[1] for item in flow_keys)
    for operand in BALANCE_PARENTS:
        values = sorted((item for item in parents if item.operand == operand),
                        key=lambda item: item.period_end)
        if any(item.duration_class != "INSTANT" for item in values):
            raise PilotError("BALANCE_PARENT_DURATION_INVALID")
        if not (0 <= (flow_start - values[0].period_end).days <= 120
                and 0 <= (flow_end - values[1].period_end).days <= 120
                and values[0].period_end <= values[1].period_end):
            raise PilotError("ROIC_BALANCE_BOUNDARY_BINDING_INVALID")


def _missing_envelope(
    contract: ProducerContractV1, identity: Mapping[str, str], cutoff: datetime,
    stratum: AvailabilityStratum, reason: str,
    state: PilotState = PilotState.MISSING,
) -> Stage7ProducedEvidenceV1:
    body = dict(
        availability_stratum=stratum, producer_code=contract.producer_code,
        producer_version=contract.producer_version,
        producer_content_hash=contract.content_hash,
        security_id=identity["securityId"], issuer_id=identity["issuerId"],
        listing_id=identity["listingId"], decision_cutoff=cutoff,
        period_start=None, period_end=None, effective_at=None, available_at=None,
        ingested_at=None, unit=contract.unit, currency=contract.currency,
        period_semantics=contract.duration_policy, ordered_parents=(),
        state=state, reason_code=reason, value=None,
    )
    provisional = Stage7ProducedEvidenceV1(**body, output_hash="")
    return Stage7ProducedEvidenceV1(**body, output_hash=canonical_hash(_envelope_body(provisional)))


def bind_controlled_100_sec_intersection(
    repository_root: Path, controlled_root: Path | None = None,
) -> dict[str, object]:
    coverage_path = repository_root / COVERAGE_PATH
    if hashlib.sha256(coverage_path.read_bytes()).hexdigest().upper() != COVERAGE_FILE_SHA256:
        raise PilotError("CONTROLLED_100_FILE_HASH_MISMATCH")
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage_hash = verify_artifact(coverage, label="CONTROLLED_100_COVERAGE")
    sec = json.loads((repository_root / SEC_V4_PATH).read_text(encoding="utf-8"))
    sec_hash = verify_artifact(sec, label="SEC_V4_MANIFEST")
    sec_rows = list(sec.get("securities", []))
    sec_by_symbol = _unique_sec_rows_by_symbol(sec_rows)
    rows = []
    for item in coverage.get("results", []):
        symbol = str(item.get("symbol", "")).upper()
        security_id = str(item.get("securityId", ""))
        sec_item = sec_by_symbol.get(symbol)
        if (not security_id or sec_item is None
                or sec_item.get("status") != "SEC_TIMELINE_BUILT"):
            raise PilotError(f"CONTROLLED_100_SEC_INTERSECTION_FAILED[{symbol}]")
        payload_hash = str(sec_item.get("payloadContentHash", "")).upper()
        issuer_id = f"SEC_PAYLOAD:{payload_hash}"
        if controlled_root is not None:
            payload_path = controlled_root / sec_item["storageReference"]
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            if canonical_hash(payload) != payload_hash:
                raise PilotError("SEC_PAYLOAD_HASH_MISMATCH")
            issuer_id = str(payload.get("entityId", ""))
            _nonblank(issuer_id, "SEC_ENTITY_ID")
        row = {
            "securityId": security_id, "issuerId": issuer_id,
            "listingId": f"US_LISTING:{security_id.removeprefix('US:')}",
            "symbol": symbol, "sector": item.get("sector"),
            "controlledPayloadHash": item["controlledPayload"]["contentHash"],
            "secPayloadHash": payload_hash,
            "secStorageReference": sec_item["storageReference"],
        }
        row["identityBindingHash"] = canonical_hash(row)
        rows.append(row)
    if len(rows) != 100 or len({item["securityId"] for item in rows}) != 100:
        raise PilotError("CONTROLLED_100_EXACT_CARDINALITY_REQUIRED")
    rows.sort(key=lambda item: item["securityId"])
    body: dict[str, object] = {
        "coverageArtifactHash": coverage_hash, "secV4ArtifactHash": sec_hash,
        "intersectionCount": 100, "builtTimelineCount": 100,
        "identityLimitation": (
            "listingId is a frozen Stage7 validation identity, not a vendor ID; "
            "issuerId is payload-bound when controlled storage is supplied."
        ),
        "securities": rows,
    }
    body["contentHash"] = canonical_hash(body)
    return body


def _unique_sec_rows_by_symbol(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    symbols = [str(item.get("symbol", "")).upper() for item in rows]
    if any(not item for item in symbols) or len(symbols) != len(set(symbols)):
        raise PilotError("DUPLICATE_OR_EMPTY_SEC_MANIFEST_SYMBOL")
    return {str(item.get("symbol", "")).upper(): item for item in rows}


def select_cross_sector_pilot25(intersection: Mapping[str, object]) -> tuple[str, ...]:
    rows = list(intersection["securities"])
    ranked = sorted(rows, key=lambda item: (hashlib.sha256(
        f"FV-STAGE7C1-PILOT25|{item['identityBindingHash']}".encode()).hexdigest(),
        item["securityId"]))
    selected: list[Mapping[str, object]] = []
    for sector in sorted({str(item["sector"]) for item in rows}):
        selected.append(next(item for item in ranked if item["sector"] == sector))
    selected_ids = {item["securityId"] for item in selected}
    selected.extend(item for item in ranked if item["securityId"] not in selected_ids)
    return tuple(str(item["securityId"]) for item in selected[:25])


def freeze_q2_dates_from_sessions(sessions: Sequence[date]) -> tuple[date, ...]:
    if list(sessions) != sorted(set(sessions)):
        raise PilotError("SESSION_CALENDAR_NOT_SORTED_UNIQUE")
    calendar_hash = canonical_hash([item.isoformat() for item in sessions])
    result = []
    for year in range(2015, 2024):
        candidates = [item for item in sessions
                      if item.year == year and 4 <= item.month <= 6]
        if not candidates:
            raise PilotError(f"Q2_SESSION_MISSING[{year}]")
        result.append(min(candidates, key=lambda item: hashlib.sha256(
            f"{DATE_SEED}|{calendar_hash}|{year}|{item.isoformat()}".encode()
        ).hexdigest()))
    return tuple(result)


def load_session_calendar_dates_only(price_payload_path: Path) -> tuple[date, ...]:
    text = price_payload_path.read_text(encoding="utf-8")
    matches = re.findall(r'"tradingDate"\s*:\s*"(\d{4}-\d{2}-\d{2})"', text)
    if not matches:
        raise PilotError("PRICE_CALENDAR_DATE_MISSING")
    # The regex deliberately extracts only session labels; price/return fields
    # are never deserialized or accessed by this validation stage.
    return tuple(date.fromisoformat(item) for item in matches)


def _payload_points(payload: Mapping[str, object], cutoff: datetime) -> list[RawPoint]:
    points = []
    observation_ingested = {str(item.get("observationId")): item.get("ingestedAt")
                            for item in payload.get("observations", [])}
    for record in [*payload.get("observations", []), *payload.get("derivations", [])]:
        if not isinstance(record, dict):
            raise PilotError("SEC_RECORD_INVALID")
        if (record.get("normalizedOperand") not in {*FLOW_PARENTS, *BALANCE_PARENTS}
                or record.get("durationClass") not in {"DISCRETE_QUARTER", "INSTANT"}):
            continue
        available = _aware(record.get("availableAt"), "AVAILABLE_AT")
        if available > cutoff:
            continue
        body = dict(record)
        content_hash = str(body.pop("contentHash", "")).upper()
        observation_id = str(body.pop("observationId", ""))
        if canonical_hash(body) != content_hash or not observation_id.endswith(content_hash):
            raise PilotError("SEC_RECORD_HASH_MISMATCH")
        ingested_raw = record.get("ingestedAt")
        if ingested_raw is None:
            parent_ingested = [observation_ingested.get(str(parent))
                               for parent in record.get("orderedOperandIds", [])]
            if not parent_ingested or any(item is None for item in parent_ingested):
                raise PilotError("DERIVATION_INGESTED_LINEAGE_MISSING")
            ingested_raw = max(str(item) for item in parent_ingested)
        try:
            value = Decimal(str(record["value"]))
            end = date.fromisoformat(str(record["periodEnd"]))
            start_raw = record.get("periodStart")
            start = end if record.get("durationClass") == "INSTANT" else date.fromisoformat(
                str(start_raw))
        except (KeyError, ValueError, DecimalException) as error:
            raise PilotError("SEC_RECORD_VALUE_OR_PERIOD_INVALID") from error
        point = RawPoint(str(record.get("normalizedOperand")), value,
            str(record.get("unit")), str(record.get("currency")), start, end,
            str(record.get("durationClass")), available,
            _aware(ingested_raw, "INGESTED_AT"), observation_id, content_hash,
            int(record.get("mappingPriority", 999)))
        if point.period_end > cutoff.date() or point.available_at > point.ingested_at:
            raise PilotError("SEC_RECORD_CHRONOLOGY_INVALID")
        points.append(point)
    return points


def _candidate_points_by_period(
    points: Sequence[RawPoint], duration: str,
) -> dict[str, dict[tuple[date, date], tuple[RawPoint, ...]]]:
    grouped: dict[tuple[str, date, date], list[RawPoint]] = {}
    for point in points:
        if point.duration_class != duration:
            continue
        key = point.operand, point.period_start, point.period_end
        grouped.setdefault(key, []).append(point)
    result: dict[str, dict[tuple[date, date], tuple[RawPoint, ...]]] = {}
    for (operand, start, end), values in grouped.items():
        result.setdefault(operand, {})[(start, end)] = tuple(values)
    return result


def _resolve_exact_revision(values: Sequence[RawPoint]) -> RawPoint:
    if not values:
        raise PilotError("EXACT_PERIOD_PARENT_MISSING")
    best_priority = min(item.mapping_priority for item in values)
    priority = [item for item in values if item.mapping_priority == best_priority]
    best_available = max(item.available_at for item in priority)
    top = [item for item in priority if item.available_at == best_available]
    if len({item.content_hash for item in top}) != 1:
        raise PilotError("SELECTED_PARENT_REVISION_AMBIGUITY")
    return max(top, key=lambda item: item.observation_id)


def _variant_rank(key: tuple[date, date]) -> tuple[int, date]:
    start, end = key
    return abs((end - start).days - 91), start


def _aligned(
    by_operand: Mapping[
        str, Mapping[tuple[date, date], Sequence[RawPoint]]
    ], operands: Sequence[str], count: int,
) -> list[list[RawPoint]]:
    sets = [set(by_operand.get(item, {})) for item in operands]
    common = set.intersection(*sets) if sets else set()
    variants_by_end: dict[date, list[tuple[date, date]]] = {}
    for key in common:
        variants_by_end.setdefault(key[1], []).append(key)
    ends = sorted(variants_by_end)
    chains: list[tuple[tuple[int, int], tuple[tuple[date, date], ...]]] = []
    for end_index in range(count - 1, len(ends)):
        selected_ends = ends[end_index - count + 1:end_index + 1]
        if any(not 60 <= (right - left).days <= 120
               for left, right in zip(selected_ends, selected_ends[1:], strict=False)):
            continue
        partial: list[tuple[tuple[date, date], ...]] = [()]
        for period_end in selected_ends:
            partial = [(*chain, variant) for chain in partial
                       for variant in variants_by_end[period_end]
                       if not chain or abs((variant[0] - chain[-1][1]).days) <= 7]
        for chain in partial:
            deviation = sum(_variant_rank(item)[0] for item in chain)
            chains.append(((-chain[-1][1].toordinal(), deviation), chain))
    if not chains:
        raise PilotError("MISSING_ALIGNED_PERIODS")
    best_rank = min(item[0] for item in chains)
    top = [chain for rank, chain in chains if rank == best_rank]
    if len(top) > 1:
        evidence_sets = {
            tuple(tuple(sorted(point.content_hash for point in by_operand[operand][key]))
                  for key in chain for operand in operands)
            for chain in top
        }
        if len(evidence_sets) > 1:
            raise PilotError("EQUALLY_RANKED_PERIOD_VARIANT_AMBIGUITY")
    keys = min(top, key=lambda chain: tuple(item[0] for item in chain))
    if len({item[1] for item in keys}) != count:
        raise PilotError("DISTINCT_QUARTER_CARDINALITY_INVALID")
    rows = [[_resolve_exact_revision(by_operand[item][key])
             for item in operands] for key in keys]
    if any(point.unit != "USD" or point.currency != "USD"
           for row in rows for point in row):
        raise PilotError("PARENT_UNIT_OR_CURRENCY_MISMATCH")
    return rows


def _stability(values: Sequence[Decimal]) -> Decimal:
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    if abs(mean) <= Decimal("0.000001"):
        raise PilotError("STABILITY_DENOMINATOR_INVALID")
    variance = sum(((item - mean) ** 2 for item in values), Decimal(0)) / Decimal(len(values))
    return max(Decimal(0), min(Decimal(1), Decimal(1) - variance.sqrt() / abs(mean)))


def _bounded_ratio(
    numerator: Decimal, denominator: Decimal, low: Decimal, high: Decimal,
) -> Decimal:
    if denominator <= 0:
        raise PilotError("DENOMINATOR_NONPOSITIVE")
    result = numerator / denominator
    if not result.is_finite() or not low <= result <= high:
        raise PilotError("OUTLIER_POLICY_FAILED")
    return result


def _fcf_margin(rows: Sequence[Sequence[RawPoint]]) -> Decimal:
    if any(row[1].value < 0 for row in rows):
        raise PilotError("CAPEX_SIGN_POLICY_FAILED")
    revenue = sum((row[2].value for row in rows), Decimal(0))
    numerator = (sum((row[0].value for row in rows), Decimal(0))
                 - sum((row[1].value for row in rows), Decimal(0)))
    return _bounded_ratio(numerator, revenue, Decimal("-2"), Decimal("2"))


def _select_balance_point(
    points: Mapping[tuple[date, date], Sequence[RawPoint]], boundary: date,
) -> RawPoint:
    candidates = [key for key in points
                  if 0 <= (boundary - key[1]).days <= 120]
    if not candidates:
        raise PilotError("BALANCE_PARENT_ALIGNMENT_MISSING")
    selected_key = max(candidates, key=lambda item: (item[1], item[0]))
    return _resolve_exact_revision(points[selected_key])


def _valid_envelope(
    contract: ProducerContractV1, identity: Mapping[str, str],
    cutoff: datetime, parents: Sequence[RawPoint], value: Decimal,
) -> Stage7ProducedEvidenceV1:
    ordered = sorted(parents, key=lambda item: (
        item.period_end, item.period_start, item.operand, item.observation_id))
    body = dict(availability_stratum=AvailabilityStratum.STRICT_PIT,
        producer_code=contract.producer_code, producer_version=contract.producer_version,
        producer_content_hash=contract.content_hash, security_id=identity["securityId"],
        issuer_id=identity["issuerId"], listing_id=identity["listingId"],
        decision_cutoff=cutoff, period_start=min(item.period_start for item in ordered),
        period_end=max(item.period_end for item in ordered),
        effective_at=datetime.combine(max(item.period_end for item in ordered), time.max, UTC),
        available_at=max(item.available_at for item in ordered),
        ingested_at=max(item.ingested_at for item in ordered), unit="RATIO", currency="USD",
        period_semantics=contract.duration_policy,
        ordered_parents=tuple(ParentBindingV1(
            item.operand, item.observation_id, item.content_hash,
            item.period_start, item.period_end, item.duration_class,
            item.available_at) for item in ordered),
        state=PilotState.VALID, reason_code=None, value=value)
    provisional = Stage7ProducedEvidenceV1(**body, output_hash="")
    result = Stage7ProducedEvidenceV1(
        **body, output_hash=canonical_hash(_envelope_body(provisional)))
    validate_produced_evidence(result, contract)
    return result


def produce_company_quality_operands(payload: Mapping[str, object], identity: Mapping[str, str],
                                     cutoff: datetime) -> dict[str, Stage7ProducedEvidenceV1]:
    contracts = build_company_quality_producer_registry()
    try:
        points = _payload_points(payload, cutoff)
        discrete = _candidate_points_by_period(points, "DISCRETE_QUARTER")
        instant = _candidate_points_by_period(points, "INSTANT")
    except PilotError as error:
        return {code: _missing_envelope(contract, identity, cutoff,
            AvailabilityStratum.STRICT_PIT, str(error), PilotState.INVALID)
            for code, contract in contracts.items()}
    result: dict[str, Stage7ProducedEvidenceV1] = {}
    for code, contract in contracts.items():
        try:
            if code == "operating_margin":
                rows = _aligned(discrete, contract.parent_operands, 4)
                parents = [point for row in rows for point in row]
                operating = sum((row[0].value for row in rows), Decimal(0))
                revenue = sum((row[1].value for row in rows), Decimal(0))
                value = _bounded_ratio(
                    operating, revenue, Decimal("-1"), Decimal("1"))
            elif code == "free_cash_flow_margin":
                rows = _aligned(discrete, contract.parent_operands, 4)
                parents = [point for row in rows for point in row]
                value = _fcf_margin(rows)
            elif code in {"earnings_stability", "cash_flow_stability"}:
                rows = _aligned(discrete, contract.parent_operands, 8)
                parents = [row[0] for row in rows]
                value = _stability([row[0].value for row in rows])
            else:
                flow_names = ("income_tax", "pretax_income", "operating_income")
                rows = _aligned(discrete, flow_names, 4)
                flow_parents = [point for row in rows for point in row]
                pretax = sum((row[1].value for row in rows), Decimal(0))
                if pretax <= 0:
                    raise PilotError("PRETAX_INCOME_NONPOSITIVE")
                tax_rate = sum((row[0].value for row in rows), Decimal(0)) / pretax
                if not Decimal(0) <= tax_rate <= Decimal("0.50"):
                    raise PilotError("TAX_RATE_OUTLIER")
                start, end = rows[0][0].period_start, rows[-1][0].period_end
                balance_rows = []
                for boundary in (start, end):
                    selected = []
                    for operand in BALANCE_PARENTS:
                        selected.append(_select_balance_point(
                            instant.get(operand, {}), boundary))
                    balance_rows.append(selected)
                capitals = [row[0].value + row[1].value - row[2].value
                            for row in balance_rows]
                average_capital = sum(capitals, Decimal(0)) / Decimal(2)
                if average_capital <= 0:
                    raise PilotError("INVESTED_CAPITAL_NONPOSITIVE")
                nopat = sum((row[2].value for row in rows), Decimal(0)) * (1 - tax_rate)
                value = nopat / average_capital
                if not Decimal("-1") <= value <= Decimal("2"):
                    raise PilotError("OUTLIER_POLICY_FAILED")
                parents = [*flow_parents, *[point for row in balance_rows for point in row]]
            if not value.is_finite():
                raise PilotError("NONFINITE_PRODUCER_OUTPUT")
            result[code] = _valid_envelope(contract, identity, cutoff, parents, value)
        except (PilotError, DecimalException) as error:
            result[code] = _missing_envelope(contract, identity, cutoff,
                AvailabilityStratum.STRICT_PIT, str(error), PilotState.MISSING)
    return result


def _target_state(evidence: Mapping[str, Stage7ProducedEvidenceV1]) -> tuple[str, str]:
    missing = [f"{code}:{item.reason_code}" for code, item in evidence.items()
               if item.state != PilotState.VALID]
    if missing:
        return "MISSING", missing[0]
    metric = {code: MetricEvidence.valid(item.value) for code, item in evidence.items()}
    assessment = evaluate_fundamental_value_v1(build_diagnostic_inputs(metric))
    mapping = next(item for item in build_predictor_registry()
                   if item.target == "COMPANY_QUALITY")
    component = extract_target_component(assessment, mapping)
    return ("VALID", "VALID") if component["admitted"] else (
        "MISSING", f"STAGE2_COMPONENT_{component['state']}")


def authorize_replay_phases(
    *, pilot_integrity_passed: bool, controlled100_integrity_passed: bool | None,
) -> tuple[str, ...]:
    if (type(pilot_integrity_passed) is not bool
            or (controlled100_integrity_passed is not None
                and type(controlled100_integrity_passed) is not bool)):
        raise PilotError("REPLAY_INTEGRITY_FLAG_MUST_BE_BOOL")
    phases = ["PILOT25"]
    if not pilot_integrity_passed:
        return tuple(phases)
    phases.append("CONTROLLED100")
    if controlled100_integrity_passed:
        phases.append("OFFLINE216")
    return tuple(phases)


def _run_coverage_phase(
    phase: str, ids: Sequence[str], identities: Mapping[str, Mapping[str, str]],
    cache: Mapping[str, Mapping[str, object]], dates: Sequence[date],
) -> dict[str, object]:
    matrix = []
    for decision_date in dates:
        cutoff = datetime.combine(decision_date, time.max, UTC)
        operand_counts = {code: Counter() for code in PRODUCER_CODES}
        target_counts: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        output_hashes = []
        for security_id in ids:
            evidence = produce_company_quality_operands(
                cache[security_id], identities[security_id], cutoff)
            for code, item in evidence.items():
                operand_counts[code][item.state] += 1
                reasons[item.reason_code or "VALID"] += 1
                output_hashes.append(item.output_hash)
            target_state, reason = _target_state(evidence)
            target_counts[target_state] += 1
            reasons[f"TARGET:{reason}"] += 1
        row = {"decisionDate": decision_date.isoformat(), "securityCount": len(ids),
            "availabilityStratum": AvailabilityStratum.STRICT_PIT,
            "operandStateCounts": {code: dict(sorted(counts.items(), key=str))
                                   for code, counts in operand_counts.items()},
            "companyQualityTargetCounts": dict(sorted(target_counts.items())),
            "reasonCounts": dict(sorted(reasons.items())),
            "valueFreeOutputSetHash": canonical_hash(sorted(output_hashes))}
        row["contentHash"] = canonical_hash(row)
        matrix.append(row)
    return {"phase": phase, "securityIds": tuple(ids), "matrix": matrix,
            "contentHash": canonical_hash(matrix)}


def replay_company_quality_coverage(
    repository_root: Path, controlled_root: Path, session_dates: Sequence[date],
) -> dict[str, object]:
    intersection = bind_controlled_100_sec_intersection(repository_root, controlled_root)
    dates = freeze_q2_dates_from_sessions(session_dates)
    rows_by_id = {item["securityId"]: item for item in intersection["securities"]}
    pilot_ids = select_cross_sector_pilot25(intersection)
    sec_manifest = json.loads((repository_root / SEC_V4_PATH).read_text(encoding="utf-8"))
    cache: dict[str, Mapping[str, object]] = {}
    for identity in intersection["securities"]:
        path = controlled_root / identity["secStorageReference"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        if canonical_hash(payload) != identity["secPayloadHash"]:
            raise PilotError("SEC_PAYLOAD_HASH_MISMATCH")
        if str(payload.get("symbol", "")).upper() != identity["symbol"]:
            raise PilotError("SEC_PAYLOAD_IDENTITY_MISMATCH")
        cache[identity["securityId"]] = payload
    phase_summaries = [_run_coverage_phase(
        "PILOT25", pilot_ids, rows_by_id, cache, dates)]
    authorized_after_pilot = authorize_replay_phases(
        pilot_integrity_passed=True, controlled100_integrity_passed=None)
    if "CONTROLLED100" not in authorized_after_pilot:
        raise PilotError("CONTROLLED100_NOT_AUTHORIZED")
    phase_summaries.append(_run_coverage_phase(
        "CONTROLLED100", tuple(sorted(rows_by_id)), rows_by_id, cache, dates))
    authorized_final = authorize_replay_phases(
        pilot_integrity_passed=True, controlled100_integrity_passed=True)
    if "OFFLINE216" not in authorized_final:
        raise PilotError("OFFLINE216_NOT_AUTHORIZED_AFTER_INTEGRITY_PASS")
    sec_by_symbol = _unique_sec_rows_by_symbol(sec_manifest.get("securities", []))
    built = [item for item in sec_by_symbol.values()
             if item.get("status") == "SEC_TIMELINE_BUILT"]
    offline_identities: dict[str, Mapping[str, str]] = {}
    offline_cache: dict[str, Mapping[str, object]] = {}
    for item in built:
        payload_hash = str(item.get("payloadContentHash", "")).upper()
        payload = json.loads(
            (controlled_root / str(item["storageReference"])).read_text(encoding="utf-8"))
        if canonical_hash(payload) != payload_hash:
            raise PilotError("OFFLINE216_PAYLOAD_HASH_MISMATCH")
        symbol = str(item["symbol"]).upper()
        issuer_id = str(payload.get("entityId", ""))
        security_id = f"SEC:{issuer_id}:{symbol}"
        identity = {"securityId": security_id, "issuerId": issuer_id,
                    "listingId": f"US_LISTING:{symbol}", "symbol": symbol,
                    "secPayloadHash": payload_hash}
        if not issuer_id or security_id in offline_identities:
            raise PilotError("OFFLINE216_DURABLE_IDENTITY_DUPLICATE_OR_MISSING")
        offline_identities[security_id] = identity
        offline_cache[security_id] = payload
    if len(offline_identities) != 216:
        raise PilotError("OFFLINE216_EXACT_CARDINALITY_REQUIRED")
    offline216 = _run_coverage_phase(
        "OFFLINE216", tuple(sorted(offline_identities)),
        offline_identities, offline_cache, dates)
    phase_summaries.append(offline216)
    controlled100 = next(item for item in phase_summaries
                         if item["phase"] == "CONTROLLED100")
    controlled100_minimum = min(
        row["companyQualityTargetCounts"].get("VALID", 0)
        for row in controlled100["matrix"])
    offline216_minimum = min(
        row["companyQualityTargetCounts"].get("VALID", 0)
        for row in offline216["matrix"])
    replay216 = {
        "state": ("PASSED_MINIMUM_COVERAGE" if offline216_minimum >= 100
                  else "STOPPED_BELOW_MINIMUM_COVERAGE"),
        "builtTimelineCount": len(offline_identities),
        "minimumRequiredUsablePerDate": 100,
        "controlled100MinimumUsablePerDate": controlled100_minimum,
        "offline216MinimumUsablePerDate": offline216_minimum,
        "reason": "Final coverage threshold is evaluated only after OFFLINE216.",
        "authorizedPhases": authorized_final,
    }
    approximation = [{"decisionDate": item.isoformat(), "securityCount": 100,
        "usableCount": 0, "state": "NOT_RUN",
        "reason": "CURRENT_REVISION_APPROXIMATION_PRODUCER_NOT_IMPLEMENTED"}
        for item in dates]
    body: dict[str, object] = {
        "schemaVersion": PILOT_VERSION, "outcomesRead": False,
        "networkRequests": 0, "databaseRequests": 0,
        "intersectionContentHash": intersection["contentHash"],
        "producerRegistry": [asdict(item) for item in
                             build_company_quality_producer_registry().values()],
        "calendarHash": canonical_hash([item.isoformat() for item in session_dates]),
        "decisionDates": [item.isoformat() for item in dates],
        "strictPitPhases": phase_summaries,
        "currentRevisionApproximation": approximation,
        "offline216Replay": replay216,
        "otherTargets": {
            "SECURITY_ATTRACTIVENESS_MARGIN_OF_SAFETY": "BLOCKED_VALUATION_POLICY",
            "EXPECTED_RETURN": "BLOCKED_VALUATION_POLICY",
            "DOWNSIDE_RISK": "BLOCKED_POLICY_RISK_EVIDENCE",
        },
        "parentCoverageAudit": {
            "depreciation_and_amortization": "PARENT_COVERAGE_UNPROVEN",
            "cash_dividends_paid": "PARENT_COVERAGE_UNPROVEN",
            "share_repurchases": "PARENT_COVERAGE_UNPROVEN",
        },
        "claimCeiling": "DEVELOPMENT_OBSERVED_TARGET_COMPONENT_ONLY",
    }
    body["contentHash"] = canonical_hash(body)
    return body


def compact_pilot_artifact(result: Mapping[str, object]) -> dict[str, object]:
    phases = []
    for phase in result["strictPitPhases"]:
        phases.append({
            "phase": phase["phase"],
            "securityCount": len(phase["securityIds"]),
            "securitySetHash": canonical_hash(sorted(phase["securityIds"])),
            "matrix": phase["matrix"],
            "contentHash": phase["contentHash"],
        })
    body: dict[str, object] = {
        "schemaVersion": result["schemaVersion"],
        "outcomesRead": result["outcomesRead"],
        "networkRequests": result["networkRequests"],
        "databaseRequests": result["databaseRequests"],
        "intersectionContentHash": result["intersectionContentHash"],
        "producerRegistryHashes": {
            item["producer_code"]: item["content_hash"]
            for item in result["producerRegistry"]
        },
        "calendarHash": result["calendarHash"],
        "decisionDates": result["decisionDates"],
        "strictPitPhases": phases,
        "currentRevisionApproximation": result["currentRevisionApproximation"],
        "offline216Replay": result["offline216Replay"],
        "otherTargets": result["otherTargets"],
        "parentCoverageAudit": result["parentCoverageAudit"],
        "claimCeiling": result["claimCeiling"],
        "fullInMemoryResultHash": result["contentHash"],
    }
    body["contentHash"] = canonical_hash(body)
    return body
