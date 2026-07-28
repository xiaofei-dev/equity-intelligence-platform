import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from equity_analysis.provider_validation.models import SecFilingSummary
from equity_analysis.provider_validation.sec_edgar import (
    SEC_CONCEPT_MAPPING_VERSION,
    select_point_in_time_facts,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sec_formula_concepts_v1.json"


def _evidence():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return (
        payload["companyFacts"],
        tuple(SecFilingSummary.model_validate(item) for item in payload["filings"]),
        tuple(date.fromisoformat(item) for item in payload["tradingDates"]),
    )


def test_concept_priority_beats_later_lower_priority_alias() -> None:
    facts, filings, trading_dates = _evidence()

    selected = select_point_in_time_facts(
        facts,
        filings,
        trading_dates,
        datetime.fromisoformat("2025-06-01T00:00:00+00:00"),
    )
    interest = next(item for item in selected if item.metric_code == "interest_expense")

    assert interest.taxonomy_tag == "InterestExpenseNonOperating"
    assert interest.value == Decimal("10")
    assert interest.concept_priority == 0
    assert interest.semantic_classification == "DURATION_GROSS_INTEREST_EXPENSE"


def test_same_concept_revision_wins_without_future_filing_leakage() -> None:
    facts, filings, trading_dates = _evidence()

    before_amendment = select_point_in_time_facts(
        facts,
        filings,
        trading_dates,
        datetime.fromisoformat("2025-05-03T00:00:00+00:00"),
    )
    after_amendment = select_point_in_time_facts(
        facts,
        filings,
        trading_dates,
        datetime.fromisoformat("2025-06-01T00:00:00+00:00"),
    )

    assert next(
        item.value for item in before_amendment if item.metric_code == "diluted_shares"
    ) == Decimal("100")
    revised = next(
        item for item in after_amendment if item.metric_code == "diluted_shares"
    )
    assert revised.value == Decimal("101")
    assert revised.form == "10-Q/A"
    assert revised.accession_number == "0000000001-25-000002"
    assert all(item.period_end != date(2025, 6, 30) for item in after_amendment)


def test_evidence_carries_units_pit_accession_mapping_version_and_source_hash() -> None:
    facts, filings, trading_dates = _evidence()
    selected = select_point_in_time_facts(
        facts,
        filings,
        trading_dates,
        datetime.fromisoformat("2025-06-01T00:00:00+00:00"),
    )
    diluted = next(item for item in selected if item.metric_code == "diluted_shares")

    assert diluted.unit == "shares"
    assert diluted.period_start == date(2025, 1, 1)
    assert diluted.period_end == date(2025, 3, 31)
    assert diluted.acceptance_datetime < diluted.available_at
    assert diluted.concept_mapping_version == SEC_CONCEPT_MAPPING_VERSION
    assert diluted.source_content_hash is not None
    assert len(diluted.source_content_hash) == 64
    assert diluted.semantic_classification == (
        "DURATION_WEIGHTED_AVERAGE_DILUTED_SHARES"
    )


def test_wrong_units_and_missing_concepts_remain_missing() -> None:
    facts, filings, trading_dates = _evidence()
    facts["facts"]["us-gaap"].pop("InterestExpenseNonOperating")
    facts["facts"]["us-gaap"].pop("InterestExpense")
    facts["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"][
        "units"
    ].pop("shares")

    selected = select_point_in_time_facts(
        facts,
        filings,
        trading_dates,
        datetime.fromisoformat("2025-06-01T00:00:00+00:00"),
    )

    assert selected == ()


def test_ytd_duration_is_preserved_and_not_implicitly_quarterized() -> None:
    facts, filings, trading_dates = _evidence()

    selected = select_point_in_time_facts(
        facts,
        filings,
        trading_dates,
        datetime.fromisoformat("2025-08-06T00:00:00+00:00"),
    )
    ytd = next(
        item
        for item in selected
        if item.metric_code == "diluted_shares"
        and item.period_end == date(2025, 6, 30)
    )

    assert ytd.period_start == date(2025, 1, 1)
    assert ytd.value == Decimal("102")
