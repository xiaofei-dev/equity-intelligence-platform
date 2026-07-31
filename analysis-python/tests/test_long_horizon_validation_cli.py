import json
from datetime import date, timedelta
from decimal import Decimal

from equity_analysis.historical_validation.long_horizon_replay_v1 import (
    AnnualFactRecord,
    AnnualMetric,
)
from equity_analysis.historical_validation.long_horizon_validation_cli import (
    _build_slices,
    _controlled_slice_payload,
    _fact_contract_allowed,
    _maximum_close_drawdown,
    _price_evidence_hash,
)
from equity_analysis.historical_validation.sampling_v1 import (
    HistoricalAgeBand,
    HistoricalSamplePoint,
)
from equity_analysis.tactical.signal_v2 import TacticalBar


def _fact(
    metric: AnnualMetric,
    value: str,
    period_end: date,
    character: str,
) -> AnnualFactRecord:
    return AnnualFactRecord(
        metric=metric,
        value=Decimal(value),
        period_end=period_end,
        current_revision_evidence_hash=f"sha256:{character * 64}",
    )


def _facts() -> tuple[AnnualFactRecord, ...]:
    prior = date(2017, 12, 31)
    current = date(2018, 12, 31)
    return (
        _fact(AnnualMetric.REVENUE, "100", prior, "a"),
        _fact(AnnualMetric.NET_INCOME, "10", prior, "b"),
        _fact(AnnualMetric.REVENUE, "110", current, "c"),
        _fact(AnnualMetric.OPERATING_INCOME, "20", current, "d"),
        _fact(AnnualMetric.NET_INCOME, "12", current, "e"),
        _fact(AnnualMetric.TOTAL_EQUITY, "60", current, "f"),
        _fact(AnnualMetric.TOTAL_DEBT, "20", current, "1"),
        _fact(AnnualMetric.SHARES_OUTSTANDING, "2", current, "2"),
        _fact(AnnualMetric.CASH_AND_EQUIVALENTS, "5", current, "3"),
        _fact(AnnualMetric.EBITDA, "25", current, "4"),
    )


def _bars() -> tuple[TacticalBar, ...]:
    start = date(2020, 1, 2)
    return tuple(
        TacticalBar(
            trading_date=start + timedelta(days=index),
            open_price=100.0 + index,
            high_price=101.0 + index,
            low_price=99.0 + index,
            close_price=100.5 + index,
            volume=1_000,
        )
        for index in range(254)
    )


def test_fixed_universe_denominator_retains_missing_fact_security() -> None:
    bars = _bars()
    sample = HistoricalSamplePoint(
        sample_id="TEST-OLDER",
        age_band=HistoricalAgeBand.OLDER,
        decision_date=bars[0].trading_date,
        session_index=0,
        matured_horizons=(126, 252),
    )

    slices = _build_slices(
        (sample,),
        bars_by_symbol={"SPY": bars, "AAA": bars, "BBB": bars},
        public_ids={"AAA": "security-aaa"},
        facts_by_symbol={"AAA": _facts()},
        universe_version="universe-v1",
    )

    assert slices[0].eligible_universe_count == 2
    assert [item.symbol for item in slices[0].signals] == ["AAA"]
    assert slices[0].signals[0].membership_available_at == (
        slices[0].decision_time
    )


def test_controlled_slice_payload_is_json_and_hash_safe() -> None:
    bars = _bars()
    sample = HistoricalSamplePoint(
        sample_id="TEST-MEDIUM",
        age_band=HistoricalAgeBand.MEDIUM,
        decision_date=bars[0].trading_date,
        session_index=0,
        matured_horizons=(126, 252),
    )
    item = _build_slices(
        (sample,),
        bars_by_symbol={"SPY": bars, "AAA": bars},
        public_ids={"AAA": "security-aaa"},
        facts_by_symbol={"AAA": _facts()},
        universe_version="universe-v1",
    )[0]

    encoded = json.dumps(_controlled_slice_payload(item), sort_keys=True)

    assert json.loads(encoded)["signals"][0]["score"]
    assert "2020-01-02" in encoded


def test_price_hash_binds_raw_and_adjusted_price_bases() -> None:
    first = _price_evidence_hash(
        symbol="AAA",
        trading_date=date(2020, 1, 2),
        adjusted_close=50.0,
        raw_close=100.0,
        adjustment_factor=0.5,
    )
    changed = _price_evidence_hash(
        symbol="AAA",
        trading_date=date(2020, 1, 2),
        adjusted_close=50.0,
        raw_close=101.0,
        adjustment_factor=0.5,
    )

    assert first != changed


def test_maximum_drawdown_uses_running_close_peak_not_entry_mae() -> None:
    result = _maximum_close_drawdown(
        entry_price=100.0,
        close_prices=(120.0, 108.0, 115.0),
    )

    assert result == Decimal("-0.1")


def test_fact_contract_rejects_bad_units_currency_and_quality() -> None:
    assert _fact_contract_allowed(
        metric=AnnualMetric.REVENUE,
        unit="USD",
        currency="USD",
        quality_status="NOT_VERIFIED",
    )
    assert _fact_contract_allowed(
        metric=AnnualMetric.SHARES_OUTSTANDING,
        unit="shares",
        currency=None,
        quality_status="PROVISIONAL",
    )
    assert not _fact_contract_allowed(
        metric=AnnualMetric.REVENUE,
        unit="EUR",
        currency="EUR",
        quality_status="VALIDATED",
    )
    assert not _fact_contract_allowed(
        metric=AnnualMetric.REVENUE,
        unit="USD",
        currency="USD",
        quality_status="REJECTED",
    )
