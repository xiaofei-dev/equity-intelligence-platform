from datetime import date, datetime, time
from decimal import Decimal

from equity_analysis.forward_validation.engine import (
    maximum_adverse_excursion,
    maximum_drawdown,
    net_total_return,
    q,
)
from equity_analysis.forward_validation.models import (
    LedgerSnapshot,
    MarketDay,
    NearTermLabel,
    ObservationMetrics,
    ObservationStatus,
    ShadowArm,
    ShadowFill,
    ShadowLedgerResult,
)

ZERO = Decimal("0")
ONE = Decimal("1")
BUY_COST_RATE = Decimal("0.001")
BUY_SLIPPAGE_RATE = Decimal("0.001")
EXIT_COST_RATE = Decimal("0.002")
TRANCHE_FRACTION = Decimal("0.25")
HORIZONS = (5, 20, 60)


def _validate_pit(day: MarketDay) -> None:
    cutoff = datetime.combine(day.trading_date, time.max, tzinfo=day.price_available_at.tzinfo)
    if day.price_available_at > cutoff:
        raise ValueError("Price was not available by its trading-date cutoff")
    if day.cash_rate_available_at is None or day.cash_rate_available_at > cutoff:
        raise ValueError("Cash rate was not PIT-available by the trading-date cutoff")
    if day.close_price is None or day.close_price <= ZERO:
        raise ValueError("A positive close price is required")
    if day.cash_annual_rate is None or day.cash_annual_rate < ZERO:
        raise ValueError("A non-negative cash rate is required")
    if day.split_ratio <= ZERO:
        raise ValueError("Split ratio must be positive")
    if day.dividend_ex_per_share < ZERO:
        raise ValueError("Dividend per share must be non-negative")
    if day.dividend_ex_per_share > ZERO and day.dividend_payment_date is None:
        raise ValueError("A dividend payment date is required")


def _scheduled_fraction(arm: ShadowArm, index: int, label: NearTermLabel) -> Decimal:
    if arm in (ShadowArm.A_LUMP_SUM, ShadowArm.E_SECTOR_ETF, ShadowArm.E_SPY):
        return ONE if index == 0 else ZERO
    if arm == ShadowArm.B_FIXED_FOUR_TRANCHE:
        return TRANCHE_FRACTION if index in (0, 5, 10, 15) else ZERO
    if arm == ShadowArm.C_STATE_GATED_FOUR_TRANCHE:
        return TRANCHE_FRACTION if index % 5 == 0 and label == NearTermLabel.FAVORABLE else ZERO
    return ZERO


