import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.provider_validation.models import SecFilingSummary
from equity_analysis.provider_validation.sec_edgar import (
    SecEdgarError,
    availability_after_full_trading_session,
    select_point_in_time_facts,
    select_point_in_time_facts_with_diagnostics,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sec_pit_facts_v1.json"


def _fixture() -> tuple[dict, tuple[SecFilingSummary, ...], tuple[date, ...]]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    filings = tuple(SecFilingSummary.model_validate(item) for item in payload["filings"])
    trading_dates = tuple(date.fromisoformat(item) for item in payload["tradingDates"])
    return payload["companyFacts"], filings, trading_dates


def test_availability_requires_a_complete_trading_session() -> None:
    trading_dates = (date(2025, 5, 1), date(2025, 5, 2))

    assert availability_after_full_trading_session(
        datetime.fromisoformat("2025-05-01T08:00:00-04:00"),
        trading_dates,
    ) == datetime.fromisoformat("2025-05-01T20:00:00+00:00")
    assert availability_after_full_trading_session(
        datetime.fromisoformat("2025-05-01T17:30:00-04:00"),
        trading_dates,
    ) == datetime.fromisoformat("2025-05-02T20:00:00+00:00")


def test_point_in_time_selection_does_not_leak_later_amendment() -> None:
    company_facts, filings, trading_dates = _fixture()

    before_amendment = select_point_in_time_facts(
        company_facts,
        filings,
        trading_dates,
        datetime.fromisoformat("2025-05-03T00:00:00+00:00"),
    )
    after_amendment = select_point_in_time_facts(
        company_facts,
        filings,
        trading_dates,
        datetime.fromisoformat("2025-06-03T00:00:00+00:00"),
    )

    assert len(before_amendment) == 1
    assert before_amendment[0].value == Decimal("100")
    assert before_amendment[0].available_at == datetime.fromisoformat("2025-05-02T20:00:00+00:00")
    assert len(after_amendment) == 1
    assert after_amendment[0].value == Decimal("110")
    assert after_amendment[0].accession_number == "0000000001-25-000002"


def test_selection_rejects_naive_cutoff_and_missing_future_session() -> None:
    company_facts, filings, trading_dates = _fixture()

    with pytest.raises(ValueError, match="timezone"):
        select_point_in_time_facts(
            company_facts,
            filings,
            trading_dates,
            datetime(2025, 5, 3),
        )

    with pytest.raises(SecEdgarError, match="No complete trading session"):
        availability_after_full_trading_session(
            datetime.fromisoformat("2025-06-04T17:30:00-04:00"),
            trading_dates,
        )


def test_selection_ignores_filings_accepted_after_cutoff() -> None:
    company_facts, filings, _ = _fixture()

    selected = select_point_in_time_facts(
        company_facts,
        filings,
        (date(2025, 5, 1), date(2025, 5, 2)),
        datetime.fromisoformat("2025-05-03T00:00:00+00:00"),
    )

    assert len(selected) == 1
    assert selected[0].value == Decimal("100")


def test_selection_excludes_filing_without_post_acceptance_session_but_keeps_older_fact() -> None:
    company_facts, filings, _trading_dates = _fixture()

    result = select_point_in_time_facts_with_diagnostics(
        company_facts,
        filings,
        (date(2025, 5, 1), date(2025, 5, 2)),
        datetime.fromisoformat("2025-06-03T00:00:00+00:00"),
    )

    assert len(result.facts) == 1
    assert result.facts[0].value == Decimal("100")
    assert result.facts[0].accession_number == "0000000001-25-000001"
    assert len(result.availability_exclusions) == 1
    exclusion = result.availability_exclusions[0]
    assert exclusion.accession_number == "0000000001-25-000002"
    assert exclusion.form == "10-Q/A"
    assert exclusion.acceptance_timestamp == datetime.fromisoformat(
        "2025-06-02T08:00:00-04:00"
    )
    assert exclusion.latest_trading_date == date(2025, 5, 2)
    assert exclusion.reason_code == (
        "SEC_NO_COMPLETE_TRADING_SESSION_AFTER_ACCEPTANCE"
    )


def test_selection_returns_no_fact_when_every_filing_lacks_post_acceptance_session() -> None:
    company_facts, filings, _trading_dates = _fixture()

    result = select_point_in_time_facts_with_diagnostics(
        company_facts,
        filings,
        (date(2025, 5, 1),),
        datetime.fromisoformat("2025-06-03T00:00:00+00:00"),
    )

    assert result.facts == ()
    assert {
        item.accession_number for item in result.availability_exclusions
    } == {
        "0000000001-25-000001",
        "0000000001-25-000002",
    }
