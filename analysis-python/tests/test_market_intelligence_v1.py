import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from equity_analysis.main import app
from equity_analysis.market_intelligence.models import (
    AiNarrative,
    Classification,
    ComparableCohort,
    DeterministicView,
    DeterministicViewState,
    EvidenceLineage,
    FactState,
    Horizon,
    HorizonView,
    ProfileFact,
    ProfileInput,
    RankingState,
    RankMetric,
    ScreeningFilter,
    ScreeningRequest,
    SecurityMaster,
    SortDirection,
    ValuationEvidence,
)
from equity_analysis.market_intelligence.service import (
    MARKET_INTELLIGENCE_VERSION,
    build_security_profile,
    screen_profiles,
)

FIXTURE = Path(__file__).parent / "fixtures" / "market_intelligence_v1_profiles.json"
HASH = "sha256:" + "a" * 64


def _lineage(as_of: datetime) -> tuple[EvidenceLineage, ...]:
    return (
        EvidenceLineage(
            provider_code="FIXTURE",
            provider_schema_version="fixture-v1",
            parser_version="fixture-parser-v1",
            source_reference="fixture://market-intelligence-v1",
            content_hash=HASH,
            available_at=as_of - timedelta(days=1),
            retrieved_at=as_of - timedelta(hours=1),
        ),
    )


def _view(
    horizon: Horizon,
    score: str,
    as_of: datetime,
    *,
    stale: bool = False,
) -> HorizonView:
    tactical = horizon != Horizon.TWELVE_MONTHS_PLUS
    return HorizonView(
        horizon=horizon,
        deterministic_view=DeterministicView(
            model_id="DAILY_TACTICAL_SIGNAL" if tactical else "LONG_HORIZON_RESEARCH",
            model_version=(
                "TACTICAL-SIGNAL-v2.1.0" if tactical else "LONG-HORIZON-RESEARCH-v1.0.0"
            ),
            state=DeterministicViewState.ASSESSED,
            as_of=as_of - timedelta(days=1),
            effective_at=as_of - timedelta(hours=12),
            expires_at=as_of - timedelta(seconds=1) if stale else None,
            score=Decimal(score),
            label="FIXTURE_ASSESSED",
            input_hash=HASH,
            evidence_hash=HASH,
            explanation=("Deterministic fixture assessment.",),
        ),
    )


def _input(row: dict[str, object], as_of: datetime, *, stale: bool = False) -> ProfileInput:
    lineage = _lineage(as_of)
    tactical = row["tacticalScores"]
    assert isinstance(tactical, dict)
    return ProfileInput(
        security=SecurityMaster(
            security_id=str(row["securityId"]),
            symbol=str(row["symbol"]),
            issuer_name=str(row["issuerName"]),
            exchange_mic="XNAS",
            currency="USD",
            instrument_type="COMMON_STOCK",
            cik="0000000001",
            durable_provider_id=f"fixture-{row['securityId']}",
        ),
        classification=Classification(
            taxonomy_code="GICS",
            taxonomy_version="GICS-2025-fixture",
            sector_code=str(row["sectorCode"]),
            sector_name=str(row["sectorName"]),
            industry_code=str(row["industryCode"]),
            industry_name=str(row["industryName"]),
            company_type=str(row["companyType"]),
            effective_at=as_of - timedelta(days=365),
            lineage=lineage,
        ),
        comparable_cohorts=(
            ComparableCohort(
                cohort_id=f"sector-{row['sectorCode']}-general",
                taxonomy_version="GICS-2025-fixture",
                sector_code=str(row["sectorCode"]),
                company_type=str(row["companyType"]),
                eligible_member_count=35,
                minimum_member_count=30,
            ),
        ),
        facts=(
            ProfileFact(
                name="market_cap",
                metric_version="fixture-v1",
                state=FactState.VALID,
                value=Decimal(str(row["marketCap"])),
                lineage=lineage,
            ),
            ProfileFact(
                name="latest_price",
                metric_version="fixture-v1",
                state=FactState.VALID,
                value=Decimal("200"),
                lineage=lineage,
            ),
            ProfileFact(
                name="average_daily_dollar_volume",
                metric_version="fixture-v1",
                state=FactState.VALID,
                value=Decimal("100000000"),
                lineage=lineage,
            ),
        ),
        objective_quality_score=Decimal(str(row["qualityScore"])),
        objective_valuation_score=Decimal(str(row["valuationScore"])),
        objective_rating_status="SCORED",
        objective_rating_version="Objective-Rating-v1",
        horizons=(
            _view(Horizon.ONE_WEEK, str(tactical["ONE_WEEK"]), as_of, stale=stale),
            _view(Horizon.ONE_MONTH, str(tactical["ONE_MONTH"]), as_of),
            _view(Horizon.THREE_MONTHS, str(tactical["THREE_MONTHS"]), as_of),
            _view(
                Horizon.TWELVE_MONTHS_PLUS,
                str(row["longHorizonScore"]),
                as_of,
            ),
        ),
        valuation=ValuationEvidence(
            state=FactState.VALID,
            as_of=as_of - timedelta(days=1),
            objective_valuation_score=Decimal(str(row["valuationScore"])),
            long_horizon_valuation_score=Decimal(str(row["longHorizonScore"])),
            own_history_percentile=Decimal(str(row["ownHistoryPercentile"])),
        ),
        ai_narrative=AiNarrative(status="NOT_EXECUTED"),
    )


