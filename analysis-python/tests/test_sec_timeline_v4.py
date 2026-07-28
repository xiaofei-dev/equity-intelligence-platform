from datetime import UTC, date, datetime

import pytest

from equity_analysis.provider_validation.sec_timeline_v4 import (
    CONCEPT_RULES,
    MARKET_AVAILABILITY_POLICY_VERSION,
    SEC_CONCEPT_MAPPING_VERSION,
    SEC_FISCAL_Q4_DIFFERENCE_VERSION,
    SEC_YTD_DIFFERENCE_VERSION,
    classify_duration,
    derive_discrete_quarters,
    derive_ebitda,
    derive_fiscal_q4_difference,
    derive_fiscal_q4_quarters,
    derive_ytd_difference,
    next_session_open_available_at,
)


def _ytd_fact(
    *,
    observation_id: str,
    value: str,
    period_end: str,
    available_at: str,
) -> dict:
    return {
        "observationId": observation_id,
        "contentHash": observation_id.rsplit(":", 1)[-1].ljust(64, "0")[:64],
        "observationType": "DURATION",
        "normalizedOperand": "operating_cash_flow",
        "entityId": "CIK:0000000001",
        "taxonomy": "us-gaap",
        "concept": "NetCashProvidedByUsedInOperatingActivities",
        "unit": "USD",
        "currency": "USD",
        "dimensions": {"scope": "CONSOLIDATED_ENTITY_FROM_COMPANY_FACTS"},
        "fiscalYear": 2025,
        "periodStart": "2025-01-01",
        "periodEnd": period_end,
        "durationClass": "YTD",
        "availableAt": available_at,
        "value": value,
    }


def test_concept_map_restores_frozen_v1_total_interest_semantics() -> None:
    assert SEC_CONCEPT_MAPPING_VERSION == "sec-us-gaap-objective-rating-map-v1.1.0"
    interest_concepts = {rule[1] for rule in CONCEPT_RULES["interest_expense"]}
    assert interest_concepts == {"InterestExpense"}
    assert "InterestAndDebtExpense" not in interest_concepts
    assert "InterestExpenseDebt" not in interest_concepts
    assert "InterestExpenseNonoperating" not in interest_concepts
    assert "EBITDA" not in {
        concept
        for rules in CONCEPT_RULES.values()
        for _taxonomy, concept, _units in rules
    }


@pytest.mark.parametrize(
    ("start", "end", "form", "expected"),
    [
        (date(2025, 1, 1), date(2025, 12, 31), "10-K", "ANNUAL"),
        (date(2025, 1, 1), date(2025, 3, 31), "10-Q", "DISCRETE_QUARTER"),
        (date(2025, 1, 1), date(2025, 6, 30), "10-Q", "YTD"),
        (date(2025, 1, 1), date(2025, 6, 30), "8-K", "UNPROVEN"),
    ],
)
def test_duration_classifier_uses_dates_and_form(
    start: date,
    end: date,
    form: str,
    expected: str,
) -> None:
    assert classify_duration(period_start=start, period_end=end, form=form) == expected


def test_ytd_difference_preserves_ordered_lineage_and_latest_availability() -> None:
    earlier = _ytd_fact(
        observation_id="sec-fact:EARLIER",
        value="100.00",
        period_end="2025-03-31",
        available_at="2025-05-01T20:00:00Z",
    )
    earlier["durationClass"] = "DISCRETE_QUARTER"
    later = _ytd_fact(
        observation_id="sec-fact:LATER",
        value="240.00",
        period_end="2025-06-30",
        available_at="2025-08-01T20:00:00Z",
    )

    derived = derive_ytd_difference(
        later,
        earlier,
        cutoff=datetime(2025, 8, 2, tzinfo=UTC),
    )

    assert derived["value"] == "140.00"
    assert derived["derivationVersion"] == SEC_YTD_DIFFERENCE_VERSION
    assert derived["orderedOperandIds"] == ["sec-fact:EARLIER", "sec-fact:LATER"]
    assert derived["availableAt"] == "2025-08-01T20:00:00Z"
    assert derived["observationId"].startswith("sec-derived:")


def test_ytd_difference_rejects_future_operand_and_context_mismatch() -> None:
    earlier = _ytd_fact(
        observation_id="sec-fact:EARLIER",
        value="100",
        period_end="2025-03-31",
        available_at="2025-05-01T20:00:00Z",
    )
    earlier["durationClass"] = "DISCRETE_QUARTER"
    later = _ytd_fact(
        observation_id="sec-fact:LATER",
        value="240",
        period_end="2025-06-30",
        available_at="2025-08-01T20:00:00Z",
    )
    with pytest.raises(ValueError, match="YTD_OPERAND_NOT_AVAILABLE_AT_CUTOFF"):
        derive_ytd_difference(
            later,
            earlier,
            cutoff=datetime(2025, 7, 31, tzinfo=UTC),
        )

    later["unit"] = "EUR"
    with pytest.raises(ValueError, match="YTD_IDENTITY_MISMATCH"):
        derive_ytd_difference(
            later,
            earlier,
            cutoff=datetime(2025, 8, 2, tzinfo=UTC),
        )


