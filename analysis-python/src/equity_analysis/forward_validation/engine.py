from decimal import ROUND_HALF_EVEN, Decimal

from equity_analysis.forward_validation.models import (
    DailyLedgerValue,
    EntryPolicyState,
    NearTermLabel,
    PolicyCheckpoint,
    PolicyDecision,
)

FOUR = Decimal("4")
ONE = Decimal("1")
ZERO = Decimal("0")
SCALE = Decimal("0.00000001")


def q(value: Decimal) -> Decimal:
    return value.quantize(SCALE, rounding=ROUND_HALF_EVEN)


def decide_state_gated_tranche(checkpoint: PolicyCheckpoint) -> PolicyDecision:
    if checkpoint.prior_tranches >= 4:
        return PolicyDecision(
            state=EntryPolicyState.FULLY_ALLOCATED,
            execute_tranche=False,
            reason="All four tranches were already executed",
        )
    if checkpoint.checkpoint_index >= 60:
        return PolicyDecision(
            state=EntryPolicyState.EXPIRED,
            execute_tranche=False,
            reason="The 60-trading-day entry window expired",
        )
    if not checkpoint.tradable:
        return PolicyDecision(
            state=EntryPolicyState.TERMINATED,
            execute_tranche=False,
            reason="The security is no longer safely tradable",
        )
    if checkpoint.near_term_label != NearTermLabel.FAVORABLE:
        return PolicyDecision(
            state=EntryPolicyState.PAUSE,
            execute_tranche=False,
            reason=f"Near-term state is {checkpoint.near_term_label}",
        )
    tranche_number = checkpoint.prior_tranches + 1
    states = (
        EntryPolicyState.FIRST_TRANCHE,
        EntryPolicyState.SECOND_TRANCHE,
        EntryPolicyState.THIRD_TRANCHE,
        EntryPolicyState.FOURTH_TRANCHE,
    )
    return PolicyDecision(
        state=states[tranche_number - 1],
        execute_tranche=True,
        tranche_number=tranche_number,
        allocation_fraction=q(ONE / FOUR),
        reason="FAVORABLE state permits the next fixed tranche",
    )


def net_total_return(
    ending_securities: Decimal,
    cash: Decimal,
    dividend_receivable: Decimal,
    initial_budget: Decimal,
) -> Decimal:
    if initial_budget <= ZERO:
        raise ValueError("Initial budget must be positive")
    return q((ending_securities + cash + dividend_receivable - initial_budget) / initial_budget)


def average_acquisition_price(
    gross_purchase_value: Decimal,
    buy_costs: Decimal,
    slippage: Decimal,
    acquired_shares: Decimal,
) -> Decimal:
    if acquired_shares <= ZERO:
        raise ValueError("Acquired shares must be positive")
    return q((gross_purchase_value + buy_costs + slippage) / acquired_shares)


def purchase_price_improvement(comparison_price: Decimal, policy_price: Decimal) -> Decimal:
    if comparison_price <= ZERO:
        raise ValueError("Comparison price must be positive")
    return q((comparison_price - policy_price) / comparison_price)


def missed_upside(
    hypothetical_fully_invested_ending_value: Decimal,
    actual_ending_value: Decimal,
    initial_budget: Decimal,
) -> Decimal:
    if initial_budget <= ZERO:
        raise ValueError("Initial budget must be positive")
    return q(
        max(ZERO, hypothetical_fully_invested_ending_value - actual_ending_value)
        / initial_budget
    )


def accrue_cash(
    principal: Decimal,
    annual_rate: Decimal,
    actual_days: int,
) -> Decimal:
    if principal < ZERO or annual_rate < ZERO or actual_days < 0:
        raise ValueError("Cash, annual rate, and actual days must be non-negative")
    daily_factor = ONE + annual_rate / Decimal("365")
    return q(principal * (daily_factor**actual_days))


def cash_drag(fully_invested_return: Decimal, mixed_cash_return: Decimal) -> Decimal:
    return q(fully_invested_return - mixed_cash_return)


def maximum_adverse_excursion(marked_returns: tuple[Decimal, ...]) -> Decimal:
    if not marked_returns:
        raise ValueError("At least one marked return is required")
    return q(min(ZERO, min(marked_returns)))


def maximum_drawdown(values: tuple[Decimal, ...]) -> Decimal:
    if not values or any(value <= ZERO for value in values):
        raise ValueError("Positive ledger values are required")
    peak = values[0]
    worst = ZERO
    for value in values:
        peak = max(peak, value)
        worst = min(worst, (value - peak) / peak)
    return q(worst)


def capture_ratio(
    rows: tuple[DailyLedgerValue, ...],
    *,
    upside: bool,
    minimum_days: int = 5,
) -> Decimal | None:
    selected = tuple(
        row
        for row in rows
        if (row.benchmark_return > ZERO if upside else row.benchmark_return < ZERO)
    )
    if len(selected) < minimum_days:
        return None
    denominator = sum((row.benchmark_return for row in selected), ZERO)
    if denominator == ZERO:
        return None
    numerator = sum((row.position_return for row in selected), ZERO)
    return q(numerator / denominator)


def relative_return(strategy_return: Decimal, benchmark_return: Decimal) -> Decimal:
    return q(strategy_return - benchmark_return)


def top_bottom_spread(
    top_returns: tuple[Decimal, ...],
    bottom_returns: tuple[Decimal, ...],
    *,
    minimum_group_size: int = 20,
) -> Decimal | None:
    if len(top_returns) < minimum_group_size or len(bottom_returns) < minimum_group_size:
        return None
    top_mean = sum(top_returns, ZERO) / Decimal(len(top_returns))
    bottom_mean = sum(bottom_returns, ZERO) / Decimal(len(bottom_returns))
    return q(top_mean - bottom_mean)
