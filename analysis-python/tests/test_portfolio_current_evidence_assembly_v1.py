from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from equity_analysis.main import app
from equity_analysis.portfolio_context.contracts_v1 import (
    ConstraintInputV1,
    EvidenceState,
    ModelEvidenceLabel,
    SleeveType,
)
from equity_analysis.portfolio_context.evidence_assembly_v2 import (
    CurrentPortfolioAssemblyV1,
    CurrentPortfolioEvidenceViolation,
    HoldingEvidenceV1,
    ModelReferenceV1,
    PriceEvidenceV1,
    assemble_current_portfolio_v1,
)
from equity_analysis.portfolio_context.routes_v1 import (
    CurrentPortfolioAssemblyCommandV1,
    assemble_current_portfolio,
)

CUTOFF = datetime(2026, 8, 12, 23, 59, 59, tzinfo=UTC)
client = TestClient(app)


def _price(state: EvidenceState = EvidenceState.VALID) -> PriceEvidenceV1:
    if state is not EvidenceState.VALID:
        return PriceEvidenceV1(state, None, None, None, None, None, None, None, None)
    return PriceEvidenceV1(
        state,
        "00000000-0000-4000-8000-000000000001",
        "sha256:" + "1" * 64,
        "00000000-0000-4000-8000-000000000002",
        "sha256:" + "2" * 64,
        Decimal("200"),
        datetime(2026, 8, 12, 20, tzinfo=UTC),
        datetime(2026, 8, 12, 21, tzinfo=UTC),
        datetime(2026, 8, 12, 22, tzinfo=UTC),
    )


def _assembly(price: PriceEvidenceV1 | None = None) -> CurrentPortfolioAssemblyV1:
    return CurrentPortfolioAssemblyV1(
        CUTOFF,
        Decimal("20000"),
        Decimal("0"),
        (
            HoldingEvidenceV1(
                "00000000-0000-4000-8000-000000000010",
                "MSFT",
                Decimal("400"),
                SleeveType.LONG_TERM_CORE,
                "INFORMATION_TECHNOLOGY",
                price or _price(),
            ),
        ),
        (
            ModelReferenceV1(
                SleeveType.LONG_TERM_CORE,
                "fundamental-value-v1.1.0",
                ModelEvidenceLabel.NOT_VALIDATED,
                False,
                "00000000-0000-4000-8000-000000000020",
                "sha256:" + "3" * 64,
            ),
            ModelReferenceV1(
                SleeveType.QUANT_TRADING,
                "quant-trading-v1.1.0",
                ModelEvidenceLabel.NOT_VALIDATED,
                False,
                "00000000-0000-4000-8000-000000000021",
                "sha256:" + "4" * 64,
            ),
        ),
        ConstraintInputV1(
            Decimal("0.5"), Decimal("0.6"), Decimal("0.1"), Decimal("0")
        ),
    )


def test_assembly_derives_market_value_and_value_free_manifest() -> None:
    result = assemble_current_portfolio_v1(_assembly())

    assert result.risk_input.positions[0].market_value == Decimal("80000")
    assert result.evidence_manifest["browserSuppliedMarketValueAllowed"] is False
    assert result.evidence_manifest["positions"][0]["marketValue"] == "80000"
    assert result.evidence_manifest["manifestHash"].startswith("sha256:")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ticker", "MSFT.A"),
        ("sleeve", SleeveType.QUANT_TRADING),
        ("sector_code", "FINANCIALS"),
    ],
)
def test_manifest_hash_binds_position_presentation_and_sleeve(
    field: str, value: object
) -> None:
    baseline = _assembly()
    changed_holding = replace(baseline.holdings[0], **{field: value})
    changed = replace(baseline, holdings=(changed_holding,))
    assert assemble_current_portfolio_v1(changed).evidence_manifest[
        "manifestHash"
    ] != assemble_current_portfolio_v1(baseline).evidence_manifest["manifestHash"]