def test_discrete_quarter_builder_uses_latest_revision_per_period() -> None:
    first = _ytd_fact(
        observation_id="sec-fact:FIRST",
        value="100",
        period_end="2025-03-31",
        available_at="2025-05-01T20:00:00Z",
    )
    first["durationClass"] = "DISCRETE_QUARTER"
    first["accession"] = "0001"
    amended = dict(first)
    amended.update(
        {
            "observationId": "sec-fact:AMENDED",
            "contentHash": "A" * 64,
            "value": "110",
            "availableAt": "2025-05-15T20:00:00Z",
            "accession": "0002",
        }
    )
    second_ytd = _ytd_fact(
        observation_id="sec-fact:SECOND",
        value="250",
        period_end="2025-06-30",
        available_at="2025-08-01T20:00:00Z",
    )
    second_ytd["accession"] = "0003"

    result = derive_discrete_quarters(
        [first, amended, second_ytd],
        cutoff=datetime(2025, 8, 2, tzinfo=UTC),
    )

    assert len(result) == 1
    assert result[0]["value"] == "140"
    assert result[0]["orderedOperandIds"][0] == "sec-fact:AMENDED"


def _fiscal_fact(
    *,
    observation_id: str,
    value: str,
    period_end: str,
    duration_class: str,
    fiscal_period: str,
    form: str,
    available_at: str,
) -> dict:
    return {
        **_ytd_fact(
            observation_id=observation_id,
            value=value,
            period_end=period_end,
            available_at=available_at,
        ),
        "fiscalPeriod": fiscal_period,
        "form": form,
        "amendment": form.endswith("/A"),
        "revisionStatus": "PRESERVED_REVISION",
        "accession": f"0000000001-26-{observation_id[-3:]}",
        "durationClass": duration_class,
    }


def test_fiscal_q4_difference_is_a_separate_strict_derivation() -> None:
    nine_month = _fiscal_fact(
        observation_id="sec-fact:009",
        value="750",
        period_end="2025-09-30",
        duration_class="YTD",
        fiscal_period="Q3",
        form="10-Q",
        available_at="2025-11-01T20:00:00Z",
    )
    annual = _fiscal_fact(
        observation_id="sec-fact:012",
        value="1100",
        period_end="2025-12-31",
        duration_class="ANNUAL",
        fiscal_period="FY",
        form="10-K",
        available_at="2026-02-01T20:00:00Z",
    )

    derived = derive_fiscal_q4_difference(
        annual,
        nine_month,
        cutoff=datetime(2026, 2, 2, tzinfo=UTC),
    )

    assert derived["value"] == "350"
    assert derived["periodStart"] == "2025-10-01"
    assert derived["periodEnd"] == "2025-12-31"
    assert derived["derivationVersion"] == SEC_FISCAL_Q4_DIFFERENCE_VERSION
    assert derived["orderedOperandAccessions"] == [
        nine_month["accession"],
        annual["accession"],
    ]
    assert derived["orderedOperandAvailableAt"] == [
        nine_month["availableAt"],
        annual["availableAt"],
    ]


def test_fiscal_q4_difference_rejects_future_amendment_and_calendar_mismatch() -> None:
    nine_month = _fiscal_fact(
        observation_id="sec-fact:009",
        value="750",
        period_end="2025-09-30",
        duration_class="YTD",
        fiscal_period="Q3",
        form="10-Q",
        available_at="2025-11-01T20:00:00Z",
    )
    annual = _fiscal_fact(
        observation_id="sec-fact:012",
        value="1100",
        period_end="2025-12-31",
        duration_class="ANNUAL",
        fiscal_period="FY",
        form="10-K",
        available_at="2026-02-01T20:00:00Z",
    )

    with pytest.raises(ValueError, match="OPERAND_NOT_AVAILABLE_AT_CUTOFF"):
        derive_fiscal_q4_difference(
            annual,
            nine_month,
            cutoff=datetime(2026, 1, 31, tzinfo=UTC),
        )

    annual["form"] = "10-K/A"
    annual["amendment"] = True
    with pytest.raises(ValueError, match="AMENDED_OPERAND"):
        derive_fiscal_q4_difference(
            annual,
            nine_month,
            cutoff=datetime(2026, 2, 2, tzinfo=UTC),
        )

    annual["form"] = "10-K"
    annual["amendment"] = False
    annual["periodEnd"] = "2026-02-28"
    with pytest.raises(ValueError, match="53_54_WEEK_ALIGNMENT_UNPROVEN"):
        derive_fiscal_q4_difference(
            annual,
            nine_month,
            cutoff=datetime(2026, 3, 1, tzinfo=UTC),
        )