def _fixture_profiles() -> tuple[datetime, tuple]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    as_of = datetime.fromisoformat(payload["asOf"].replace("Z", "+00:00"))
    return as_of, tuple(
        build_security_profile(_input(row, as_of), as_of) for row in payload["profiles"]
    )


def test_fixture_profiles_are_complete_explainable_and_ranking_eligible() -> None:
    _, profiles = _fixture_profiles()

    assert all(profile.contract_version == MARKET_INTELLIGENCE_VERSION for profile in profiles)
    assert all(profile.ranking_state == RankingState.ELIGIBLE for profile in profiles)
    assert all(profile.explainability for profile in profiles)
    assert all(profile.ai_narrative.status == "NOT_EXECUTED" for profile in profiles)


def test_screen_filters_sector_and_ranks_without_ai_input() -> None:
    as_of, profiles = _fixture_profiles()
    result = screen_profiles(
        profiles,
        ScreeningRequest(
            as_of=as_of,
            filters=ScreeningFilter(sectors=("45",)),
            rank_by=RankMetric.OBJECTIVE_QUALITY,
        ),
    )

    assert [item.symbol for item in result.items] == ["MSFT", "AAPL"]
    assert [item.value for item in result.items] == [Decimal("88.00"), Decimal("82.50")]
    assert result.acceptance["gateStatus"] == "PASS"
    assert result.acceptance["explainableCount"] == 2


def test_buying_opportunity_is_deterministic_mean_of_explicit_evidence() -> None:
    as_of, profiles = _fixture_profiles()
    result = screen_profiles(
        profiles,
        ScreeningRequest(
            as_of=as_of,
            rank_by=RankMetric.BUYING_OPPORTUNITY,
            direction=SortDirection.DESCENDING,
        ),
    )

    assert result.items[0].symbol == "AAPL"
    assert result.items[0].value == Decimal("64.33333333333333333333333333")


def test_stale_horizon_and_provider_pass_do_not_create_ranking_eligibility() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    as_of = datetime.fromisoformat(payload["asOf"].replace("Z", "+00:00"))
    stale = build_security_profile(_input(payload["profiles"][0], as_of, stale=True), as_of)

    assert stale.ranking_state == RankingState.NOT_ELIGIBLE
    assert "HORIZON_ONE_WEEK_STALE" in stale.ranking_exclusions

    result = screen_profiles(
        (stale,),
        ScreeningRequest(as_of=as_of, rank_by=RankMetric.OBJECTIVE_QUALITY),
    )
    assert result.items == ()
    assert result.acceptance["gateStatus"] == "NO_ELIGIBLE_RESULTS"


def test_fact_states_never_allow_missing_value_to_become_zero() -> None:
    with pytest.raises(ValueError, match="Non-VALID facts cannot carry a value"):
        ProfileFact(
            name="market_cap",
            metric_version="fixture-v1",
            state=FactState.MISSING,
            value=Decimal("0"),
            reason="Provider omitted the field.",
        )


def test_internal_api_exposes_versioned_screening_contract() -> None:
    as_of, profiles = _fixture_profiles()
    response = TestClient(app).post(
        "/internal/v1/market-intelligence/screen",
        json={
            "asOf": as_of.isoformat(),
            "profiles": [profile.model_dump(mode="json", by_alias=True) for profile in profiles],
            "rankBy": "LONG_HORIZON",
            "direction": "DESCENDING",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    assert response.json()["contractVersion"] == MARKET_INTELLIGENCE_VERSION
    assert [item["symbol"] for item in response.json()["items"]] == ["MSFT", "AAPL"]
