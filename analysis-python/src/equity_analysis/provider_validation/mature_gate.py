import json
import os
import sys
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import Field

from equity_analysis.provider_validation.models import (
    GateStatus,
    HistoricalMarketValueObservation,
    MatureGateReport,
    MatureGateSecurityResult,
    NormalizedFinancialObservation,
    PitPeriodDiagnostic,
    ProviderRequestMetric,
    RequiredFieldDiagnostic,
    SecFactObservation,
    SecFilingSummary,
    ValidationModel,
)
from equity_analysis.provider_validation.sec_edgar import select_point_in_time_facts

REPORT_VERSION = "mature-company-data-gate-v1.0.0"
MINIMUM_MARKET_CAP = Decimal("500000000")
MINIMUM_ANNUAL_PERIODS = 3
MINIMUM_QUARTERLY_PERIODS = 8
EODHD_WEIGHTED_CALL_CEILING = 3500
EODHD_REQUEST_CEILING = 1122
TARGET_QUALIFIED_COMPANIES = 100
MAXIMUM_NETWORK_RERUN_SAMPLE = 5
OBSERVED_TWO_PASS_PROVIDER_CALLS = 50
OBSERVED_ONE_PASS_PROVIDER_CALLS = 25
BILLING_SAFETY_MULTIPLIER = Decimal("1.5")
LIVE_ENDPOINTS = (
    "fundamentals",
    "eod",
    "dividends",
    "splits",
    "historical_market_cap",
    "sec_ticker_mapping",
    "sec_submissions",
    "sec_company_facts",
)

REQUIRED_NORMALIZED_FIELDS = frozenset(
    {
        "revenue",
        "operating_income",
        "net_income",
        "income_tax",
        "pretax_income",
        "total_assets",
        "total_liabilities",
        "stockholders_equity",
        "cash_and_equivalents",
        "total_debt",
        "operating_cash_flow",
        "capital_expenditure",
        "shares_outstanding",
    }
)


class CandidateRole(StrEnum):
    PRIMARY = "PRIMARY"
    RESERVE = "RESERVE"


class MatureGateCandidate(ValidationModel):
    symbol: str
    sector: str
    candidate_role: CandidateRole
    selection_reason: str
    expected_company_type: str = "MATURE_OPERATING_COMPANY"
    cik: str | None = None


class MatureGateUniverse(ValidationModel):
    universe_version: str
    candidates: tuple[MatureGateCandidate, ...] = Field(min_length=120, max_length=120)

    def validate_composition(self) -> None:
        symbols = [item.symbol.upper() for item in self.candidates]
        if len(set(symbols)) != len(symbols):
            raise ValueError("Mature gate symbols must be unique")
        roles = Counter(item.candidate_role for item in self.candidates)
        if roles[CandidateRole.PRIMARY] != 100 or roles[CandidateRole.RESERVE] != 20:
            raise ValueError("Mature gate requires exactly 100 primary and 20 reserve candidates")
        if any(
            item.expected_company_type != "MATURE_OPERATING_COMPANY"
            for item in self.candidates
        ):
            raise ValueError("Every mature gate candidate must use the general-company model")


class EodhdCallBudget:
    def __init__(
        self,
        weighted_call_ceiling: int = EODHD_WEIGHTED_CALL_CEILING,
        request_ceiling: int = EODHD_REQUEST_CEILING,
    ) -> None:
        self._weighted_call_ceiling = weighted_call_ceiling
        self._request_ceiling = request_ceiling
        self._metrics: list[ProviderRequestMetric] = []

    @property
    def metrics(self) -> tuple[ProviderRequestMetric, ...]:
        return tuple(self._metrics)

    @property
    def weighted_calls(self) -> int:
        return sum(item.weighted_calls for item in self._metrics)

    @property
    def requests(self) -> int:
        return len(self._metrics)

    def reserve(self, weighted_calls: int) -> None:
        if self.requests + 1 > self._request_ceiling:
            raise RuntimeError("EODHD_REQUEST_BUDGET_EXHAUSTED")
        if self.weighted_calls + weighted_calls > self._weighted_call_ceiling:
            raise RuntimeError("EODHD_WEIGHTED_CALL_BUDGET_EXHAUSTED")

    def record(self, metric: ProviderRequestMetric) -> None:
        self.reserve(metric.weighted_calls)
        self._metrics.append(metric)