def test_fiscal_q4_builder_keeps_rejections_explicit() -> None:
    nine_month = _fiscal_fact(
        observation_id="sec-fact:009",
        value="750",
        period_end="2025-09-30",
        duration_class="YTD",
        fiscal_period="Q3",
        form="10-Q",
        available_at="2025-11-01T20:00:00Z",
    )
    annual = _fiscal_fact(
        observation_id="sec-fact:012",
        value="1100",
        period_end="2025-12-31",
        duration_class="ANNUAL",
        fiscal_period="FY",
        form="10-K",
        available_at="2026-02-01T20:00:00Z",
    )

    derived, rejected = derive_fiscal_q4_quarters(
        [nine_month, annual],
        cutoff=datetime(2026, 2, 2, tzinfo=UTC),
    )
    assert len(derived) == 1
    assert rejected == {}

    annual["amendment"] = True
    _, rejected = derive_fiscal_q4_quarters(
        [nine_month, annual],
        cutoff=datetime(2026, 2, 2, tzinfo=UTC),
    )
    assert rejected["FISCAL_Q4_AMENDED_OPERAND_REQUIRES_MANUAL_RECONCILIATION"] == 1

    annual["amendment"] = False
    conflicting = dict(annual)
    conflicting.update(
        {
            "value": "1200",
            "availableAt": "2026-02-02T20:00:00Z",
            "accession": "0000000001-26-CONFLICT",
            "observationId": "sec-fact:CONFLICT",
            "contentHash": "F" * 64,
        }
    )
    _, rejected = derive_fiscal_q4_quarters(
        [nine_month, annual, conflicting],
        cutoff=datetime(2026, 2, 3, tzinfo=UTC),
    )
    assert rejected["FISCAL_Q4_RESTATEMENT_VALUE_CONFLICT"] == 1


def test_ebitda_derivation_requires_exact_compatible_operands() -> None:
    base = {
        "observationType": "DURATION",
        "entityId": "CIK:0000000001",
        "unit": "USD",
        "currency": "USD",
        "dimensions": {"scope": "CONSOLIDATED_ENTITY_FROM_COMPANY_FACTS"},
        "periodStart": "2025-01-01",
        "periodEnd": "2025-12-31",
        "durationClass": "ANNUAL",
        "availableAt": "2026-02-01T20:00:00Z",
    }
    pretax = {
        **base,
        "normalizedOperand": "pretax_income",
        "value": "100",
        "observationId": "pretax",
        "contentHash": "1" * 64,
    }
    interest = {
        **base,
        "normalizedOperand": "interest_expense",
        "value": "20",
        "observationId": "interest",
        "contentHash": "2" * 64,
    }
    depreciation = {
        **base,
        "normalizedOperand": "depreciation_depletion_amortization",
        "value": "30",
        "observationId": "da",
        "contentHash": "3" * 64,
    }

    result = derive_ebitda(
        pretax_income=pretax,
        interest_expense=interest,
        depreciation_amortization=depreciation,
        cutoff=datetime(2026, 2, 2, tzinfo=UTC),
    )

    assert result["value"] == "150"
    assert result["frozenV1Eligibility"] == "NOT_APPROVED_SOURCE_NORMALIZATION"
    assert result["orderedOperandIds"] == ["pretax", "interest", "da"]

    interest["periodEnd"] = "2025-09-30"
    with pytest.raises(ValueError, match="EBITDA_OPERAND_CONTEXT_MISMATCH"):
        derive_ebitda(
            pretax_income=pretax,
            interest_expense=interest,
            depreciation_amortization=depreciation,
            cutoff=datetime(2026, 2, 2, tzinfo=UTC),
        )


def test_market_policy_requires_an_explicit_next_session_open() -> None:
    assert MARKET_AVAILABILITY_POLICY_VERSION == "US-EOD-NEXT-SESSION-OPEN-v1.0.0"
    opens = (
        datetime(2025, 7, 7, 13, 30, tzinfo=UTC),
        datetime(2025, 7, 8, 13, 30, tzinfo=UTC),
    )
    assert next_session_open_available_at(date(2025, 7, 7), opens) == opens[1]
    with pytest.raises(ValueError, match="NEXT_SESSION_OPEN_NOT_PROVIDED"):
        next_session_open_available_at(date(2025, 7, 8), opens)
