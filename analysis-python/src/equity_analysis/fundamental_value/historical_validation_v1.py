from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

CONTRACT_VERSION = "FUNDAMENTAL-VALUE-HISTORICAL-VALIDATION-v1.1.0"
UNIVERSE_SEED = "FV-STAGE7-UNIVERSE-20260731-v1"
DATE_SEED = "FV-STAGE7-DATES-20260731-v1"
GICS_SECTORS = (
    "Communication Services", "Consumer Discretionary", "Consumer Staples",
    "Energy", "Financials", "Health Care", "Industrials",
    "Information Technology", "Materials", "Real Estate", "Utilities",
)
STRESS_DATES = (
    (date(2018, 9, 20), "2018_ADVERSE_ENTRY"),
    (date(2020, 2, 19), "2020_ADVERSE_ENTRY"),
    (date(2022, 1, 3), "2022_ADVERSE_ENTRY"),
)
HORIZONS = (1, 2, 3)


class HistoricalValidationError(ValueError):
    """Raised when a Stage 7 frozen validation contract fails closed."""


class UniverseRole(StrEnum):
    PRIMARY = "PRIMARY"
    RESERVE = "RESERVE"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"
    EXCLUDED = "EXCLUDED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CapitalizationBucket(StrEnum):
    LARGE = "LARGE"
    MID = "MID"
    SMALL = "SMALL"


class LifecycleState(StrEnum):
    ACTIVE = "ACTIVE"
    DELISTED = "DELISTED"
    ACQUIRED = "ACQUIRED"
    FAILED = "FAILED"


class DateRole(StrEnum):
    PRIMARY_RANDOM = "PRIMARY_RANDOM"
    STRESS_DIAGNOSTIC = "STRESS_DIAGNOSTIC"


class EvidenceAvailability(StrEnum):
    STRICT_PIT = "STRICT_PIT"
    CURRENT_REVISION_APPROXIMATION = "CURRENT_REVISION_APPROXIMATION"


class SectorBenchmarkQuality(StrEnum):
    DATED_CLASSIFICATION_PROVEN = "DATED_CLASSIFICATION_PROVEN"
    CURRENT_CLASSIFICATION_APPROXIMATION = "CURRENT_CLASSIFICATION_APPROXIMATION"
    MISSING = "MISSING"


class PredictorTarget(StrEnum):
    COMPANY_QUALITY = "COMPANY_QUALITY"
    SECURITY_ATTRACTIVENESS_MARGIN_OF_SAFETY = "SECURITY_ATTRACTIVENESS_MARGIN_OF_SAFETY"
    EXPECTED_RETURN = "EXPECTED_RETURN"
    DOWNSIDE_RISK = "DOWNSIDE_RISK"


class RatingGroup(StrEnum):
    HIGH = "HIGH"
    MIDDLE = "MIDDLE"
    LOW = "LOW"


class TerminalState(StrEnum):
    USABLE_VALID = "USABLE_VALID"
    MISSING = "MISSING"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"
    INVALID = "INVALID"
    EXCLUDED = "EXCLUDED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class UniverseCandidate:
    security_id: str
    issuer_id: str
    listing_id: str
    symbol: str
    sector: str
    capitalization_bucket: CapitalizationBucket
    capitalization_observed_at: datetime
    classification_effective_at: datetime
    classification_available_at: datetime
    classification_ingested_at: datetime
    lifecycle_state: LifecycleState
    role: UniverseRole
    source_ordinal: int
    source_snapshot_id: str
    source_snapshot_hash: str
    is_curated: bool


@dataclass(frozen=True)
class DecisionDate:
    decision_date: date
    role: DateRole
    stratum: str


@dataclass(frozen=True)
class PredictorContract:
    contract_id: str
    model_version: str
    target: PredictorTarget
    mapping_version: str | None
    mapping_content_hash: str
    source_output_definition: str
    eligibility_definition: str
    higher_is_better: bool
    source_field_path: str
    formula_version: str
    assumption_version: str
    projection_years: int
    aggregation_version: str = ""
    binary_condition_paths: tuple[str, ...] = ()
    accepted_by_master: bool = False
    uses_risk_cap: bool = False
    outcome_informed: bool = False


@dataclass(frozen=True)
class OutcomePolicy:
    policy_version: str
    completed_session_calendar_hash: str
    outcome_cutoff: date
    entry_session_offset: int
    exit_session_offsets: tuple[int, int, int]
    entry_price_convention: str
    exit_price_convention: str
    dividend_treatment: str
    split_treatment: str
    acquisition_delisting_cashout_policy: str | None
    sector_mapping_version: str
    currency_policy: str
    transaction_cost_policy: str | None
    missing_liquidity_policy: str
    descriptive_only: bool = True
    iid_inference_allowed: bool = False


