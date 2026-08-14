from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from equity_analysis.evidence_foundation.contracts_v1 import (
    DataState,
    UnifiedEvidenceContractViolation,
)
from equity_analysis.portfolio_context.contracts_v1 import ConstraintInputV1, SleeveType
from equity_analysis.portfolio_context.current_repository_assembly_v1 import (
    CurrentPortfolioByIdRequestV1,
    CurrentPortfolioRepositoryAssemblerV1,
    HoldingSelectionReferenceV1,
)
from equity_analysis.portfolio_context.evidence_assembly_v2 import (
    CurrentPortfolioEvidenceViolation,
)

SECURITY = "11111111-1111-4111-8111-111111111111"
REQUEST = "22222222-2222-4222-8222-222222222222"
FV = "33333333-3333-4333-8333-333333333333"
QUANT = "44444444-4444-4444-8444-444444444444"
HASH = "sha256:" + "1" * 64
CUTOFF = datetime(2026, 8, 13, 20, tzinfo=UTC)


def selector(security_id: str = SECURITY):
    selected = SimpleNamespace(
        evidence_id="55555555-5555-4555-8555-555555555555",
        normalized_record_hash=HASH,
        canonical_data={"adjustmentMode": "UNADJUSTED", "close": "125.50"},
        effective_at=datetime(2026, 8, 13, 19, 59, tzinfo=UTC),
        available_at=datetime(2026, 8, 13, 20, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 8, 13, 20, 0, tzinfo=UTC),
        stale_after=datetime(2026, 8, 14, 20, 0, tzinfo=UTC),
    )
    return SimpleNamespace(
        request=SimpleNamespace(
            security=SimpleNamespace(security_id=security_id, ticker="AAPL"),
            decision_cutoff=CUTOFF,
            sealed_ingestion_cutoff=CUTOFF,
            policy=SimpleNamespace(
                domain="DAILY_PRICE",
                field_code="CLOSE_PRICE",
                domain_constraints={"adjustmentMode": "UNADJUSTED"},
            ),
        ),
        result=SimpleNamespace(state=DataState.VALID, selected=selected),
    )


def request() -> CurrentPortfolioByIdRequestV1:
    return CurrentPortfolioByIdRequestV1(
        CUTOFF,
        Decimal("1000"),
        Decimal("0"),
        (
            HoldingSelectionReferenceV1(
                SECURITY,
                "AAPL",
                Decimal("10"),
                SleeveType.LONG_TERM_CORE,
                "45",
                REQUEST,
                FV,
            ),
        ),
        ConstraintInputV1(
            Decimal("1"), Decimal("1"), Decimal("0"), Decimal("0")
        ),
    )


def install_repositories(monkeypatch, selected=None) -> None:
    aggregate = selector() if selected is None else selected
    monkeypatch.setattr(
        "equity_analysis.portfolio_context.current_repository_assembly_v1.EvidenceFoundationRepository",
        lambda _url: SimpleNamespace(load_selector_aggregate=lambda _id: aggregate),
    )
    monkeypatch.setattr(
        "equity_analysis.portfolio_context.current_repository_assembly_v1.selector_result_hash",
        lambda _request, _result: HASH,
    )
    monkeypatch.setattr(
        "equity_analysis.portfolio_context.current_repository_assembly_v1.CurrentAssessmentRepositoryV1",
        lambda _url: SimpleNamespace(
            load=lambda _id: SimpleNamespace(
                assessment_id=FV,
                assessment_content_hash=HASH,
                payload={
                    "security_id": SECURITY,
                    "decision_cutoff": CUTOFF,
                    "model_evidence_label": "NOT_VALIDATED",
                    "assessment": {"model_version": "FUNDAMENTAL-VALUE-v1.0.0"},
                    "investment_view": {"deterministic_action_authorized": False},
                },
            )
        ),
    )
    monkeypatch.setattr(
        "equity_analysis.portfolio_context.current_repository_assembly_v1.QuantResearchDecisionRepositoryV11",
        lambda _url: SimpleNamespace(
            load=lambda _id: SimpleNamespace(
                decision_id=QUANT,
                content_hash=HASH,
                payload={
                    "decisionDate": "2026-08-13",
                    "modelVersion": "QUANT-TRADING-v1.1.0",
                    "modelEvidenceLabel": "NOT_VALIDATED",
                    "authority": {"deterministicResearchSignal": True},
                    "signals": [{"securityId": SECURITY}],
                },
            )
        ),
    )