def simulate_shadow_ledger(
    arm: ShadowArm,
    market_days: tuple[MarketDay, ...],
    *,
    initial_budget: Decimal = Decimal("10000"),
) -> ShadowLedgerResult:
    if initial_budget <= ZERO:
        raise ValueError("Initial budget must be positive")
    if not market_days:
        raise ValueError("At least one market day is required")
    if len({day.trading_date for day in market_days}) != len(market_days):
        raise ValueError("Trading dates must be unique")
    if tuple(sorted(day.trading_date for day in market_days)) != tuple(
        day.trading_date for day in market_days
    ):
        raise ValueError("Market days must be chronological")

    cash = initial_budget
    shares = ZERO
    pending_dividends: list[tuple[date, Decimal]] = []
    fills: list[ShadowFill] = []
    snapshots: list[LedgerSnapshot] = []
    observations: list[ObservationMetrics] = []
    marked_position_returns: list[Decimal] = []
    termination_reason: str | None = None
    prior_date = market_days[0].trading_date

    for index, day in enumerate(market_days):
        _validate_pit(day)
        actual_days = (day.trading_date - prior_date).days if index else 0
        cash = q(cash * ((ONE + day.cash_annual_rate / Decimal("365")) ** actual_days))
        prior_date = day.trading_date

        shares = q(shares * day.split_ratio)
        paid = sum(
            (
                amount
                for payment_date, amount in pending_dividends
                if payment_date <= day.trading_date
            ),
            ZERO,
        )
        cash = q(cash + paid)
        pending_dividends = [
            (payment_date, amount)
            for payment_date, amount in pending_dividends
            if payment_date > day.trading_date
        ]
        if day.dividend_ex_per_share > ZERO and shares > ZERO:
            pending_dividends.append(
                (day.dividend_payment_date, q(shares * day.dividend_ex_per_share))
            )

        if not day.tradable:
            termination_reason = "Security is not safely tradable"
        fraction = (
            ZERO
            if termination_reason
            else _scheduled_fraction(arm, index, day.near_term_label_prior_close)
        )
        if arm == ShadowArm.C_STATE_GATED_FOUR_TRANCHE and len(fills) >= 4:
            fraction = ZERO
        if fraction > ZERO:
            tranche_cash = q(initial_budget * fraction)
            available = min(cash, tranche_cash)
            gross = q(available / (ONE + BUY_COST_RATE + BUY_SLIPPAGE_RATE))
            transaction_cost = q(gross * BUY_COST_RATE)
            slippage_cost = q(gross * BUY_SLIPPAGE_RATE)
            acquired = q(gross / day.close_price)
            cash = q(cash - gross - transaction_cost - slippage_cost)
            shares = q(shares + acquired)
            fills.append(
                ShadowFill(
                    arm=arm,
                    tranche_number=len(fills) + 1,
                    trading_date=day.trading_date,
                    close_price=day.close_price,
                    shares=acquired,
                    gross_value=gross,
                    transaction_cost=transaction_cost,
                    slippage_cost=slippage_cost,
                )
            )

        receivable = sum((amount for _, amount in pending_dividends), ZERO)
        securities = q(shares * day.close_price)
        total = q(securities + cash + receivable)
        snapshots.append(
            LedgerSnapshot(
                arm=arm,
                trading_date=day.trading_date,
                shares=shares,
                cash=cash,
                dividend_receivable=receivable,
                securities_value=securities,
                total_value=total,
            )
        )
        if shares > ZERO:
            invested_cost = sum(
                (fill.gross_value + fill.transaction_cost + fill.slippage_cost for fill in fills),
                ZERO,
            )
            marked_position_returns.append(q((securities - invested_cost) / invested_cost))

        completed_days = index + 1
        if completed_days in HORIZONS:
            liquidation_value = q(securities * (ONE - EXIT_COST_RATE))
            observations.append(
                ObservationMetrics(
                    status=ObservationStatus.COMPLETE,
                    horizon_trading_days=completed_days,
                    net_total_return=net_total_return(
                        liquidation_value, cash, receivable, initial_budget
                    ),
                    cash_return=q(
                        (cash - max(ZERO, initial_budget - invested_cost)) / initial_budget
                    )
                    if fills
                    else q((cash - initial_budget) / initial_budget),
                    maximum_adverse_excursion=maximum_adverse_excursion(
                        tuple(marked_position_returns)
                    )
                    if marked_position_returns
                    else ZERO,
                    maximum_drawdown=maximum_drawdown(
                        tuple(snapshot.total_value for snapshot in snapshots)
                    ),
                )
            )

    matured = {observation.horizon_trading_days for observation in observations}
    observations.extend(
        ObservationMetrics(
            status=ObservationStatus.NOT_MATURED,
            horizon_trading_days=horizon,
        )
        for horizon in HORIZONS
        if horizon not in matured
    )
    status = (
        ObservationStatus.INSUFFICIENT_DATA if termination_reason else ObservationStatus.COMPLETE
    )
    return ShadowLedgerResult(
        arm=arm,
        status=status,
        fills=tuple(fills),
        snapshots=tuple(snapshots),
        observations=tuple(sorted(observations, key=lambda item: item.horizon_trading_days)),
        uninvested_cash=cash,
        termination_reason=termination_reason,
    )