@dataclass(frozen=True)
class AcceptanceThresholds:
    policy_version: str = "FV-STAGE7-MARKET-FIRST-THRESHOLDS-v1.0.0"
    minimum_complete_random_dates: int = 7
    minimum_usable_assessments_per_date: int = 100
    minimum_top_bottom_count: int = 20
    minimum_spy_outcome_coverage: Decimal = Decimal("0.90")
    minimum_rank_ic_median: Decimal = Decimal("0.05")
    minimum_positive_rank_ic_dates: int = 6
    minimum_top_bottom_annualized_spread: Decimal = Decimal("0.02")
    minimum_top_spy_annualized_excess: Decimal = Decimal("0.01")
    minimum_top_spy_win_dates: int = 6
    minimum_leave_one_out_spy_excess: Decimal = Decimal("0")
    maximum_top_mdd_deterioration: Decimal = Decimal("0.05")
    minimum_expected_return_interval_coverage: Decimal = Decimal("0.40")
    maximum_expected_return_annualized_error: Decimal = Decimal("0.10")
    stress_veto_node_count: int = 2
    stress_veto_annualized_underperformance: Decimal = Decimal("0.10")
    stress_veto_mdd_deterioration: Decimal = Decimal("0.10")


@dataclass(frozen=True)
class HorizonOutcome:
    horizon_years: int
    security_total_return: Decimal | None
    spy_total_return: Decimal | None
    sector_total_return: Decimal | None
    maximum_drawdown: Decimal | None = None
    spy_maximum_drawdown: Decimal | None = None
    downside_capture: Decimal | None = None
    severe_loss: bool | None = None
    expected_return_interval_contains_realized: bool | None = None
    expected_annualized_return_error: Decimal | None = None
    business_quality_maintained: bool | None = None


@dataclass(frozen=True)
class HistoricalObservation:
    security_id: str
    decision_date: date
    target: PredictorTarget
    group: RatingGroup
    outcomes: tuple[HorizonOutcome, ...]
    evidence_availability: EvidenceAvailability
    sector_benchmark_quality: SectorBenchmarkQuality
    predictor_contract_id: str
    predictor_content_hash: str
    model_version: str
    formula_version: str
    assumption_version: str
    mapping_version: str
    predictor_value: Decimal
    higher_is_better: bool
    deterministic_rank: int
    binary_investable_conditions: tuple[tuple[str, bool], ...] = ()


@dataclass(frozen=True)
class TerminalCoverageRecord:
    security_id: str
    decision_date: date
    target: PredictorTarget
    state: TerminalState
    outcome_available: bool


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest().upper()


