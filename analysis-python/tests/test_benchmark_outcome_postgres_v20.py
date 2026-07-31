from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_controlled_ledger_v22 import (
    ControlledBenchmarkFamilyV22,
    ControlledBenchmarkHoldingV22,
    ControlledBenchmarkLedgerSetV22,
    ControlledBenchmarkVariantV22,
)
from equity_analysis.forward_validation.benchmark_outcome_persistence_v3 import (
    BENCHMARK_LEDGER_PERSISTENCE_V3,
    BENCHMARK_OUTCOME_PERSISTENCE_V3,
    BenchmarkLedgerPersistenceV3,
    BenchmarkOutcomePersistenceV3,
    FamilyOutcomeV3,
    ForwardDqvBenchmarkOutcomeRepositoryV3,
    HoldingOutcomeV3,
    SecurityBenchmarkBindingV3,
    VariantOutcomeV3,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

DATABASE_URL = os.getenv("FORWARD_DQV_V20_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="FORWARD_DQV_V20_TEST_DATABASE_URL is not configured",
)

ENROLLMENT_ID = UUID("20000000-0000-4000-8000-000000000002")
PREDECESSOR_LEDGER_ID = UUID("20000000-0000-4000-8000-000000000003")
CUTOFF = datetime(2026, 7, 30, 12, tzinfo=UTC)
HASH = "sha256:" + "a" * 64
COST_HASH = (
    "sha256:2000000000000000000000000000000000000000000000000000000000000010"
)
BENCHMARK_HASH = (
    "sha256:2000000000000000000000000000000000000000000000000000000000000009"
)


def _snake(alias: str) -> str:
    result = ""
    for character in alias:
        result += (
            "_" + character.lower()
            if character.isupper()
            else character
        )
    return result


def _seal(model_type, payload: dict, hash_alias: str):
    provisional = model_type.model_validate(
        {**payload, hash_alias: HASH},
        context={"skip_hash_verification": True},
    )
    body = provisional.model_dump(
        mode="json",
        by_alias=True,
        exclude={_snake(hash_alias)},
    )
    return model_type.model_validate(
        {**body, hash_alias: canonical_hash(body)}
    )


def _assert_isolated_database() -> None:
    assert DATABASE_URL is not None
    database_name = conninfo_to_dict(DATABASE_URL).get("dbname", "")
    if "test" not in database_name.lower():
        raise RuntimeError(
            "FORWARD_DQV_V20_TEST_DATABASE_URL must name an isolated test database"
        )


def _controlled_holding(
    *,
    public_id: UUID,
    symbol: str,
    sector: str | None,
    rank: int,
) -> ControlledBenchmarkHoldingV22:
    payload = {
        "publicSecurityId": str(public_id),
        "symbol": symbol,
        "sector": sector,
        "selectionRank": rank,
        "weightUnits": 1,
        "totalWeightUnits": 2,
        "notional": "100000",
        "averageDailyDollarVolume": (
            "10000000" if rank == 1 else "5000000"
        ),
        "roundTripCostRate": "0.01" if rank == 1 else "0.02",
        "identitySourceHash": HASH,
        "classificationSourceHash": HASH if sector else None,
        "classificationEffectiveAt": "2026-07-29T20:00:00Z" if sector else None,
        "classificationAvailableAt": "2026-07-29T20:01:00Z" if sector else None,
        "classificationIngestedAt": "2026-07-29T20:02:00Z" if sector else None,
        "priceBarsHash": HASH,
        "priceReceiptHash": HASH,
        "controlledPriceArtifactHash": HASH,
        "priceSourceHash": HASH,
        "priceFirstSession": "2025-07-29",
        "priceLastSession": "2026-07-29",
        "priceBarCount": 252,
        "priceAvailableAt": "2026-07-29T20:01:00Z",
        "priceIngestedAt": "2026-07-29T20:02:00Z",
        "selectionEvidenceState": "NOT_APPLICABLE",
        "adjustmentMode": "TOTAL_RETURN_ADJUSTED",
        "actionState": "RECONCILED",
        "adjustmentPolicyVersion": "fixture-v1",
        "actionBindingHash": HASH,
        "actionSourceHash": HASH,
        "actionAvailableAt": "2026-07-29T20:01:00Z",
        "actionIngestedAt": "2026-07-29T20:02:00Z",
        "liquidityAsOfSession": "2026-07-29",
        "liquidityQualityStatus": "VALIDATED",
        "liquidityAvailableAt": "2026-07-29T20:01:00Z",
        "liquidityIngestedAt": "2026-07-29T20:02:00Z",
        "liquiditySourceHash": HASH,
        "costPolicyHash": COST_HASH,
        "inputAvailableAt": "2026-07-29T20:01:00Z",
        "inputIngestedAt": "2026-07-29T20:02:00Z",
    }
    return _seal(
        ControlledBenchmarkHoldingV22,
        payload,
        "holdingContentHash",
    )


def _ledger_envelope(
    securities: list[tuple[UUID, str]],
) -> BenchmarkLedgerPersistenceV3:
    variant_specs = (
        (BenchmarkKind.SPY, "typed-spy", None),
        (BenchmarkKind.SECTOR, "typed-sector-a", "Sector A"),
        (BenchmarkKind.SECTOR, "typed-sector-b", "Sector B"),
        (BenchmarkKind.EQUAL_WEIGHT, "typed-equal-weight", None),
        (BenchmarkKind.PURE_MOMENTUM, "typed-momentum", None),
        (BenchmarkKind.PURE_VALUE, "typed-value", None),
        (BenchmarkKind.PURE_QUALITY, "typed-quality", None),
    )
    variants_by_kind: dict[
        BenchmarkKind,
        list[ControlledBenchmarkVariantV22],
    ] = {}
    for ordinal, (kind, identifier, sector) in enumerate(variant_specs):
        holdings = tuple(
            _controlled_holding(
                public_id=securities[ordinal * 2 + rank - 1][0],
                symbol=securities[ordinal * 2 + rank - 1][1],
                sector=sector,
                rank=rank,
            )
            for rank in (1, 2)
        )
        variant = _seal(
            ControlledBenchmarkVariantV22,
            {
                "identifier": identifier,
                "constructionVersion": "fixture-v1",
                "sector": sector,
                "state": "AVAILABLE",
                "reasonCodes": [],
                "populationCount": 66,
                "eligibleCount": 66,
                "coverageRatio": "1",
                "pathConstruction": "FIXED_WEIGHT_BUY_AND_HOLD",
                "constituentSetHash": HASH,
                "weightHash": HASH,
                "sourceEvidenceHash": HASH,
                "selectionHash": HASH,
                "costEvidenceHash": HASH,
                "sectorAssignmentHash": HASH if sector else None,
                "evidenceHash": HASH,
                "holdings": [
                    item.model_dump(mode="json", by_alias=True)
                    for item in holdings
                ],
            },
            "variantContentHash",
        )
        variants_by_kind.setdefault(kind, []).append(variant)
    families = []
    for kind in BenchmarkKind:
        family = _seal(
            ControlledBenchmarkFamilyV22,
            {
                "kind": kind.value,
                "benchmarkId": f"typed-{kind.value.lower()}",
                "constructionMethod": (
                    "DATED_SECTOR_VARIANTS"
                    if kind == BenchmarkKind.SECTOR
                    else "FROZEN_CONSTITUENT_SET"
                ),
                "state": "AVAILABLE",
                "reasonCodes": [],
                "variants": [
                    item.model_dump(mode="json", by_alias=True)
                    for item in variants_by_kind[kind]
                ],
                "evidenceHash": HASH,
                "sourceEvidenceHash": HASH,
                "constituentSetHash": HASH,
                "weightHash": HASH,
                "selectionHash": HASH,
                "costEvidenceHash": HASH,
                "sectorAssignmentHash": (
                    HASH if kind == BenchmarkKind.SECTOR else None
                ),
                "terminalHash": HASH,
            },
            "familyContentHash",
        )
        families.append(family)
    controlled = _seal(
        ControlledBenchmarkLedgerSetV22,
        {
            "artifactType": "FORWARD_DQV_CONTROLLED_BENCHMARK_PATH_LEDGER",
            "schemaVersion": "FORWARD-DQV-BENCHMARK-PATH-LEDGER-v2.2.0",
            "status": "READY",
            "decisionCompletedSession": "2026-07-29",
            "decisionCutoff": CUTOFF.isoformat(),
            "decisionAsOf": CUTOFF.isoformat(),
            "universeVersion": "forward-dqv-v20-acceptance-v1",
            "universeHash": HASH,
            "populationIdentityBindingHash": HASH,
            "preregistrationSealHash": HASH,
            "futurePriceExecutionHash": HASH,
            "candidateConstructionHash": HASH,
            "benchmarkBundleHash": HASH,
            "benchmarkContractHash": BENCHMARK_HASH,
            "parentLiquidityCostPolicyHash": HASH,
            "costPolicyHash": COST_HASH,
            "familyCount": 6,
            "families": [
                item.model_dump(mode="json", by_alias=True)
                for item in families
            ],
            "providerNetworkRequests": 0,
            "databaseWrites": 0,
            "scoresOrRanksComputed": False,
            "aiMayAffectDeterministicResult": False,
            "humanMayAffectDeterministicResult": False,
            "rawProviderValuesInGitSafeManifest": False,
        },
        "ledgerContentHash",
    )
    variant_id_by_kind = {
        kind: variants_by_kind[kind][0].identifier
        for kind in BenchmarkKind
    }
    bindings = []
    for ordinal, (public_id, _) in enumerate(securities, start=1):
        for kind in BenchmarkKind:
            if kind == BenchmarkKind.SECTOR:
                sector = "Sector A" if ordinal % 2 else "Sector B"
                variant_id = (
                    "typed-sector-a" if ordinal % 2 else "typed-sector-b"
                )
            else:
                sector = None
                variant_id = variant_id_by_kind[kind]
            bindings.append(
                _seal(
                    SecurityBenchmarkBindingV3,
                    {
                        "publicSecurityId": str(public_id),
                        "benchmarkKind": kind.value,
                        "variantId": variant_id,
                        "sectorIdentity": sector,
                        "classificationEffectiveAt": (
                            "2026-07-29T20:00:00Z" if sector else None
                        ),
                        "classificationAvailableAt": (
                            "2026-07-29T20:01:00Z" if sector else None
                        ),
                        "classificationIngestedAt": (
                            "2026-07-29T20:02:00Z" if sector else None
                        ),
                        "classificationSourceHash": HASH if sector else None,
                        "identityBindingHash": HASH,
                    },
                    "bindingContentHash",
                )
            )
    return _seal(
        BenchmarkLedgerPersistenceV3,
        {
            "schemaVersion": BENCHMARK_LEDGER_PERSISTENCE_V3,
            "ledgerId": str(uuid4()),
            "enrollmentId": str(ENROLLMENT_ID),
            "ledgerVersion": 2,
            "supersedesLedgerId": str(PREDECESSOR_LEDGER_ID),
            "classificationPolicyHash": HASH,
            "controlledLedgerReference": "fixture://typed-v20-ledger",
            "sealedAt": "2026-07-30T12:30:00Z",
            "controlledLedger": controlled.model_dump(
                mode="json",
                by_alias=True,
            ),
            "bindings": [
                item.model_dump(mode="json", by_alias=True)
                for item in bindings
            ],
        },
        "persistenceContentHash",
    )


def _outcomes(
    envelope: BenchmarkLedgerPersistenceV3,
    outcome_batch_id: UUID,
) -> BenchmarkOutcomePersistenceV3:
    variants: list[VariantOutcomeV3] = []
    for family in envelope.controlled_ledger.families:
        for controlled_variant in family.variants:
            holdings = []
            for holding in controlled_variant.holdings:
                gross = Decimal("0.10") if holding.selection_rank == 1 else Decimal("0.12")
                cost = holding.round_trip_cost_rate
                weight = Decimal(holding.weight_units) / Decimal(
                    holding.total_weight_units
                )
                holdings.append(
                    _seal(
                        HoldingOutcomeV3,
                        {
                            "publicSecurityId": str(holding.public_security_id),
                            "benchmarkKind": family.kind.value,
                            "variantId": controlled_variant.identifier,
                            "state": "ASSESSED",
                            "frozenWeightUnits": holding.weight_units,
                            "frozenTotalWeightUnits": holding.total_weight_units,
                            "frozenNotional": holding.notional,
                            "frozenAverageDailyDollarVolume": (
                                holding.average_daily_dollar_volume
                            ),
                            "grossReturn": gross,
                            "roundTripCostRate": cost,
                            "weightedGrossContribution": gross * weight,
                            "weightedCostContribution": cost * weight,
                            "weightedNetContribution": (gross - cost) * weight,
                            "priceActionEvidenceHash": HASH,
                            "sourceManifestHash": HASH,
                            "reasonCodes": [],
                        },
                        "outcomeContentHash",
                    )
                )
            variants.append(
                _seal(
                    VariantOutcomeV3,
                    {
                        "benchmarkKind": family.kind.value,
                        "variantId": controlled_variant.identifier,
                        "state": "AVAILABLE",
                        "grossReturn": "0.11",
                        "roundTripCostRate": "0.015",
                        "netReturn": "0.095",
                        "priceActionEvidenceHash": HASH,
                        "sourceManifestHash": HASH,
                        "reasonCodes": [],
                        "holdings": [
                            item.model_dump(mode="json", by_alias=True)
                            for item in holdings
                        ],
                    },
                    "outcomeContentHash",
                )
            )
    families = [
        _seal(
            FamilyOutcomeV3,
            {
                "benchmarkKind": kind.value,
                "aggregationMethod": (
                    "SECURITY_BINDING_WEIGHTED"
                    if kind == BenchmarkKind.SECTOR
                    else "SINGLE_VARIANT"
                ),
                "state": "AVAILABLE",
                "grossReturn": "0.11",
                "roundTripCostRate": "0.015",
                "netReturn": "0.095",
                "sourceManifestHash": HASH,
                "reasonCodes": [],
            },
            "outcomeContentHash",
        )
        for kind in BenchmarkKind
    ]
    return _seal(
        BenchmarkOutcomePersistenceV3,
        {
            "schemaVersion": BENCHMARK_OUTCOME_PERSISTENCE_V3,
            "outcomeBatchId": str(outcome_batch_id),
            "ledgerId": str(envelope.ledger_id),
            "state": "COMPLETE",
            "variants": [
                item.model_dump(mode="json", by_alias=True)
                for item in variants
            ],
            "families": [
                item.model_dump(mode="json", by_alias=True)
                for item in families
            ],
            "bindingContentHash": HASH,
        },
        "persistenceContentHash",
    )


def test_v20_typed_repository_round_trip() -> None:
    _assert_isolated_database()
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT public_id, symbol
            FROM analytics.security
            WHERE exchange = 'V20 TEST'
            ORDER BY symbol
            """
        ).fetchall()
    securities = [(row["public_id"], row["symbol"]) for row in rows]
    assert len(securities) == 66
    envelope = _ledger_envelope(securities)
    repository = ForwardDqvBenchmarkOutcomeRepositoryV3(DATABASE_URL)
    assert repository.persist_ledger(envelope) == envelope.ledger_id
    assert repository.persist_ledger(envelope) == envelope.ledger_id
    assert repository.read_ledger(envelope.ledger_id) == envelope

    outcome_batch_id = uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO analytics.forward_dqv_outcome_batch_v2 (
                id, enrollment_id, completed_sessions, contract_version,
                result_version, supersedes_batch_id, observed_at,
                matured_at_completed_session, evaluation_role,
                operational_completeness, security_count, benchmark_count,
                terminal_counts, preregistration_content_hash,
                decision_manifest_content_hash, frozen_population_hash,
                model_freeze_hashes, benchmark_contract_hash,
                cost_policy_hash, source_manifest_hash,
                calendar_evidence_hash, action_evidence_hash,
                price_evidence_hash, evidence_blockers,
                outcome_batch_content_hash
            )
            SELECT
                %s, enrollment.id, 60, 'FORWARD-DQV-OUTCOME-v2.1.0',
                1, NULL, %s, %s, 'TACTICAL_FORMAL',
                'BLOCKED', enrollment.security_count, 0,
                '{"MISSING":66}'::jsonb,
                enrollment.preregistration_content_hash,
                enrollment.decision_manifest_content_hash,
                enrollment.frozen_population_hash,
                enrollment.model_freeze_hashes,
                enrollment.benchmark_contract_hash,
                enrollment.cost_policy_hash,
                %s, %s, %s, %s,
                '["V20_TYPED_ACCEPTANCE"]'::jsonb, %s
            FROM analytics.forward_dqv_enrollment_v2 enrollment
            WHERE enrollment.id = %s
            """,
            (
                outcome_batch_id,
                CUTOFF + timedelta(days=61),
                CUTOFF + timedelta(days=60),
                canonical_hash({"outcome": str(outcome_batch_id), "source": 1}),
                canonical_hash({"outcome": str(outcome_batch_id), "calendar": 1}),
                canonical_hash({"outcome": str(outcome_batch_id), "action": 1}),
                canonical_hash({"outcome": str(outcome_batch_id), "price": 1}),
                canonical_hash({"outcome": str(outcome_batch_id), "batch": 1}),
                ENROLLMENT_ID,
            ),
        )
    outcomes = _outcomes(envelope, outcome_batch_id)
    assert repository.persist_outcomes(outcomes) == outcome_batch_id
    assert repository.persist_outcomes(outcomes) == outcome_batch_id
    assert repository.read_outcomes(outcome_batch_id) == outcomes