def test_id_only_assembly_hydrates_price_and_model_lineage(monkeypatch) -> None:
    install_repositories(monkeypatch)
    assembler = CurrentPortfolioRepositoryAssemblerV1("postgresql://test")
    result = assembler.assemble(request())
    assert result.risk_input.positions[0].market_value == Decimal("1255.00")
    assert result.evidence_manifest["positions"][0]["price"] == "125.5"
    assert result.evidence_manifest["positions"][0]["ticker"] == "AAPL"
    assert result.evidence_manifest["positions"][0]["sleeve"] == "LONG_TERM_CORE"
    assert result.evidence_manifest["positions"][0]["sectorCode"] == "45"
    assert all(not item.research_use_allowed for item in result.risk_input.sleeve_evidence)


def test_id_only_assembly_rejects_selector_security_mismatch(monkeypatch) -> None:
    install_repositories(monkeypatch, selector("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
    assembler = CurrentPortfolioRepositoryAssemblerV1("postgresql://test")
    with pytest.raises(
        CurrentPortfolioEvidenceViolation,
        match="PRICE_REFERENCE_SECURITY_MISMATCH",
    ):
        assembler.assemble(request())


def test_id_only_assembly_rejects_future_selector_chronology(monkeypatch) -> None:
    aggregate = selector()
    aggregate.request.decision_cutoff = datetime(2026, 8, 14, 20, tzinfo=UTC)
    install_repositories(monkeypatch, aggregate)
    with pytest.raises(
        CurrentPortfolioEvidenceViolation,
        match="PRICE_REFERENCE_AFTER_CONTEXT_CUTOFF",
    ):
        CurrentPortfolioRepositoryAssemblerV1("postgresql://test").assemble(request())


@pytest.mark.parametrize(
    ("mutate", "value"),
    [
        ("field_code", "ADJUSTED_CLOSE_PRICE"),
        ("policy_adjustment", "TOTAL_RETURN_ADJUSTED"),
        ("canonical_adjustment", "TOTAL_RETURN_ADJUSTED"),
        ("canonical_price_key", None),
    ],
)
def test_id_only_assembly_rejects_price_semantic_drift(
    monkeypatch,
    mutate: str,
    value: str | None,
) -> None:
    aggregate = selector()
    if mutate == "field_code":
        aggregate.request.policy.field_code = value
    elif mutate == "policy_adjustment":
        aggregate.request.policy.domain_constraints["adjustmentMode"] = value
    elif mutate == "canonical_adjustment":
        aggregate.result.selected.canonical_data["adjustmentMode"] = value
    else:
        aggregate.result.selected.canonical_data.pop("close")
    install_repositories(monkeypatch, aggregate)
    expected = (
        "CLOSE_PRICE_VALUE_INVALID"
        if mutate == "canonical_price_key"
        else "PRICE_REFERENCE_DOMAIN_MISMATCH"
    )
    with pytest.raises(CurrentPortfolioEvidenceViolation, match=expected):
        CurrentPortfolioRepositoryAssemblerV1("postgresql://test").assemble(request())


def test_id_only_assembly_rejects_valid_price_stale_at_context(monkeypatch) -> None:
    aggregate = selector()
    aggregate.result.selected.stale_after = datetime(2020, 8, 14, 20, tzinfo=UTC)
    install_repositories(monkeypatch, aggregate)
    with pytest.raises(
        CurrentPortfolioEvidenceViolation,
        match="PRICE_EVIDENCE_STALE_AT_CONTEXT",
    ):
        CurrentPortfolioRepositoryAssemblerV1("postgresql://test").assemble(request())


def test_id_only_assembly_rejects_future_fundamental_decision(monkeypatch) -> None:
    install_repositories(monkeypatch)
    from equity_analysis.portfolio_context import current_repository_assembly_v1 as module

    original = module.CurrentAssessmentRepositoryV1
    repository = original("postgresql://test")
    persisted = repository.load(FV)
    persisted.payload["decision_cutoff"] = datetime(2026, 8, 14, 20, tzinfo=UTC)
    future_repository = SimpleNamespace(load=lambda _id: persisted)
    monkeypatch.setattr(
        module, "CurrentAssessmentRepositoryV1", lambda _url: future_repository
    )
    with pytest.raises(
        CurrentPortfolioEvidenceViolation,
        match="FUNDAMENTAL_REFERENCE_AFTER_CONTEXT_CUTOFF",
    ):
        CurrentPortfolioRepositoryAssemblerV1("postgresql://test").assemble(request())


def test_id_only_assembly_rejects_future_quant_decision(monkeypatch) -> None:
    value = request()
    quant_holding = HoldingSelectionReferenceV1(
        SECURITY,
        "AAPL",
        Decimal("10"),
        SleeveType.QUANT_TRADING,
        "45",
        REQUEST,
        QUANT,
    )
    value = CurrentPortfolioByIdRequestV1(
        value.as_of_time,
        value.cash_value,
        value.liability_value,
        (quant_holding,),
        value.constraints,
    )
    install_repositories(monkeypatch)
    from equity_analysis.portfolio_context import current_repository_assembly_v1 as module

    persisted = module.QuantResearchDecisionRepositoryV11("postgresql://test").load(QUANT)
    persisted.payload["decisionDate"] = "2026-08-14"
    future_repository = SimpleNamespace(load=lambda _id: persisted)
    monkeypatch.setattr(
        module, "QuantResearchDecisionRepositoryV11", lambda _url: future_repository
    )
    with pytest.raises(
        CurrentPortfolioEvidenceViolation,
        match="QUANT_REFERENCE_AFTER_CONTEXT_CUTOFF",
    ):
        CurrentPortfolioRepositoryAssemblerV1("postgresql://test").assemble(value)


def test_id_only_assembly_preserves_missing_without_numeric_substitution(monkeypatch) -> None:
    aggregate = selector()
    aggregate.result.state = DataState.MISSING
    aggregate.result.selected = None
    install_repositories(monkeypatch, aggregate)
    result = CurrentPortfolioRepositoryAssemblerV1("postgresql://test").assemble(request())
    assert result.risk_input.positions[0].market_value is None
    row = result.evidence_manifest["positions"][0]
    assert row["priceState"] == "MISSING"
    assert row["price"] is None
    assert row["selectionRequestId"] == REQUEST


def test_id_only_assembly_propagates_v22_hash_integrity_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "equity_analysis.portfolio_context.current_repository_assembly_v1.EvidenceFoundationRepository",
        lambda _url: SimpleNamespace(
            load_selector_aggregate=lambda _id: (_ for _ in ()).throw(
                UnifiedEvidenceContractViolation(
                    "Persisted selector result content hash does not match readback"
                )
            )
        ),
    )
    with pytest.raises(UnifiedEvidenceContractViolation, match="content hash"):
        CurrentPortfolioRepositoryAssemblerV1("postgresql://test").assemble(request())


def test_id_only_route_schema_has_no_caller_price_or_market_value() -> None:
    from equity_analysis.portfolio_context.routes_v1 import CurrentPortfolioByIdCommandV1

    payload = {
        "assemblyVersion": "current-portfolio-evidence-assembly-v1.0.0",
        "asOfTime": "2026-08-13T20:00:00Z",
        "cashValue": "1000",
        "liabilityValue": "0",
        "holdings": [{
            "securityId": SECURITY, "ticker": "AAPL", "quantity": "10",
            "sleeve": "LONG_TERM_CORE", "sectorCode": "45",
            "selectionRequestId": REQUEST, "price": "125.5",
        }],
        "constraints": {
            "maximumPositionWeight": "1", "maximumSectorWeight": "1",
            "minimumCashWeight": "0", "maximumLeverageRatio": "0",
        },
    }
    with pytest.raises(ValueError):
        CurrentPortfolioByIdCommandV1.model_validate(payload)


def test_unsafe_caller_evidence_route_is_not_registered() -> None:
    from equity_analysis.portfolio_context.routes_v1 import router

    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post(
        "/internal/v1/portfolio-context/current-evidence-assemblies", json={}
    )
    assert response.status_code == 404


def test_id_only_route_requires_private_service_auth(monkeypatch) -> None:
    from equity_analysis.portfolio_context.routes_v1 import router

    monkeypatch.setenv("PORTFOLIO_DECISION_SERVICE_TOKEN", "private-service-token")
    app = FastAPI()
    app.include_router(router)
    path = "/internal/v1/portfolio-context/current-evidence-assemblies/by-id"
    payload = {
        "assemblyVersion": "current-portfolio-evidence-assembly-v1.0.0",
        "asOfTime": "2026-08-13T20:00:00Z",
        "cashValue": "1000",
        "liabilityValue": "0",
        "holdings": [
            {
                "securityId": SECURITY,
                "ticker": "AAPL",
                "quantity": "10",
                "sleeve": "LONG_TERM_CORE",
                "sectorCode": "45",
                "selectionRequestId": REQUEST,
                "modelReferenceId": FV,
            }
        ],
        "constraints": {
            "maximumPositionWeight": "1",
            "maximumSectorWeight": "1",
            "minimumCashWeight": "0",
            "maximumLeverageRatio": "0",
        },
    }
    assert TestClient(app).post(path, json=payload).status_code == 401
    assert TestClient(app).post(
        path,
        json=payload,
        headers={"X-Portfolio-Decision-Service-Token": "wrong"},
    ).status_code == 403