class GateEvidenceLedger:
    """Deterministic acceptance-run ledger used before database persistence."""

    def __init__(self) -> None:
        self._hashes_by_identity: dict[str, list[str]] = {}

    def record(self, source_identity: str, content_hash: str) -> tuple[str, int]:
        if not source_identity or len(content_hash) != 64:
            raise ValueError("Gate evidence requires a source identity and SHA-256 hash")
        revisions = self._hashes_by_identity.setdefault(source_identity, [])
        if content_hash in revisions:
            return "UNCHANGED", revisions.index(content_hash) + 1
        revisions.append(content_hash)
        return ("INSERTED" if len(revisions) == 1 else "REVISED"), len(revisions)


class MatureGateRunLock:
    def __init__(self, path: Path, run_id: str) -> None:
        self._path = path
        self._run_id = run_id
        self._handle = None

    def __enter__(self) -> "MatureGateRunLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            handle.close()
            raise RuntimeError("MATURE_GATE_ALREADY_RUNNING") from None
        handle.seek(0)
        handle.truncate()
        handle.write((self._run_id + "\n").encode("utf-8"))
        handle.flush()
        self._handle = handle
        return self

    def __exit__(self, *_args) -> None:
        if self._handle is None:
            return
        self._handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


def projected_live_cost(symbol_count: int, rerun_count: int | None = None) -> dict[str, int | str]:
    if symbol_count < 1:
        raise ValueError("Symbol count must be positive")
    reruns = min(symbol_count, MAXIMUM_NETWORK_RERUN_SAMPLE) if rerun_count is None else rerun_count
    if not 0 <= reruns <= min(symbol_count, MAXIMUM_NETWORK_RERUN_SAMPLE):
        raise ValueError("Rerun count must be between zero and five")
    eodhd_initial_requests = symbol_count * 5
    eodhd_rerun_requests = reruns * 5
    sec_requests = symbol_count * 3
    configured_weighted_calls = symbol_count * 14 + reruns * 14
    provisional_provider_calls = (
        symbol_count * OBSERVED_ONE_PASS_PROVIDER_CALLS
        + reruns * OBSERVED_ONE_PASS_PROVIDER_CALLS
    )
    safety_budget = int(
        (
            Decimal(provisional_provider_calls) * BILLING_SAFETY_MULTIPLIER
        ).to_integral_value(rounding="ROUND_CEILING")
    )
    return {
        "symbols": symbol_count,
        "networkRerunSample": reruns,
        "eodhdHttpRequests": eodhd_initial_requests + eodhd_rerun_requests,
        "secHttpRequests": sec_requests,
        "totalHttpRequests": eodhd_initial_requests + eodhd_rerun_requests + sec_requests,
        "configuredLocalWeightedCalls": configured_weighted_calls,
        "observedProvisionalProviderCalls": provisional_provider_calls,
        "billingSafetyMultiplier": str(BILLING_SAFETY_MULTIPLIER),
        "billingSafetyBudget": safety_budget,
        "providerBillingReconciliation": "NOT_RECONCILED",
        "requiredEodhdHttpAttempts": (
            eodhd_initial_requests + eodhd_rerun_requests
        ),
        "eodhdAttemptCeiling": min(
            EODHD_REQUEST_CEILING,
            eodhd_initial_requests + eodhd_rerun_requests,
        ),
        "weightedEodhdCallCeiling": min(
            EODHD_WEIGHTED_CALL_CEILING,
            configured_weighted_calls,
        ),
        "executableWithinCurrentHardCeilings": (
            eodhd_initial_requests + eodhd_rerun_requests
            <= EODHD_REQUEST_CEILING
            and configured_weighted_calls <= EODHD_WEIGHTED_CALL_CEILING
        ),
    }


def plan_reproducibility(
    symbols: tuple[str, ...],
    network_sample_size: int,
) -> dict[str, str]:
    if not 0 <= network_sample_size <= MAXIMUM_NETWORK_RERUN_SAMPLE:
        raise ValueError("Network rerun sample size must be between zero and five")
    if len(set(symbols)) != len(symbols):
        raise ValueError("Reproducibility symbols must be unique")
    return {
        symbol: (
            "NETWORK_RERUN"
            if index < network_sample_size
            else "IMMUTABLE_PAYLOAD_REPLAY"
        )
        for index, symbol in enumerate(symbols)
    }


def market_cap_band(value: Decimal | None) -> str | None:
    if value is None or value < MINIMUM_MARKET_CAP:
        return None
    if value >= Decimal("200000000000"):
        return "MEGA"
    if value >= Decimal("10000000000"):
        return "LARGE"
    if value >= Decimal("2000000000"):
        return "MID"
    return "SMALL"