def test_missing_price_stays_missing_without_zero_substitution() -> None:
    result = assemble_current_portfolio_v1(_assembly(_price(EvidenceState.MISSING)))
    assert result.risk_input.positions[0].market_value is None
    assert result.evidence_manifest["positions"][0]["marketValue"] is None


def test_future_ingestion_fails_closed() -> None:
    value = _price()
    future = PriceEvidenceV1(
        value.state,
        value.selection_request_id,
        value.selection_result_hash,
        value.evidence_id,
        value.evidence_hash,
        value.price,
        value.effective_at,
        value.available_at,
        datetime(2026, 8, 13, tzinfo=UTC),
    )
    with pytest.raises(CurrentPortfolioEvidenceViolation, match="CHRONOLOGY"):
        assemble_current_portfolio_v1(_assembly(future))


def test_not_validated_model_cannot_gain_research_authority() -> None:
    value = _assembly()
    bad = CurrentPortfolioAssemblyV1(
        value.as_of_time,
        value.cash_value,
        value.liability_value,
        value.holdings,
        (
            ModelReferenceV1(
                SleeveType.LONG_TERM_CORE,
                "fundamental-value-v1.1.0",
                ModelEvidenceLabel.NOT_VALIDATED,
                True,
                "00000000-0000-4000-8000-000000000020",
                "sha256:" + "3" * 64,
            ),
            value.model_references[1],
        ),
        value.constraints,
    )
    with pytest.raises(CurrentPortfolioEvidenceViolation, match="NOT_VALIDATED"):
        assemble_current_portfolio_v1(bad)


def test_internal_current_assembly_route_derives_risk_context() -> None:
    command = {
        "assemblyVersion": "current-portfolio-evidence-assembly-v1.0.0",
        "asOfTime": "2026-08-12T23:59:59Z",
        "cashValue": "20000",
        "liabilityValue": "0",
        "holdings": [
            {
                "securityId": "00000000-0000-4000-8000-000000000010",
                "ticker": "MSFT",
                "quantity": "400",
                "sleeve": "LONG_TERM_CORE",
                "sectorCode": "INFORMATION_TECHNOLOGY",
                "priceEvidence": {
                    "state": "VALID",
                    "selectionRequestId": "00000000-0000-4000-8000-000000000001",
                    "selectionResultHash": "sha256:" + "1" * 64,
                    "evidenceId": "00000000-0000-4000-8000-000000000002",
                    "evidenceHash": "sha256:" + "2" * 64,
                    "price": "200",
                    "effectiveAt": "2026-08-12T20:00:00Z",
                    "availableAt": "2026-08-12T21:00:00Z",
                    "ingestedAt": "2026-08-12T22:00:00Z",
                },
            }
        ],
        "modelReferences": [
            {
                "sleeve": "LONG_TERM_CORE",
                "modelVersion": "fundamental-value-v1.1.0",
                "evidenceLabel": "NOT_VALIDATED",
                "researchUseAllowed": False,
                "referenceId": "00000000-0000-4000-8000-000000000020",
                "referenceHash": "sha256:" + "3" * 64,
            },
            {
                "sleeve": "QUANT_TRADING",
                "modelVersion": "quant-trading-v1.1.0",
                "evidenceLabel": "NOT_VALIDATED",
                "researchUseAllowed": False,
                "referenceId": "00000000-0000-4000-8000-000000000021",
                "referenceHash": "sha256:" + "4" * 64,
            },
        ],
        "constraints": {
            "maximumPositionWeight": "0.5",
            "maximumSectorWeight": "0.6",
            "minimumCashWeight": "0.1",
            "maximumLeverageRatio": "0",
        },
    }
    body = assemble_current_portfolio(
        CurrentPortfolioAssemblyCommandV1.model_validate(command)
    )
    assert body["evidenceManifest"]["positions"][0]["marketValue"] == "80000"
    assert body["riskContext"]["totals"]["netPortfolioValue"] == "100000"


def test_internal_current_assembly_route_rejects_browser_market_value() -> None:
    response = client.post(
        "/internal/v1/portfolio-context/current-evidence-assemblies",
        json={"marketValue": "100000"},
    )
    assert response.status_code == 404