def _require_hash(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789ABCDEF" for character in value):
        raise HistoricalValidationError(f"INVALID_{label}_HASH")


def _validate_candidate(candidate: UniverseCandidate) -> None:
    values = (candidate.security_id, candidate.issuer_id, candidate.listing_id, candidate.symbol)
    if any(not value or value != value.strip() for value in values):
        raise HistoricalValidationError("DURABLE_IDENTITIES_AND_SYMBOL_REQUIRED")
    if candidate.sector not in GICS_SECTORS or candidate.source_ordinal < 1:
        raise HistoricalValidationError("VALID_SECTOR_AND_SOURCE_ORDINAL_REQUIRED")
    _require_hash(candidate.source_snapshot_hash, "SOURCE_SNAPSHOT")
    if not candidate.source_snapshot_id:
        raise HistoricalValidationError("SOURCE_SNAPSHOT_ID_REQUIRED")
    if not (
        candidate.classification_effective_at
        <= candidate.classification_available_at
        <= candidate.classification_ingested_at
    ):
        raise HistoricalValidationError("CLASSIFICATION_CHRONOLOGY_INVALID")


def _casefold_unique(values: Sequence[str], error: str) -> None:
    folded = [value.casefold() for value in values]
    if len(folded) != len(set(folded)):
        raise HistoricalValidationError(error)


def freeze_universe(
    curated: Sequence[UniverseCandidate],
    random_pool: Sequence[UniverseCandidate],
    *,
    seed: str = UNIVERSE_SEED,
) -> dict[str, object]:
    if len(curated) != 200 or any(not item.is_curated for item in curated):
        raise HistoricalValidationError("CURATED_UNIVERSE_MUST_CONTAIN_EXACTLY_200")
    all_candidates = (*curated, *random_pool)
    for item in all_candidates:
        _validate_candidate(item)
    _casefold_unique([item.security_id for item in all_candidates], "DUPLICATE_SECURITY_ID")
    _casefold_unique([item.listing_id for item in all_candidates], "DUPLICATE_LISTING_ID")
    snapshots = {(item.source_snapshot_id, item.source_snapshot_hash) for item in all_candidates}
    if len(snapshots) != 1:
        raise HistoricalValidationError("SOURCE_SNAPSHOT_CONSISTENCY_REQUIRED")
    ordinals = [item.source_ordinal for item in all_candidates]
    if len(ordinals) != len(set(ordinals)):
        raise HistoricalValidationError("DUPLICATE_SOURCE_ORDINAL")
    curated_ids = {item.security_id.casefold() for item in curated}
    eligible = [
        item for item in random_pool
        if not item.is_curated and item.security_id.casefold() not in curated_ids
        and item.role not in {UniverseRole.EXCLUDED, UniverseRole.REFERENCE_ONLY}
    ]
    targets = {CapitalizationBucket.LARGE: 3, CapitalizationBucket.MID: 4,
               CapitalizationBucket.SMALL: 3}
    selected: list[UniverseCandidate] = []
    snapshot_hash = next(iter(snapshots))[1]
    for sector in GICS_SECTORS:
        for bucket, count in targets.items():
            candidates = [item for item in eligible if item.sector == sector
                          and item.capitalization_bucket == bucket]
            ranked = sorted(
                candidates,
                key=lambda item: (
                    hashlib.sha256(
                        f"{seed}|{snapshot_hash}|{sector}|{bucket}|{item.security_id}".encode()
                    ).hexdigest(),
                    item.security_id,
                ),
            )
            if len(ranked) < count:
                raise HistoricalValidationError(f"INSUFFICIENT_RANDOM_POOL[{sector}:{bucket}]")
            selected.extend(ranked[:count])
    securities = (*curated, *selected)
    if len(securities) != 310:
        raise HistoricalValidationError("FROZEN_UNIVERSE_MUST_CONTAIN_310_SECURITIES")
    body: dict[str, object] = {
        "contractVersion": CONTRACT_VERSION, "seed": seed,
        "realManifestClaimed": False, "curatedCount": 200,
        "additionalRandomCount": 110, "securities": [asdict(item) for item in securities],
    }
    body["contentHash"] = canonical_hash(body)
    return body


def freeze_decision_dates(
    completed_us_sessions: Iterable[date], *, calendar_hash: str,
    outcome_cutoff: date, seed: str = DATE_SEED
) -> dict[str, object]:
    _require_hash(calendar_hash, "CALENDAR")
    sessions_list = list(completed_us_sessions)
    if len(sessions_list) != len(set(sessions_list)):
        raise HistoricalValidationError("DUPLICATE_COMPLETED_SESSION")
    sessions = sorted(sessions_list)
    if calendar_hash != canonical_hash([item.isoformat() for item in sessions]):
        raise HistoricalValidationError("COMPLETED_SESSION_CALENDAR_HASH_MISMATCH")
    by_year: dict[int, list[date]] = defaultdict(list)
    for session in sessions:
        if 2015 <= session.year <= 2023 and 4 <= session.month <= 6:
            by_year[session.year].append(session)
    primary: list[DecisionDate] = []
    stress_set = {item[0] for item in STRESS_DATES}
    for year in range(2015, 2024):
        candidates = [item for item in by_year[year] if item not in stress_set]
        if not candidates:
            raise HistoricalValidationError(f"NO_COMPLETED_SESSION_FOR_YEAR[{year}]")
        chosen = min(candidates, key=lambda item: hashlib.sha256(
            f"{seed}|{calendar_hash}|{year}|{item.isoformat()}".encode()).hexdigest())
        primary.append(DecisionDate(chosen, DateRole.PRIMARY_RANDOM, str(year)))
    if not stress_set <= set(sessions):
        raise HistoricalValidationError("PREDECLARED_STRESS_DATE_NOT_COMPLETED")
    stress = [DecisionDate(value, DateRole.STRESS_DIAGNOSTIC, label)
              for value, label in STRESS_DATES]
    dates = (*primary, *stress)
    if len({item.decision_date for item in dates}) != 12:
        raise HistoricalValidationError("PRIMARY_STRESS_DATE_COLLISION")
    latest_primary = max(item.decision_date for item in primary)
    after_latest = [item for item in sessions if item > latest_primary and item <= outcome_cutoff]
    if len(after_latest) < 757:
        raise HistoricalValidationError("OUTCOME_CUTOFF_CANNOT_MATURE_2023_NODE")
    body: dict[str, object] = {"contractVersion": CONTRACT_VERSION,
        "seed": seed, "calendarHash": calendar_hash,
        "outcomeCutoff": outcome_cutoff,
        "primaryEstimateDateCount": 9, "stressDiagnosticDateCount": 3,
        "dates": [asdict(item) for item in dates]}
    body["contentHash"] = canonical_hash(body)
    return body


def validate_predictor_contract(contract: PredictorContract) -> None:
    if not contract.contract_id or not contract.model_version:
        raise HistoricalValidationError("PREDICTOR_ID_AND_MODEL_VERSION_REQUIRED")
    if contract.uses_risk_cap or contract.outcome_informed:
        raise HistoricalValidationError("CIRCULAR_OR_OUTCOME_INFORMED_PREDICTOR_FORBIDDEN")
    if not contract.accepted_by_master or not contract.mapping_version:
        raise HistoricalValidationError("PREDICTOR_MAPPING_REQUIRES_MASTER_ACCEPTANCE")
    _require_hash(contract.mapping_content_hash, "PREDICTOR_MAPPING_CONTENT")
    if not contract.source_output_definition or not contract.eligibility_definition:
        raise HistoricalValidationError("PREDICTOR_SOURCE_AND_ELIGIBILITY_REQUIRED")
    if type(contract.higher_is_better) is not bool:
        raise HistoricalValidationError("PREDICTOR_DIRECTION_REQUIRED")
    expected_hash = canonical_hash({
        "target": contract.target,
        "modelVersion": contract.model_version,
        "formulaVersion": contract.formula_version,
        "assumptionVersion": contract.assumption_version,
        "aggregationVersion": contract.aggregation_version,
        "projectionYears": contract.projection_years,
        "mappingVersion": contract.mapping_version,
        "sourceFieldPath": contract.source_field_path,
        "sourceOutputDefinition": contract.source_output_definition,
        "eligibilityDefinition": contract.eligibility_definition,
        "higherIsBetter": contract.higher_is_better,
        "binaryConditionPaths": contract.binary_condition_paths,
    })
    if contract.mapping_content_hash != expected_hash:
        raise HistoricalValidationError("PREDICTOR_MAPPING_CONTENT_HASH_MISMATCH")
    if (contract.projection_years != 3 or not contract.source_field_path
            or not contract.aggregation_version
            or any(not value for value in contract.binary_condition_paths)):
        raise HistoricalValidationError("PREDICTOR_PROJECTION_OR_PATH_INVALID")


def validate_outcome_policy(policy: OutcomePolicy, latest_decision_date: date) -> None:
    _require_hash(policy.completed_session_calendar_hash, "CALENDAR")
    if policy.exit_session_offsets != (252, 504, 756) or policy.entry_session_offset != 1:
        raise HistoricalValidationError("OUTCOME_SESSION_OFFSETS_NOT_FROZEN")
    required = (policy.entry_price_convention, policy.exit_price_convention,
                policy.dividend_treatment, policy.split_treatment,
                policy.sector_mapping_version, policy.currency_policy)
    if any(not value for value in required):
        raise HistoricalValidationError("OUTCOME_POLICY_FIELD_REQUIRED")
    if policy.acquisition_delisting_cashout_policy is None:
        raise HistoricalValidationError("ACQUISITION_DELISTING_POLICY_BLOCKED")
    if policy.transaction_cost_policy is None or policy.missing_liquidity_policy == "ZERO_COST":
        raise HistoricalValidationError("TRANSACTION_COST_OR_LIQUIDITY_POLICY_BLOCKED")
    if policy.outcome_cutoff <= latest_decision_date:
        raise HistoricalValidationError("OUTCOME_CUTOFF_CANNOT_MATURE_HORIZONS")
    if not policy.descriptive_only or policy.iid_inference_allowed:
        raise HistoricalValidationError("OVERLAPPING_WINDOWS_MUST_REMAIN_DESCRIPTIVE")


def resolve_outcome_sessions(
    completed_sessions: Sequence[date], decision_date: date, *, outcome_cutoff: date
) -> tuple[date, date, date, date]:
    if list(completed_sessions) != sorted(set(completed_sessions)):
        raise HistoricalValidationError("COMPLETED_SESSION_CALENDAR_NOT_SORTED_UNIQUE")
    later = [session for session in completed_sessions if session > decision_date]
    if len(later) < 757 or later[756] > outcome_cutoff:
        raise HistoricalValidationError("OUTCOME_SESSIONS_NOT_MATURE")
    entry = later[0]
    return entry, later[252], later[504], later[756]


def annualize_total_return(total_return: Decimal, years: int) -> Decimal:
    if not total_return.is_finite() or total_return < Decimal("-1") or years not in HORIZONS:
        raise HistoricalValidationError("INVALID_TOTAL_RETURN_OR_HORIZON")
    if total_return == Decimal("-1"):
        return Decimal("-1")
    try:
        result = (Decimal(1) + total_return) ** (Decimal(1) / years) - Decimal(1)
        if not result.is_finite():
            raise HistoricalValidationError("ANNUALIZATION_NONFINITE_RESULT")
        return result
    except ArithmeticError as error:
        raise HistoricalValidationError("ANNUALIZATION_ARITHMETIC_FAILED") from error


def assign_target_quintiles(
    values: Mapping[str, Decimal], *, higher_is_better: bool
) -> dict[str, RatingGroup]:
    if len(values) < 100:
        raise HistoricalValidationError("MINIMUM_100_ELIGIBLE_VALUES_REQUIRED")
    ordered = sorted(
        values,
        key=lambda security_id: (
            -values[security_id] if higher_is_better else values[security_id],
            security_id,
        ),
    )
    top = len(ordered) // 5
    bottom_start = len(ordered) - top
    return {
        security_id: (
            RatingGroup.HIGH if index < top
            else RatingGroup.LOW if index >= bottom_start
            else RatingGroup.MIDDLE
        )
        for index, security_id in enumerate(ordered)
    }


def build_batch_schedule(
    securities: Sequence[UniverseCandidate], benchmark_symbols: Sequence[str]
) -> tuple[dict[str, object], ...]:
    if len(securities) != 310:
        raise HistoricalValidationError("BATCH_SCOPE_REQUIRES_310_SECURITIES")
    _casefold_unique([item.security_id for item in securities], "DUPLICATE_SECURITY_ID")
    if len(benchmark_symbols) != 12 or any(not item for item in benchmark_symbols):
        raise HistoricalValidationError("TWELVE_NONEMPTY_BENCHMARKS_REQUIRED")
    _casefold_unique(list(benchmark_symbols), "DUPLICATE_BENCHMARK_SYMBOL")
    canary_by_sector: dict[str, UniverseCandidate] = {}
    for item in securities:
        canary_by_sector.setdefault(item.sector, item)
    if set(canary_by_sector) != set(GICS_SECTORS):
        raise HistoricalValidationError("ELEVEN_SECTOR_CANARIES_REQUIRED")
    canaries = [canary_by_sector[sector] for sector in GICS_SECTORS]
    batches: list[dict[str, object]] = [{"batchId": "BATCH-000-CANARY",
        "benchmarkSymbols": list(benchmark_symbols),
        "securityIds": [item.security_id for item in canaries],
        "securityCount": 11, "retryLimit": 0}]
    remaining = [item for item in securities if item not in canaries]
    for offset in range(0, len(remaining), 25):
        chunk = remaining[offset:offset + 25]
        membership_canary = canaries[len(batches) - 1:len(batches)]
        batches.append({"batchId": f"BATCH-{len(batches):03d}",
            "benchmarkSymbols": [], "securityIds": [item.security_id for item in chunk],
            "securityCount": len(chunk), "retryLimit": 0,
            "checkpointReuseSecurityIds": [item.security_id for item in membership_canary]})
    reused = {item for batch in batches[1:] for item in batch["checkpointReuseSecurityIds"]}
    if reused != {item.security_id for item in canaries} or [batch["securityCount"]
            for batch in batches[1:]] != [25] * 11 + [24]:
        raise HistoricalValidationError("CANARY_MEMBERSHIP_REUSE_INCOMPLETE")
    return tuple(batches)


def aggregate_date_portfolios(
    observations: Sequence[HistoricalObservation], decision_dates: Sequence[date],
    *, availability: EvidenceAvailability,
    accepted_predictors: Mapping[PredictorTarget, PredictorContract],
    expected_security_ids: Sequence[str],
    terminal_coverage: Sequence[TerminalCoverageRecord],
) -> dict[str, object]:
    date_set = set(decision_dates)
    if len(date_set) not in {3, 9}:
        raise HistoricalValidationError("PRIMARY_OR_STRESS_DATE_SET_REQUIRED")
    if any(item.decision_date not in date_set for item in observations):
        raise HistoricalValidationError("PRIMARY_AND_STRESS_MUST_REMAIN_SEPARATE")
    if any(item.evidence_availability != availability for item in observations):
        raise HistoricalValidationError("PIT_AND_APPROXIMATION_STRATA_MUST_REMAIN_SEPARATE")
    if set(accepted_predictors) != set(PredictorTarget) or any(
        key != contract.target for key, contract in accepted_predictors.items()
    ):
        raise HistoricalValidationError("EXACT_FOUR_TARGET_PREDICTOR_REGISTRY_REQUIRED")
    if len(expected_security_ids) != 310 or len(set(expected_security_ids)) != 310:
        raise HistoricalValidationError("EXPECTED_SECURITY_MANIFEST_MUST_HAVE_310_UNIQUE_IDS")
    expected_ids = set(expected_security_ids)
    terminal_keys: set[tuple[str, date, PredictorTarget]] = set()
    coverage_by_pair: dict[
        tuple[date, PredictorTarget], list[TerminalCoverageRecord]
    ] = defaultdict(list)
    for record in terminal_coverage:
        if type(record.outcome_available) is not bool:
            raise HistoricalValidationError("TERMINAL_OUTCOME_AVAILABLE_MUST_BE_BOOL")
        if type(record.state) is not TerminalState or type(record.target) is not PredictorTarget:
            raise HistoricalValidationError("EXACT_TERMINAL_ENUM_TYPES_REQUIRED")
        key = (record.security_id, record.decision_date, record.target)
        if key in terminal_keys:
            raise HistoricalValidationError("DUPLICATE_TERMINAL_COVERAGE_IDENTITY")
        terminal_keys.add(key)
        if record.security_id not in expected_ids or record.decision_date not in date_set:
            raise HistoricalValidationError("TERMINAL_COVERAGE_EXTRA_IDENTITY")
        coverage_by_pair[(record.decision_date, record.target)].append(record)
    expected_terminal_keys = {(security_id, decision_date, target)
        for security_id in expected_ids for decision_date in date_set
        for target in PredictorTarget}
    if terminal_keys != expected_terminal_keys:
        raise HistoricalValidationError("TERMINAL_COVERAGE_SILENT_POPULATION_SHRINK")
    grouped: dict[
        tuple[date, PredictorTarget, RatingGroup], list[HistoricalObservation]
    ] = defaultdict(list)
    identities: set[tuple[str, date, PredictorTarget]] = set()
    predictor_bindings: dict[PredictorTarget, tuple[str, ...]] = {}
    by_date_target: dict[
        tuple[date, PredictorTarget], list[HistoricalObservation]
    ] = defaultdict(list)
    for item in observations:
        if item.security_id not in expected_ids:
            raise HistoricalValidationError("OBSERVATION_SECURITY_NOT_IN_MANIFEST")
        if type(item.target) is not PredictorTarget or type(item.group) is not RatingGroup:
            raise HistoricalValidationError("EXACT_TARGET_AND_GROUP_ENUM_TYPES_REQUIRED")
        contract = accepted_predictors.get(item.target)
        if contract is None:
            raise HistoricalValidationError("ACCEPTED_PREDICTOR_CONTRACT_REQUIRED")
        validate_predictor_contract(contract)
        if (item.predictor_contract_id != contract.contract_id
                or item.predictor_content_hash != contract.mapping_content_hash
                or item.model_version != contract.model_version
                or item.mapping_version != contract.mapping_version):
            raise HistoricalValidationError("OBSERVATION_PREDICTOR_CONTRACT_MISMATCH")
        if item.higher_is_better != contract.higher_is_better:
            raise HistoricalValidationError("PREDICTOR_DIRECTION_DRIFT")
        if type(item.higher_is_better) is not bool or not item.predictor_value.is_finite():
            raise HistoricalValidationError("PREDICTOR_VALUE_OR_DIRECTION_INVALID")
        if type(item.sector_benchmark_quality) is not SectorBenchmarkQuality:
            raise HistoricalValidationError("EXACT_SECTOR_QUALITY_ENUM_REQUIRED")
        if any(
            (item.sector_benchmark_quality == SectorBenchmarkQuality.MISSING)
            != (outcome.sector_total_return is None)
            for outcome in item.outcomes
        ):
            raise HistoricalValidationError("SECTOR_RETURN_QUALITY_PARITY_INVALID")
        terminal = next(record for record in coverage_by_pair[(item.decision_date, item.target)]
                        if record.security_id == item.security_id)
        if terminal.state != TerminalState.USABLE_VALID or not terminal.outcome_available:
            raise HistoricalValidationError("OBSERVATION_NOT_BOUND_TO_USABLE_TERMINAL_ROW")
        identity = (item.security_id, item.decision_date, item.target)
        if identity in identities:
            raise HistoricalValidationError("DUPLICATE_SECURITY_DATE_TARGET")
        identities.add(identity)
        binding = (item.predictor_contract_id, item.predictor_content_hash,
                   item.model_version, item.formula_version, item.assumption_version,
                   item.mapping_version, str(item.higher_is_better))
        if item.target in predictor_bindings and predictor_bindings[item.target] != binding:
            raise HistoricalValidationError("MIXED_PREDICTOR_CONTRACT_OR_DIRECTION")
        predictor_bindings[item.target] = binding
        _require_hash(item.predictor_content_hash, "PREDICTOR_CONTENT")
        if item.deterministic_rank < 1:
            raise HistoricalValidationError("DETERMINISTIC_RANK_REQUIRED")
        horizon_ids = [outcome.horizon_years for outcome in item.outcomes]
        if len(horizon_ids) != 3 or set(horizon_ids) != set(HORIZONS):
            raise HistoricalValidationError("COMPLETE_ONE_TWO_THREE_YEAR_OUTCOMES_REQUIRED")
        if any(outcome.security_total_return is None or outcome.spy_total_return is None
               for outcome in item.outcomes):
            raise HistoricalValidationError("COMPLETE_SECURITY_AND_SPY_OUTCOMES_REQUIRED")
        for outcome in item.outcomes:
            returns = (outcome.security_total_return, outcome.spy_total_return,
                       outcome.sector_total_return)
            if any(value is not None and (not value.is_finite() or value < -1)
                   for value in returns):
                raise HistoricalValidationError("OUTCOME_RETURN_DOMAIN_INVALID")
            optional_decimals = (outcome.maximum_drawdown, outcome.spy_maximum_drawdown,
                outcome.downside_capture, outcome.expected_annualized_return_error)
            if any(value is not None and not value.is_finite() for value in optional_decimals):
                raise HistoricalValidationError("OPTIONAL_OUTCOME_NUMERIC_NONFINITE")
            if any(value is not None and not (Decimal("-1") <= value <= 0)
                   for value in (outcome.maximum_drawdown, outcome.spy_maximum_drawdown)):
                raise HistoricalValidationError("MAXIMUM_DRAWDOWN_DOMAIN_INVALID")
            if outcome.downside_capture is not None and outcome.downside_capture < 0:
                raise HistoricalValidationError("DOWNSIDE_CAPTURE_DOMAIN_INVALID")
            if (outcome.expected_annualized_return_error is not None
                    and outcome.expected_annualized_return_error < 0):
                raise HistoricalValidationError("EXPECTED_RETURN_ERROR_INVALID")
            if any(value is not None and type(value) is not bool for value in (
                outcome.severe_loss, outcome.expected_return_interval_contains_realized,
                outcome.business_quality_maintained)):
                raise HistoricalValidationError("OPTIONAL_OUTCOME_BOOLEAN_TYPE_INVALID")
        grouped[(item.decision_date, item.target, item.group)].append(item)
        by_date_target[(item.decision_date, item.target)].append(item)
    for records in by_date_target.values():
        values = {item.security_id: item.predictor_value for item in records}
        recomputed = assign_target_quintiles(
            values, higher_is_better=records[0].higher_is_better
        )
        ordered = sorted(values, key=lambda security_id: (
            -values[security_id] if records[0].higher_is_better else values[security_id],
            security_id,
        ))
        ranks = {security_id: index + 1 for index, security_id in enumerate(ordered)}
        if any(item.group != recomputed[item.security_id]
               or item.deterministic_rank != ranks[item.security_id] for item in records):
            raise HistoricalValidationError("SUPPLIED_RANK_OR_GROUP_MISMATCH")
    usable_terminal_keys = {(record.security_id, record.decision_date, record.target)
        for record in terminal_coverage
        if record.state == TerminalState.USABLE_VALID and record.outcome_available}
    if identities != usable_terminal_keys:
        raise HistoricalValidationError("USABLE_TERMINAL_OBSERVATION_BINDING_MISMATCH")
    expected_pairs = {(decision_date, target) for decision_date in date_set
                      for target in accepted_predictors}
    if set(by_date_target) != expected_pairs:
        raise HistoricalValidationError("DECLARED_DATE_TARGET_COVERAGE_INCOMPLETE")
    rows: list[dict[str, object]] = []
    for (decision_date, target, group), records in sorted(grouped.items(), key=str):
        horizons: list[dict[str, object]] = []
        for years in HORIZONS:
            values = [next(value for value in item.outcomes if value.horizon_years == years)
                      for item in records]
            total = sum((value.security_total_return for value in values), Decimal(0)) / len(values)
            spy = sum((value.spy_total_return for value in values), Decimal(0)) / len(values)
            annualized = annualize_total_return(total, years)
            sector_values = [value.sector_total_return for value in values
                             if value.sector_total_return is not None]
            matched_security_values = [value.security_total_return for value in values
                                       if value.sector_total_return is not None]
            sector = (sum(sector_values, Decimal(0)) / len(sector_values)
                      if sector_values else None)
            matched_security = (sum(matched_security_values, Decimal(0))
                                / len(matched_security_values)
                                if matched_security_values else None)
            spy_annualized = annualize_total_return(spy, years)
            sector_annualized = (
                annualize_total_return(sector, years) if sector is not None else None
            )
            matched_security_annualized = (annualize_total_return(matched_security, years)
                                           if matched_security is not None else None)
            severe = [value.severe_loss for value in values if value.severe_loss is not None]
            interval = [value.expected_return_interval_contains_realized for value in values
                        if value.expected_return_interval_contains_realized is not None]
            quality = [value.business_quality_maintained for value in values
                       if value.business_quality_maintained is not None]
            errors = [value.expected_annualized_return_error for value in values
                      if value.expected_annualized_return_error is not None]
            if any(not value.is_finite() or value < 0 for value in errors):
                raise HistoricalValidationError("EXPECTED_RETURN_ERROR_INVALID")
            sector_strata = []
            present_sector_qualities = {
                item.sector_benchmark_quality for item in records
                if item.sector_benchmark_quality != SectorBenchmarkQuality.MISSING
            }
            for quality_state in (
                SectorBenchmarkQuality.DATED_CLASSIFICATION_PROVEN,
                SectorBenchmarkQuality.CURRENT_CLASSIFICATION_APPROXIMATION,
            ):
                stratum_records = [item for item in records
                                   if item.sector_benchmark_quality == quality_state]
                stratum_values = [next(value for value in item.outcomes
                    if value.horizon_years == years) for item in stratum_records]
                if stratum_values:
                    stratum_security = sum((value.security_total_return
                        for value in stratum_values), Decimal(0)) / len(stratum_values)
                    stratum_sector = sum((value.sector_total_return
                        for value in stratum_values), Decimal(0)) / len(stratum_values)
                    sector_strata.append({"quality": quality_state,
                        "matchedCount": len(stratum_values),
                        "securityTotalReturn": str(stratum_security),
                        "sectorTotalReturn": str(stratum_sector)})
            horizons.append({"horizonYears": years, "eligibleCount": len(values),
                "totalReturn": str(total), "annualizedReturn": str(annualized),
                "spyExcessTotalReturn": str(total - spy),
                "spyAnnualizedReturn": str(spy_annualized),
                "spyAnnualizedExcess": str(annualized - spy_annualized),
                "labelEligible": years == 3,
                "sectorMatchedCount": len(sector_values),
                "sectorCoverage": str(Decimal(len(sector_values)) / len(values)),
                "sectorExcessTotalReturn": str(matched_security - sector)
                if sector is not None else None,
                "sectorAnnualizedExcess": str(matched_security_annualized - sector_annualized)
                if sector_annualized is not None else None,
                "combinedSectorDiagnosticOnly": len(present_sector_qualities) > 1,
                "combinedSectorThresholdEligible": present_sector_qualities
                == {SectorBenchmarkQuality.DATED_CLASSIFICATION_PROVEN},
                "portfolioMaximumDrawdown": None,
                "portfolioPathAcceptanceState": "BLOCKED_DAILY_PATH_REQUIRED",
                "severeLossObservedCount": len(severe),
                "severeLossCoverage": str(Decimal(len(severe)) / len(values)),
                "severeLossFrequency": str(Decimal(sum(severe)) / len(severe)) if severe else None,
                "expectedReturnIntervalObservedCount": len(interval),
                "expectedReturnIntervalObservationCoverage": str(
                    Decimal(len(interval)) / len(values)
                ),
                "expectedReturnIntervalCoverage": (
                    str(Decimal(sum(interval)) / len(interval)) if interval else None
                ),
                "businessQualityObservedCount": len(quality),
                "businessQualityObservationCoverage": str(
                    Decimal(len(quality)) / len(values)
                ),
                "businessQualityMaintenanceRate": (
                    str(Decimal(sum(quality)) / len(quality)) if quality else None
                ),
                "expectedReturnErrorObservedCount": len(errors),
                "expectedReturnErrorCoverage": str(Decimal(len(errors)) / len(values)),
                "medianAbsoluteAnnualizedError": str(statistics.median(errors))
                if errors else None,
                "sectorQualityStrata": sector_strata})
        rows.append({"decisionDate": decision_date.isoformat(), "target": target,
                     "group": group, "horizons": horizons})
    monotonicity: list[dict[str, object]] = []
    for decision_date in sorted(date_set):
        for target in PredictorTarget:
            target_rows = [
                item
                for item in rows
                if item["decisionDate"] == decision_date.isoformat()
                and item["target"] == target
            ]
            for years in HORIZONS:
                returns = {
                    item["group"]: Decimal(
                        next(
                            value["totalReturn"]
                            for value in item["horizons"]
                            if value["horizonYears"] == years
                        )
                    )
                    for item in target_rows
                }
                if set(returns) == set(RatingGroup):
                    monotonicity.append({"decisionDate": decision_date.isoformat(),
                        "target": target, "horizonYears": years,
                        "highMinusLow": str(returns[RatingGroup.HIGH] - returns[RatingGroup.LOW]),
                        "monotonic": returns[RatingGroup.HIGH] >= returns[RatingGroup.MIDDLE]
                        >= returns[RatingGroup.LOW]})
    coverage_rows = []
    for pair, records in sorted(coverage_by_pair.items(), key=str):
        usable = sum(record.state == TerminalState.USABLE_VALID for record in records)
        outcome = sum(record.outcome_available for record in records)
        coverage_rows.append({"decisionDate": pair[0].isoformat(), "target": pair[1],
            "totalCount": 310, "usableCount": usable, "outcomeCount": outcome,
            "usableCoverage": str(Decimal(usable) / 310),
            "outcomeCoverage": str(Decimal(outcome) / 310)})
    return {"contractVersion": CONTRACT_VERSION, "availabilityStratum": availability,
        "aggregationUnit": "DECISION_DATE_EQUAL_WEIGHT_PORTFOLIO",
        "descriptiveOnly": True, "iidBootstrapAllowed": False,
        "datePortfolioRows": rows, "monotonicityRows": monotonicity,
        "terminalCoverageRows": coverage_rows}


def summarize_date_level_primary(
    date_spy_excess: Mapping[date, Decimal],
    *,
    non_overlapping_dates: Sequence[date],
) -> dict[str, object]:
    if len(date_spy_excess) != 9:
        raise HistoricalValidationError("NINE_DATE_LEVEL_OBSERVATIONS_REQUIRED")
    if len(non_overlapping_dates) > 3 or not set(non_overlapping_dates) <= set(date_spy_excess):
        raise HistoricalValidationError("UP_TO_THREE_VALID_NON_OVERLAPPING_ANCHORS_REQUIRED")
    ordered = [date_spy_excess[item] for item in sorted(date_spy_excess)]
    leave_one_out = [
        Decimal(str(statistics.median(ordered[:index] + ordered[index + 1:])))
        for index in range(len(ordered))
    ]
    return {
        "medianSpyExcess": str(statistics.median(ordered)),
        "positiveDateCount": sum(value > 0 for value in ordered),
        "leaveOneDateOutMedianSpyExcess": [str(value) for value in leave_one_out],
        "nonOverlappingAnchorValues": [
            {"decisionDate": item.isoformat(), "spyExcess": str(date_spy_excess[item])}
            for item in non_overlapping_dates
        ],
        "descriptiveOnly": True,
    }