def attach_sec_availability(
    observations: tuple[NormalizedFinancialObservation, ...],
    filing_available_at: dict[date, datetime],
) -> tuple[NormalizedFinancialObservation, ...]:
    attached = []
    for observation in observations:
        available_at = filing_available_at.get(observation.fiscal_period_end)
        if available_at is None and filing_available_at:
            nearest_period = min(
                filing_available_at,
                key=lambda item: abs((item - observation.fiscal_period_end).days),
            )
            if abs((nearest_period - observation.fiscal_period_end).days) <= 7:
                available_at = filing_available_at[nearest_period]
        attached.append(observation.model_copy(update={"available_at": available_at}))
    return tuple(attached)


def sec_availability_by_period(
    company_facts_payload: dict[str, Any],
    filings: tuple[SecFilingSummary, ...],
    trading_dates: tuple[date, ...],
    as_of_time: datetime,
) -> dict[date, datetime]:
    facts = select_point_in_time_facts(
        company_facts_payload,
        filings,
        trading_dates,
        as_of_time,
    )
    grouped: dict[date, list] = {}
    for fact in facts:
        grouped.setdefault(fact.period_end, []).append(fact)
    return {
        period_end: max(item.available_at for item in period_facts)
        for period_end, period_facts in grouped.items()
    }


def required_statement_window(
    financials: tuple[NormalizedFinancialObservation, ...],
) -> tuple[NormalizedFinancialObservation, ...]:
    required_window: list[NormalizedFinancialObservation] = []
    for statement_type in {item.statement_type for item in financials}:
        for period_type, minimum_periods in (
            ("ANNUAL", MINIMUM_ANNUAL_PERIODS),
            ("QUARTERLY", MINIMUM_QUARTERLY_PERIODS),
        ):
            candidates = sorted(
                (
                    item
                    for item in financials
                    if item.statement_type == statement_type
                    and item.period_type == period_type
                ),
                key=lambda item: item.fiscal_period_end,
                reverse=True,
            )
            required_window.extend(candidates[:minimum_periods])
    return tuple(required_window)


def required_field_diagnostic(
    financials: tuple[NormalizedFinancialObservation, ...],
) -> RequiredFieldDiagnostic:
    present_fields = {
        field
        for item in financials
        for field, value in item.values.items()
        if value is not None
    }
    return RequiredFieldDiagnostic(
        required_normalized_fields=tuple(sorted(REQUIRED_NORMALIZED_FIELDS)),
        present_normalized_fields=tuple(sorted(present_fields)),
        missing_normalized_fields=tuple(
            sorted(REQUIRED_NORMALIZED_FIELDS - present_fields)
        ),
    )


def pit_period_diagnostics(
    financials: tuple[NormalizedFinancialObservation, ...],
    facts: tuple[SecFactObservation, ...],
) -> tuple[PitPeriodDiagnostic, ...]:
    candidates_by_period: dict[date, list[SecFactObservation]] = {}
    for fact in facts:
        candidates_by_period.setdefault(fact.period_end, []).append(fact)
    candidate_periods = tuple(sorted(candidates_by_period))
    diagnostics: list[PitPeriodDiagnostic] = []
    for observation in required_statement_window(financials):
        exact_period = (
            observation.fiscal_period_end
            if observation.fiscal_period_end in candidates_by_period
            else None
        )
        nearest_period = (
            min(
                candidate_periods,
                key=lambda item: abs((item - observation.fiscal_period_end).days),
            )
            if candidate_periods
            else None
        )
        day_difference = (
            abs((nearest_period - observation.fiscal_period_end).days)
            if nearest_period is not None
            else None
        )
        selected_period = exact_period or nearest_period
        selected_fact = (
            max(
                candidates_by_period[selected_period],
                key=lambda item: item.available_at,
            )
            if selected_period is not None
            else None
        )
        if exact_period is not None:
            status = "EXACT"
            mismatch_reason = None
        elif day_difference is not None and day_difference <= 7:
            status = "WITHIN_SEVEN_DAYS"
            mismatch_reason = None
        elif nearest_period is not None:
            status = "OUTSIDE_SEVEN_DAYS"
            mismatch_reason = (
                "SEC_PERIOD_NOT_YET_AVAILABLE_AS_OF"
                if observation.fiscal_period_end > max(candidate_periods)
                else "SEC_PERIOD_OUTSIDE_SEVEN_DAY_TOLERANCE"
            )
        else:
            status = "NO_PERIOD_CANDIDATE"
            mismatch_reason = "SEC_NO_PERIOD_CANDIDATE"
        diagnostics.append(
            PitPeriodDiagnostic(
                statement_type=observation.statement_type,
                period_type=observation.period_type,
                provider_fiscal_period_end=observation.fiscal_period_end,
                exact_sec_period=exact_period,
                nearest_sec_candidate_period=nearest_period,
                absolute_day_difference=day_difference,
                sec_form=selected_fact.form if selected_fact else None,
                acceptance_timestamp=(
                    selected_fact.acceptance_datetime if selected_fact else None
                ),
                accession_number=(
                    selected_fact.accession_number if selected_fact else None
                ),
                match_status=status,
                mismatch_reason=mismatch_reason,
            )
        )
    return tuple(diagnostics)


