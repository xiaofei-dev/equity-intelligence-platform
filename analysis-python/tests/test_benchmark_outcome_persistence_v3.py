from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_outcome_persistence_v3 import (
    BENCHMARK_OUTCOME_PERSISTENCE_V3,
    FamilyOutcomeV3,
    HoldingOutcomeV3,
    SecurityBenchmarkBindingV3,
    VariantOutcomeV3,
)

ROOT = Path(__file__).resolve().parents[2]
HASH = "sha256:" + "a" * 64
PUBLIC_ID = UUID("00000000-0000-4000-8000-000000000001")


def _seal(model_type, payload: dict, hash_field: str):
    provisional = model_type.model_validate(
        {**payload, hash_field: HASH},
        context={"skip_hash_verification": True},
    )
    body = provisional.model_dump(
        mode="json",
        by_alias=True,
        exclude={_snake(hash_field)},
    )
    return model_type.model_validate({**body, hash_field: canonical_hash(body)})


def _snake(alias: str) -> str:
    result = ""
    for character in alias:
        if character.isupper():
            result += "_" + character.lower()
        else:
            result += character
    return result


def _holding(
    *,
    public_id: UUID = PUBLIC_ID,
    gross: str = "0.10",
    cost: str = "0.02",
) -> HoldingOutcomeV3:
    payload = {
        "publicSecurityId": str(public_id),
        "benchmarkKind": "SPY",
        "variantId": "SPY",
        "state": "ASSESSED",
        "frozenWeightUnits": 1,
        "frozenTotalWeightUnits": 2,
        "frozenNotional": "100",
        "frozenAverageDailyDollarVolume": "1000",
        "grossReturn": gross,
        "roundTripCostRate": cost,
        "weightedGrossContribution": str(Decimal(gross) / 2),
        "weightedCostContribution": str(Decimal(cost) / 2),
        "weightedNetContribution": str((Decimal(gross) - Decimal(cost)) / 2),
        "priceActionEvidenceHash": HASH,
        "sourceManifestHash": HASH,
        "reasonCodes": [],
    }
    return _seal(HoldingOutcomeV3, payload, "outcomeContentHash")


def test_sector_binding_requires_dated_matching_identity() -> None:
    payload = {
        "publicSecurityId": str(PUBLIC_ID),
        "benchmarkKind": "SECTOR",
        "variantId": "XLK",
        "sectorIdentity": "Information Technology",
        "classificationEffectiveAt": "2026-07-29T20:00:00Z",
        "classificationAvailableAt": "2026-07-29T20:01:00Z",
        "classificationIngestedAt": "2026-07-29T20:02:00Z",
        "classificationSourceHash": HASH,
        "identityBindingHash": HASH,
    }
    binding = _seal(
        SecurityBenchmarkBindingV3,
        payload,
        "bindingContentHash",
    )
    assert binding.sector_identity == "Information Technology"

    payload["sectorIdentity"] = None
    with pytest.raises(ValueError, match="sector identity"):
        SecurityBenchmarkBindingV3.model_validate(
            {**payload, "bindingContentHash": HASH},
            context={"skip_hash_verification": True},
        )


def test_holding_outcome_rejects_aggregate_cost_substitution() -> None:
    holding = _holding()
    payload = holding.model_dump(mode="json", by_alias=True)
    payload["weightedCostContribution"] = "0.02"
    payload["outcomeContentHash"] = HASH
    with pytest.raises(ValueError, match="cost contribution"):
        HoldingOutcomeV3.model_validate(
            payload,
            context={"skip_hash_verification": True},
        )


def test_variant_is_derived_from_holding_contributions() -> None:
    second_id = UUID("00000000-0000-4000-8000-000000000002")
    holdings = (_holding(), _holding(public_id=second_id, gross="0.20", cost="0.04"))
    payload = {
        "benchmarkKind": "SPY",
        "variantId": "SPY",
        "state": "AVAILABLE",
        "grossReturn": "0.15",
        "roundTripCostRate": "0.03",
        "netReturn": "0.12",
        "priceActionEvidenceHash": HASH,
        "sourceManifestHash": HASH,
        "reasonCodes": [],
        "holdings": [
            item.model_dump(mode="json", by_alias=True) for item in holdings
        ],
    }
    variant = _seal(VariantOutcomeV3, payload, "outcomeContentHash")
    assert variant.net_return == Decimal("0.12")

    payload["roundTripCostRate"] = "0.02"
    with pytest.raises(ValueError, match="holding contributions"):
        VariantOutcomeV3.model_validate(
            {**payload, "outcomeContentHash": HASH},
            context={"skip_hash_verification": True},
        )


def test_family_aggregation_contract_separates_sector() -> None:
    base = {
        "benchmarkKind": "SECTOR",
        "aggregationMethod": "SECURITY_BINDING_WEIGHTED",
        "state": "AVAILABLE",
        "grossReturn": "0.10",
        "roundTripCostRate": "0.01",
        "netReturn": "0.09",
        "sourceManifestHash": HASH,
        "reasonCodes": [],
    }
    sector = _seal(FamilyOutcomeV3, base, "outcomeContentHash")
    assert sector.aggregation_method == "SECURITY_BINDING_WEIGHTED"

    with pytest.raises(ValueError, match="security-binding"):
        FamilyOutcomeV3.model_validate(
            {
                **base,
                "aggregationMethod": "SINGLE_VARIANT",
                "outcomeContentHash": HASH,
            },
            context={"skip_hash_verification": True},
        )


def test_v20_migration_preserves_v18_v19_and_declares_rich_successor() -> None:
    migration = (
        ROOT
        / "database"
        / "migrations"
        / "V20__create_forward_dqv_benchmark_outcome_v3.sql"
    ).read_text(encoding="utf-8")
    required = {
        "analytics.forward_dqv_benchmark_ledger_v3",
        "analytics.forward_dqv_benchmark_family_v3",
        "analytics.forward_dqv_benchmark_variant_v3",
        "analytics.forward_dqv_benchmark_holding_v3",
        "analytics.forward_dqv_security_benchmark_binding_v3",
        "analytics.forward_dqv_outcome_ledger_binding_v3",
        "analytics.forward_dqv_benchmark_holding_outcome_v3",
        "analytics.forward_dqv_benchmark_variant_outcome_v3",
        "analytics.forward_dqv_benchmark_family_outcome_v3",
        "analytics.forward_dqv_human_decision_record_v3",
        "analytics.forward_dqv_portfolio_suitability_boundary_v3",
    }
    assert required <= {
        line.split("CREATE TABLE ", 1)[1].split(" ", 1)[0]
        for line in migration.splitlines()
        if line.startswith("CREATE TABLE ")
    }
    assert "ALTER TABLE analytics.forward_dqv_enrollment_v2" not in migration
    assert "ALTER TABLE analytics.forward_dqv_outcome_batch_v2" not in migration
    assert "SECURITY_BINDING_WEIGHTED" in migration
    assert "frozen_average_daily_dollar_volume" in migration
    assert BENCHMARK_OUTCOME_PERSISTENCE_V3 in (
        "FORWARD-DQV-BENCHMARK-OUTCOME-PERSISTENCE-v3.0.0"
    )