def evaluate_candidate(
    candidate: MatureGateCandidate,
    financials: tuple[NormalizedFinancialObservation, ...],
    market_values: tuple[HistoricalMarketValueObservation, ...],
    domain_coverage: dict[str, bool],
) -> MatureGateSecurityResult:
    annual_periods = {
        item.fiscal_period_end for item in financials if item.period_type == "ANNUAL"
    }
    quarterly_periods = {
        item.fiscal_period_end for item in financials if item.period_type == "QUARTERLY"
    }
    present_fields = {
        field
        for item in financials
        for field, value in item.values.items()
        if value is not None
    }
    latest_market_cap = (
        max(market_values, key=lambda item: item.effective_at).market_capitalization
        if market_values
        else None
    )
    required_window = required_statement_window(financials)
    field_coverage = {
        **domain_coverage,
        "annualFinancials": len(annual_periods) >= MINIMUM_ANNUAL_PERIODS,
        "quarterlyFinancials": len(quarterly_periods) >= MINIMUM_QUARTERLY_PERIODS,
        "pitAvailability": bool(required_window)
        and all(item.available_at is not None for item in required_window),
        "requiredRatingFields": REQUIRED_NORMALIZED_FIELDS <= present_fields,
        "historicalMarketValue": bool(market_values),
        "lineage": bool(financials)
        and all(
            bool(item.source_reference)
            and len(item.content_hash) == 64
            and bool(item.provider_schema_version)
            and bool(item.parser_version)
            for item in financials
        ),
    }
    reason_codes = [
        f"MISSING_{name.upper()}" for name, covered in field_coverage.items() if not covered
    ]
    if latest_market_cap is None or latest_market_cap < MINIMUM_MARKET_CAP:
        reason_codes.append("MARKET_CAP_BELOW_THRESHOLD_OR_MISSING")
    if not reason_codes:
        status = GateStatus.PASS
    elif financials or market_values:
        status = GateStatus.PARTIAL
    else:
        status = GateStatus.FAIL
    return MatureGateSecurityResult(
        symbol=candidate.symbol,
        sector=candidate.sector,
        candidate_role=candidate.candidate_role,
        status=status,
        reason_codes=tuple(reason_codes),
        field_coverage=field_coverage,
        market_capitalization=latest_market_cap,
        market_cap_band=market_cap_band(latest_market_cap),
    )


def normalized_payload_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def build_report(
    universe: MatureGateUniverse,
    results: tuple[MatureGateSecurityResult, ...],
    request_metrics: tuple[ProviderRequestMetric, ...],
    clock: datetime | None = None,
    started_at: datetime | None = None,
    run_id: str = "UNASSIGNED",
    observed_provider_dashboard_before: int | None = None,
    observed_provider_dashboard_delta: int | None = None,
) -> MatureGateReport:
    completed_at = clock or datetime.now(UTC)
    started = started_at or completed_at
    scoreable_count = sum(item.status == GateStatus.PASS for item in results)
    gate = (
        GateStatus.PASS
        if scoreable_count >= TARGET_QUALIFIED_COMPANIES
        else GateStatus.FAIL
    )
    return MatureGateReport(
        report_version=REPORT_VERSION,
        run_id=run_id,
        generated_at=completed_at,
        started_at=started,
        completed_at=completed_at,
        duration_seconds=Decimal(str((completed_at - started).total_seconds())),
        universe_version=universe.universe_version,
        results=results,
        request_metrics=request_metrics,
        physical_http_attempt_count=len(request_metrics),
        configured_local_weighted_calls=sum(
            item.weighted_calls
            for item in request_metrics
            if item.provider == "eodhd"
        ),
        observed_provider_dashboard_before=observed_provider_dashboard_before,
        observed_provider_dashboard_delta=observed_provider_dashboard_delta,
        provider_billing_reconciliation="NOT_RECONCILED",
        scoreable_candidate_count=scoreable_count,
        qualified_company_gate=gate,
        conclusion=(
            "At least 100 companies satisfy the mature-company data gate."
            if gate == GateStatus.PASS
            else "Fewer than 100 companies satisfy the mature-company data gate; "
            "thresholds were not relaxed."
        ),
    )
