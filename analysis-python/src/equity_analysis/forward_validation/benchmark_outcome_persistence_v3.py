from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field, ValidationInfo, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_controlled_ledger_v22 import (
    ControlledBenchmarkLedgerSetV22,
)
from equity_analysis.forward_validation.contracts_v2 import ContractModel
from equity_analysis.forward_validation.outcome_persistence_v21 import (
    ForwardDqvPersistenceConflict,
    ForwardDqvPersistenceNotFound,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

BENCHMARK_LEDGER_PERSISTENCE_V3 = (
    "FORWARD-DQV-BENCHMARK-LEDGER-PERSISTENCE-v3.0.0"
)
BENCHMARK_OUTCOME_PERSISTENCE_V3 = (
    "FORWARD-DQV-BENCHMARK-OUTCOME-PERSISTENCE-v3.0.0"
)
_HASH = r"^sha256:[0-9a-f]{64}$"
_EPSILON = Decimal("0.000000000001")
_KINDS = tuple(item.value for item in BenchmarkKind)


def _canonical_decimal(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(format(value.normalize(), "f"))


def _decimal_lexeme(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_decimal_lexeme(value: str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value)


class BenchmarkOutcomePersistenceV3Error(ValueError):
    code = "FORWARD_DQV_BENCHMARK_OUTCOME_V3_INVALID"


class SecurityBenchmarkBindingV3(ContractModel):
    public_security_id: UUID
    benchmark_kind: BenchmarkKind
    variant_id: str = Field(min_length=1)
    sector_identity: str | None = None
    classification_effective_at: datetime | None = None
    classification_available_at: datetime | None = None
    classification_ingested_at: datetime | None = None
    classification_source_hash: str | None = Field(default=None, pattern=_HASH)
    identity_binding_hash: str = Field(pattern=_HASH)
    binding_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_binding(
        self,
        info: ValidationInfo,
    ) -> SecurityBenchmarkBindingV3:
        chronology = (
            self.classification_effective_at,
            self.classification_available_at,
            self.classification_ingested_at,
        )
        if self.benchmark_kind == BenchmarkKind.SECTOR:
            if self.sector_identity is None or not self.sector_identity.strip():
                raise ValueError("SECTOR binding requires a sector identity")
            if any(item is None for item in chronology):
                raise ValueError("SECTOR binding requires dated classification evidence")
            if self.classification_source_hash is None:
                raise ValueError("SECTOR binding requires a classification hash")
        elif (
            self.sector_identity is not None
            or any(item is not None for item in chronology)
            or self.classification_source_hash is not None
        ):
            raise ValueError("Only SECTOR bindings may carry classification evidence")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"binding_content_hash"},
            )
            if canonical_hash(body) != self.binding_content_hash:
                raise ValueError("Security benchmark binding hash is invalid")
        return self


class BenchmarkLedgerPersistenceV3(ContractModel):
    schema_version: Literal[
        "FORWARD-DQV-BENCHMARK-LEDGER-PERSISTENCE-v3.0.0"
    ]
    ledger_id: UUID
    enrollment_id: UUID
    ledger_version: int = Field(ge=1)
    supersedes_ledger_id: UUID | None = None
    classification_policy_hash: str = Field(pattern=_HASH)
    controlled_ledger_reference: str = Field(min_length=1)
    sealed_at: datetime
    controlled_ledger: ControlledBenchmarkLedgerSetV22
    bindings: tuple[SecurityBenchmarkBindingV3, ...] = Field(min_length=1)
    persistence_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_ledger(
        self,
        info: ValidationInfo,
    ) -> BenchmarkLedgerPersistenceV3:
        if (self.ledger_version == 1) != (self.supersedes_ledger_id is None):
            raise ValueError("Benchmark ledger correction shape is invalid")
        if self.sealed_at < self.controlled_ledger.decision_cutoff:
            raise ValueError("Benchmark ledger cannot be sealed before its cutoff")
        variants = {
            (family.kind, variant.identifier)
            for family in self.controlled_ledger.families
            for variant in family.variants
        }
        by_security: dict[UUID, set[BenchmarkKind]] = {}
        seen: set[tuple[UUID, BenchmarkKind]] = set()
        for binding in self.bindings:
            key = (binding.public_security_id, binding.benchmark_kind)
            if key in seen:
                raise ValueError("Security benchmark bindings must be unique")
            seen.add(key)
            by_security.setdefault(binding.public_security_id, set()).add(
                binding.benchmark_kind
            )
            if (binding.benchmark_kind, binding.variant_id) not in variants:
                raise ValueError("Security benchmark binding references an unknown variant")
            if binding.benchmark_kind == BenchmarkKind.SECTOR:
                variant = next(
                    variant
                    for family in self.controlled_ledger.families
                    if family.kind == binding.benchmark_kind
                    for variant in family.variants
                    if variant.identifier == binding.variant_id
                )
                if binding.sector_identity != variant.sector:
                    raise ValueError("SECTOR binding references the wrong dated variant")
            if (
                binding.classification_available_at is not None
                and binding.classification_available_at
                > self.controlled_ledger.decision_cutoff
            ):
                raise ValueError("Security benchmark binding uses future classification")
            if (
                binding.classification_ingested_at is not None
                and binding.classification_ingested_at
                > self.controlled_ledger.decision_cutoff
            ):
                raise ValueError("Security benchmark binding was ingested after cutoff")
        expected = set(BenchmarkKind)
        if any(kinds != expected for kinds in by_security.values()):
            raise ValueError("Every security requires exactly six benchmark bindings")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"persistence_content_hash"},
            )
            if canonical_hash(body) != self.persistence_content_hash:
                raise ValueError("Benchmark ledger persistence hash is invalid")
        return self


class HoldingOutcomeV3(ContractModel):
    public_security_id: UUID
    benchmark_kind: BenchmarkKind
    variant_id: str = Field(min_length=1)
    state: Literal["ASSESSED", "MISSING", "STALE", "INVALID"]
    frozen_weight_units: int = Field(ge=1)
    frozen_total_weight_units: int = Field(ge=1)
    frozen_notional: Decimal = Field(gt=0)
    frozen_average_daily_dollar_volume: Decimal = Field(gt=0)
    gross_return: Decimal | None = None
    round_trip_cost_rate: Decimal | None = None
    weighted_gross_contribution: Decimal | None = None
    weighted_cost_contribution: Decimal | None = None
    weighted_net_contribution: Decimal | None = None
    price_action_evidence_hash: str | None = Field(default=None, pattern=_HASH)
    source_manifest_hash: str | None = Field(default=None, pattern=_HASH)
    reason_codes: tuple[str, ...] = ()
    outcome_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_outcome(self, info: ValidationInfo) -> HoldingOutcomeV3:
        values = (
            self.gross_return,
            self.round_trip_cost_rate,
            self.weighted_gross_contribution,
            self.weighted_cost_contribution,
            self.weighted_net_contribution,
        )
        if self.frozen_weight_units > self.frozen_total_weight_units:
            raise ValueError("Frozen holding weight exceeds the denominator")
        if self.state == "ASSESSED":
            if any(value is None for value in values):
                raise ValueError("ASSESSED holding requires complete values")
            if self.reason_codes:
                raise ValueError("ASSESSED holding cannot have reason codes")
            weight = Decimal(self.frozen_weight_units) / Decimal(
                self.frozen_total_weight_units
            )
            if abs(self.weighted_gross_contribution - self.gross_return * weight) > (
                _EPSILON
            ):
                raise ValueError("Holding gross contribution is not reproducible")
            if abs(
                self.weighted_cost_contribution
                - self.round_trip_cost_rate * weight
            ) > _EPSILON:
                raise ValueError("Holding cost contribution is not reproducible")
            if abs(
                self.weighted_net_contribution
                - (
                    self.weighted_gross_contribution
                    - self.weighted_cost_contribution
                )
            ) > _EPSILON:
                raise ValueError("Holding net contribution is not reproducible")
        elif any(value is not None for value in values) or not self.reason_codes:
            raise ValueError("Unavailable holding must remain explicitly non-numeric")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"outcome_content_hash"},
            )
            if canonical_hash(body) != self.outcome_content_hash:
                raise ValueError("Holding outcome hash is invalid")
        return self


class VariantOutcomeV3(ContractModel):
    benchmark_kind: BenchmarkKind
    variant_id: str = Field(min_length=1)
    state: Literal["AVAILABLE", "MISSING", "STALE", "INVALID"]
    gross_return: Decimal | None = None
    round_trip_cost_rate: Decimal | None = None
    net_return: Decimal | None = None
    price_action_evidence_hash: str | None = Field(default=None, pattern=_HASH)
    source_manifest_hash: str | None = Field(default=None, pattern=_HASH)
    reason_codes: tuple[str, ...] = ()
    holdings: tuple[HoldingOutcomeV3, ...]
    outcome_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_outcome(self, info: ValidationInfo) -> VariantOutcomeV3:
        keys = tuple(item.public_security_id for item in self.holdings)
        if len(set(keys)) != len(keys):
            raise ValueError("Variant holding outcomes must be unique")
        if any(
            item.benchmark_kind != self.benchmark_kind
            or item.variant_id != self.variant_id
            for item in self.holdings
        ):
            raise ValueError("Variant holding outcome binding changed")
        if self.state == "AVAILABLE":
            if not self.holdings or any(
                item.state != "ASSESSED" for item in self.holdings
            ):
                raise ValueError("AVAILABLE variant requires assessed holdings")
            gross = sum(
                (item.weighted_gross_contribution for item in self.holdings),
                Decimal(0),
            )
            cost = sum(
                (item.weighted_cost_contribution for item in self.holdings),
                Decimal(0),
            )
            net = sum(
                (item.weighted_net_contribution for item in self.holdings),
                Decimal(0),
            )
            if (
                self.gross_return is None
                or self.round_trip_cost_rate is None
                or self.net_return is None
                or abs(self.gross_return - gross) > _EPSILON
                or abs(self.round_trip_cost_rate - cost) > _EPSILON
                or abs(self.net_return - net) > _EPSILON
            ):
                raise ValueError("Variant outcome does not equal holding contributions")
            if self.reason_codes:
                raise ValueError("AVAILABLE variant cannot carry reason codes")
        elif self.holdings or any(
            value is not None
            for value in (
                self.gross_return,
                self.round_trip_cost_rate,
                self.net_return,
            )
        ) or not self.reason_codes:
            raise ValueError("Unavailable variant must remain explicitly non-numeric")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"outcome_content_hash"},
            )
            if canonical_hash(body) != self.outcome_content_hash:
                raise ValueError("Variant outcome hash is invalid")
        return self


class FamilyOutcomeV3(ContractModel):
    benchmark_kind: BenchmarkKind
    aggregation_method: Literal[
        "SINGLE_VARIANT", "SECURITY_BINDING_WEIGHTED"
    ]
    state: Literal["AVAILABLE", "MISSING", "STALE", "INVALID"]
    gross_return: Decimal | None = None
    round_trip_cost_rate: Decimal | None = None
    net_return: Decimal | None = None
    source_manifest_hash: str | None = Field(default=None, pattern=_HASH)
    reason_codes: tuple[str, ...] = ()
    outcome_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_outcome(self, info: ValidationInfo) -> FamilyOutcomeV3:
        if self.benchmark_kind == BenchmarkKind.SECTOR:
            if self.aggregation_method != "SECURITY_BINDING_WEIGHTED":
                raise ValueError("SECTOR family requires security-binding aggregation")
        elif self.aggregation_method != "SINGLE_VARIANT":
            raise ValueError("Non-sector family requires its sole variant")
        values = (
            self.gross_return,
            self.round_trip_cost_rate,
            self.net_return,
        )
        if self.state == "AVAILABLE":
            if any(value is None for value in values) or self.reason_codes:
                raise ValueError("AVAILABLE family requires values and no reasons")
            if abs(
                self.net_return - (self.gross_return - self.round_trip_cost_rate)
            ) > _EPSILON:
                raise ValueError("Family net return is not reproducible")
        elif any(value is not None for value in values) or not self.reason_codes:
            raise ValueError("Unavailable family must remain explicitly non-numeric")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"outcome_content_hash"},
            )
            if canonical_hash(body) != self.outcome_content_hash:
                raise ValueError("Family outcome hash is invalid")
        return self


class BenchmarkOutcomePersistenceV3(ContractModel):
    schema_version: Literal[
        "FORWARD-DQV-BENCHMARK-OUTCOME-PERSISTENCE-v3.0.0"
    ]
    outcome_batch_id: UUID
    ledger_id: UUID
    state: Literal["COMPLETE", "BLOCKED"]
    variants: tuple[VariantOutcomeV3, ...]
    families: tuple[FamilyOutcomeV3, ...]
    binding_content_hash: str = Field(pattern=_HASH)
    persistence_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_outcomes(
        self,
        info: ValidationInfo,
    ) -> BenchmarkOutcomePersistenceV3:
        family_kinds = tuple(item.benchmark_kind for item in self.families)
        if len(family_kinds) != 6 or set(family_kinds) != set(BenchmarkKind):
            raise ValueError("Benchmark outcome requires the exact six families")
        if len(set(family_kinds)) != 6:
            raise ValueError("Benchmark outcome families must be unique")
        variant_keys = tuple(
            (item.benchmark_kind, item.variant_id) for item in self.variants
        )
        if len(set(variant_keys)) != len(variant_keys):
            raise ValueError("Benchmark variant outcomes must be unique")
        if self.state == "COMPLETE" and (
            any(item.state != "AVAILABLE" for item in self.families)
            or any(item.state != "AVAILABLE" for item in self.variants)
        ):
            raise ValueError("COMPLETE benchmark outcome cannot hide missing evidence")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"persistence_content_hash"},
            )
            if canonical_hash(body) != self.persistence_content_hash:
                raise ValueError("Benchmark outcome persistence hash is invalid")
        return self


class ForwardDqvBenchmarkOutcomeRepositoryV3:
    """Strict V20 read/write port; V18/V19 repositories remain unchanged."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self.database_url = database_url

    def persist_ledger(self, envelope: BenchmarkLedgerPersistenceV3) -> UUID:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            existing = connection.execute(
                """
                SELECT id, persistence_content_hash
                FROM analytics.forward_dqv_benchmark_ledger_v3
                WHERE id = %s
                   OR (enrollment_id = %s AND ledger_version = %s)
                ORDER BY CASE WHEN id = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (
                    envelope.ledger_id,
                    envelope.enrollment_id,
                    envelope.ledger_version,
                    envelope.ledger_id,
                ),
            ).fetchone()
            if existing is not None:
                if (
                    existing["persistence_content_hash"]
                    != envelope.persistence_content_hash
                ):
                    raise ForwardDqvPersistenceConflict(
                        "Benchmark ledger idempotency hash differs"
                    )
                if self.read_ledger(envelope.ledger_id) != envelope:
                    raise ForwardDqvPersistenceConflict(
                        "Benchmark ledger hash matched but payload differed"
                    )
                return existing["id"]
            self._insert_ledger(connection, envelope)
        return envelope.ledger_id

    def read_ledger(self, ledger_id: UUID) -> BenchmarkLedgerPersistenceV3:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            header = connection.execute(
                """
                SELECT *
                FROM analytics.forward_dqv_benchmark_ledger_v3
                WHERE id = %s
                """,
                (ledger_id,),
            ).fetchone()
            if header is None:
                raise ForwardDqvPersistenceNotFound(
                    "Forward DQV benchmark ledger v3 was not found"
                )
            families = connection.execute(
                """
                SELECT *
                FROM analytics.forward_dqv_benchmark_family_v3
                WHERE ledger_id = %s
                ORDER BY family_ordinal
                """,
                (ledger_id,),
            ).fetchall()
            variants = connection.execute(
                """
                SELECT *
                FROM analytics.forward_dqv_benchmark_variant_v3
                WHERE ledger_id = %s
                ORDER BY benchmark_kind, variant_ordinal
                """,
                (ledger_id,),
            ).fetchall()
            holdings = connection.execute(
                """
                SELECT *
                FROM analytics.forward_dqv_benchmark_holding_v3
                WHERE ledger_id = %s
                ORDER BY benchmark_kind, variant_id, selection_rank
                """,
                (ledger_id,),
            ).fetchall()
            bindings = connection.execute(
                """
                SELECT *
                FROM analytics.forward_dqv_security_benchmark_binding_v3
                WHERE ledger_id = %s
                ORDER BY binding_ordinal
                """,
                (ledger_id,),
            ).fetchall()
        if len(families) != 6:
            raise ForwardDqvPersistenceConflict(
                "V20 benchmark ledger does not contain six families"
            )
        if len(bindings) == 0 or len(bindings) % 6:
            raise ForwardDqvPersistenceConflict(
                "V20 benchmark ledger binding coverage is incomplete"
            )
        binding_kinds: dict[UUID, set[str]] = {}
        for binding in bindings:
            binding_kinds.setdefault(binding["public_security_id"], set()).add(
                binding["benchmark_kind"]
            )
        if any(kinds != set(_KINDS) for kinds in binding_kinds.values()):
            raise ForwardDqvPersistenceConflict(
                "V20 benchmark ledger does not bind every security to six families"
            )
        variants_by_family: dict[str, list[dict[str, Any]]] = {}
        holdings_by_variant: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for holding in holdings:
            holdings_by_variant.setdefault(
                (holding["benchmark_kind"], holding["variant_id"]),
                [],
            ).append(holding)
        for variant in variants:
            controlled_holdings = []
            for holding in holdings_by_variant.get(
                (variant["benchmark_kind"], variant["variant_id"]),
                [],
            ):
                controlled_holdings.append(
                    {
                        "publicSecurityId": holding["public_security_id"],
                        "symbol": holding["symbol"],
                        "sector": holding["sector"],
                        "selectionRank": holding["selection_rank"],
                        "weightUnits": holding["weight_units"],
                        "totalWeightUnits": holding["total_weight_units"],
                        "notional": Decimal(holding["notional_lexeme"]),
                        "averageDailyDollarVolume": Decimal(
                            holding["average_daily_dollar_volume_lexeme"]
                        ),
                        "roundTripCostRate": Decimal(
                            holding["round_trip_cost_rate_lexeme"]
                        ),
                        "identitySourceHash": holding["identity_source_hash"],
                        "classificationSourceHash": holding[
                            "classification_source_hash"
                        ],
                        "classificationEffectiveAt": holding[
                            "classification_effective_at"
                        ],
                        "classificationAvailableAt": holding[
                            "classification_available_at"
                        ],
                        "classificationIngestedAt": holding[
                            "classification_ingested_at"
                        ],
                        "priceBarsHash": holding["price_bars_hash"],
                        "priceReceiptHash": holding["price_receipt_hash"],
                        "controlledPriceArtifactHash": holding[
                            "controlled_price_artifact_hash"
                        ],
                        "priceSourceHash": holding["price_source_hash"],
                        "priceFirstSession": holding["price_first_session"],
                        "priceLastSession": holding["price_last_session"],
                        "priceBarCount": holding["price_bar_count"],
                        "priceAvailableAt": holding["price_available_at"],
                        "priceIngestedAt": holding["price_ingested_at"],
                        "selectionEvidenceState": holding[
                            "selection_evidence_state"
                        ],
                        "selectionEvidenceVersion": holding[
                            "selection_evidence_version"
                        ],
                        "selectionLineageHash": holding[
                            "selection_lineage_hash"
                        ],
                        "selectionSourceHash": holding["selection_source_hash"],
                        "selectionAvailableAt": holding[
                            "selection_available_at"
                        ],
                        "selectionIngestedAt": holding[
                            "selection_ingested_at"
                        ],
                        "adjustmentMode": holding["adjustment_mode"],
                        "actionState": "RECONCILED",
                        "adjustmentPolicyVersion": holding[
                            "adjustment_policy_version"
                        ],
                        "actionBindingHash": holding["action_binding_hash"],
                        "actionSourceHash": holding["action_source_hash"],
                        "actionAvailableAt": holding["action_available_at"],
                        "actionIngestedAt": holding["action_ingested_at"],
                        "liquidityAsOfSession": holding[
                            "liquidity_as_of_session"
                        ],
                        "liquidityQualityStatus": holding[
                            "liquidity_quality_status"
                        ],
                        "liquidityAvailableAt": holding[
                            "liquidity_available_at"
                        ],
                        "liquidityIngestedAt": holding[
                            "liquidity_ingested_at"
                        ],
                        "liquiditySourceHash": holding["liquidity_source_hash"],
                        "costPolicyHash": holding["cost_policy_hash"],
                        "inputAvailableAt": holding["input_available_at"],
                        "inputIngestedAt": holding["input_ingested_at"],
                        "holdingContentHash": holding["holding_content_hash"],
                    }
                )
            variants_by_family.setdefault(variant["benchmark_kind"], []).append(
                {
                    "identifier": variant["variant_id"],
                    "constructionVersion": variant["construction_version"],
                    "sector": variant["sector_identity"],
                    "state": variant["state"],
                    "reasonCodes": tuple(variant["reason_codes"]),
                    "populationCount": variant["population_count"],
                    "eligibleCount": variant["eligible_count"],
                    "coverageRatio": Decimal(variant["coverage_ratio_lexeme"]),
                    "pathConstruction": variant["path_construction"],
                    "constituentSetHash": variant["constituent_set_hash"],
                    "weightHash": variant["weight_hash"],
                    "sourceEvidenceHash": variant["source_evidence_hash"],
                    "selectionHash": variant["selection_hash"],
                    "costEvidenceHash": variant["cost_evidence_hash"],
                    "sectorAssignmentHash": variant["sector_assignment_hash"],
                    "evidenceHash": variant["evidence_hash"],
                    "holdings": controlled_holdings,
                    "variantContentHash": variant["variant_content_hash"],
                }
            )
        controlled_families = [
            {
                "kind": family["benchmark_kind"],
                "benchmarkId": family["benchmark_identifier"],
                "constructionMethod": family["construction_method"],
                "state": family["state"],
                "reasonCodes": tuple(family["reason_codes"]),
                "variants": variants_by_family.get(
                    family["benchmark_kind"],
                    [],
                ),
                "evidenceHash": family["evidence_hash"],
                "sourceEvidenceHash": family["source_evidence_hash"],
                "constituentSetHash": family["constituent_set_hash"],
                "weightHash": family["weight_hash"],
                "selectionHash": family["selection_hash"],
                "costEvidenceHash": family["cost_evidence_hash"],
                "sectorAssignmentHash": family["sector_assignment_hash"],
                "terminalHash": family["terminal_hash"],
                "familyContentHash": family["family_content_hash"],
            }
            for family in families
        ]
        controlled = {
            "artifactType": "FORWARD_DQV_CONTROLLED_BENCHMARK_PATH_LEDGER",
            "schemaVersion": "FORWARD-DQV-BENCHMARK-PATH-LEDGER-v2.2.0",
            "status": "READY",
            "decisionCompletedSession": header["decision_completed_session"],
            "decisionCutoff": header["decision_cutoff"],
            "decisionAsOf": header["decision_cutoff"],
            "universeVersion": header["universe_version"],
            "universeHash": header["universe_hash"],
            "populationIdentityBindingHash": header[
                "population_identity_binding_hash"
            ],
            "preregistrationSealHash": header["preregistration_seal_hash"],
            "futurePriceExecutionHash": header["future_price_execution_hash"],
            "candidateConstructionHash": header["candidate_construction_hash"],
            "benchmarkBundleHash": header["benchmark_bundle_hash"],
            "benchmarkContractHash": header["benchmark_contract_hash"],
            "parentLiquidityCostPolicyHash": header[
                "parent_liquidity_cost_policy_hash"
            ],
            "costPolicyHash": header["cost_policy_hash"],
            "familyCount": header["family_count"],
            "families": controlled_families,
            "providerNetworkRequests": header["provider_network_requests"],
            "databaseWrites": header["source_database_writes"],
            "scoresOrRanksComputed": header["scores_or_ranks_computed"],
            "aiMayAffectDeterministicResult": header[
                "ai_may_affect_deterministic_result"
            ],
            "humanMayAffectDeterministicResult": header[
                "human_may_affect_deterministic_result"
            ],
            "rawProviderValuesInGitSafeManifest": header[
                "raw_provider_values_in_git_safe_manifest"
            ],
            "ledgerContentHash": header["ledger_content_hash"],
        }
        return BenchmarkLedgerPersistenceV3.model_validate(
            {
                "schemaVersion": BENCHMARK_LEDGER_PERSISTENCE_V3,
                "ledgerId": header["id"],
                "enrollmentId": header["enrollment_id"],
                "ledgerVersion": header["ledger_version"],
                "supersedesLedgerId": header["supersedes_ledger_id"],
                "classificationPolicyHash": header[
                    "classification_policy_hash"
                ],
                "controlledLedgerReference": header[
                    "controlled_ledger_reference"
                ],
                "sealedAt": header["sealed_at"],
                "controlledLedger": controlled,
                "bindings": [
                    {
                        "publicSecurityId": binding["public_security_id"],
                        "benchmarkKind": binding["benchmark_kind"],
                        "variantId": binding["variant_id"],
                        "sectorIdentity": binding["sector_identity"],
                        "classificationEffectiveAt": binding[
                            "classification_effective_at"
                        ],
                        "classificationAvailableAt": binding[
                            "classification_available_at"
                        ],
                        "classificationIngestedAt": binding[
                            "classification_ingested_at"
                        ],
                        "classificationSourceHash": binding[
                            "classification_source_hash"
                        ],
                        "identityBindingHash": binding[
                            "identity_binding_hash"
                        ],
                        "bindingContentHash": binding["binding_content_hash"],
                    }
                    for binding in bindings
                ],
                "persistenceContentHash": header["persistence_content_hash"],
            }
        )

    def persist_outcomes(self, envelope: BenchmarkOutcomePersistenceV3) -> UUID:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            existing = connection.execute(
                """
                SELECT outcome_batch_id, persistence_content_hash
                FROM analytics.forward_dqv_outcome_ledger_binding_v3
                WHERE outcome_batch_id = %s
                """,
                (envelope.outcome_batch_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["persistence_content_hash"]
                    != envelope.persistence_content_hash
                ):
                    raise ForwardDqvPersistenceConflict(
                        "Benchmark outcome binding hash differs"
                    )
                if self.read_outcomes(envelope.outcome_batch_id) != envelope:
                    raise ForwardDqvPersistenceConflict(
                        "Benchmark outcome hash matched but payload differed"
                    )
                return existing["outcome_batch_id"]
            self._insert_outcomes(connection, envelope)
        return envelope.outcome_batch_id

    def read_outcomes(
        self,
        outcome_batch_id: UUID,
    ) -> BenchmarkOutcomePersistenceV3:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            header = connection.execute(
                """
                SELECT *
                FROM analytics.forward_dqv_outcome_ledger_binding_v3
                WHERE outcome_batch_id = %s
                """,
                (outcome_batch_id,),
            ).fetchone()
            if header is None:
                raise ForwardDqvPersistenceNotFound(
                    "Forward DQV benchmark outcome v3 was not found"
                )
            families = connection.execute(
                """
                SELECT outcome.*
                FROM analytics.forward_dqv_benchmark_family_outcome_v3 outcome
                JOIN analytics.forward_dqv_benchmark_family_v3 family
                  ON family.ledger_id = outcome.ledger_id
                 AND family.benchmark_kind = outcome.benchmark_kind
                WHERE outcome.outcome_batch_id = %s
                ORDER BY family.family_ordinal
                """,
                (outcome_batch_id,),
            ).fetchall()
            variants = connection.execute(
                """
                SELECT outcome.*
                FROM analytics.forward_dqv_benchmark_variant_outcome_v3 outcome
                JOIN analytics.forward_dqv_benchmark_family_v3 family
                  ON family.ledger_id = outcome.ledger_id
                 AND family.benchmark_kind = outcome.benchmark_kind
                JOIN analytics.forward_dqv_benchmark_variant_v3 variant
                  ON variant.ledger_id = outcome.ledger_id
                 AND variant.benchmark_kind = outcome.benchmark_kind
                 AND variant.variant_id = outcome.variant_id
                WHERE outcome.outcome_batch_id = %s
                ORDER BY family.family_ordinal, variant.variant_ordinal
                """,
                (outcome_batch_id,),
            ).fetchall()
            holdings = connection.execute(
                """
                SELECT outcome.*
                FROM analytics.forward_dqv_benchmark_holding_outcome_v3 outcome
                JOIN analytics.forward_dqv_benchmark_family_v3 family
                  ON family.ledger_id = outcome.ledger_id
                 AND family.benchmark_kind = outcome.benchmark_kind
                JOIN analytics.forward_dqv_benchmark_variant_v3 variant
                  ON variant.ledger_id = outcome.ledger_id
                 AND variant.benchmark_kind = outcome.benchmark_kind
                 AND variant.variant_id = outcome.variant_id
                JOIN analytics.forward_dqv_benchmark_holding_v3 holding
                  ON holding.ledger_id = outcome.ledger_id
                 AND holding.benchmark_kind = outcome.benchmark_kind
                 AND holding.variant_id = outcome.variant_id
                 AND holding.holding_security_id = outcome.holding_security_id
                WHERE outcome.outcome_batch_id = %s
                ORDER BY family.family_ordinal, variant.variant_ordinal,
                         holding.selection_rank
                """,
                (outcome_batch_id,),
            ).fetchall()
        if header["state"] == "COMPLETE" and len(families) != 6:
            raise ForwardDqvPersistenceConflict(
                "V20 complete benchmark outcome lacks six family rows"
            )
        holdings_by_variant: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for holding in holdings:
            holdings_by_variant.setdefault(
                (holding["benchmark_kind"], holding["variant_id"]),
                [],
            ).append(holding)
        return BenchmarkOutcomePersistenceV3.model_validate(
            {
                "schemaVersion": BENCHMARK_OUTCOME_PERSISTENCE_V3,
                "outcomeBatchId": header["outcome_batch_id"],
                "ledgerId": header["ledger_id"],
                "state": header["state"],
                "variants": [
                    {
                        "benchmarkKind": variant["benchmark_kind"],
                        "variantId": variant["variant_id"],
                        "state": variant["state"],
                        "grossReturn": _optional_decimal_lexeme(
                            variant["gross_return_lexeme"]
                        ),
                        "roundTripCostRate": _optional_decimal_lexeme(
                            variant["round_trip_cost_rate_lexeme"]
                        ),
                        "netReturn": _optional_decimal_lexeme(
                            variant["net_return_lexeme"]
                        ),
                        "priceActionEvidenceHash": variant[
                            "price_action_evidence_hash"
                        ],
                        "sourceManifestHash": variant["source_manifest_hash"],
                        "reasonCodes": tuple(variant["reason_codes"]),
                        "holdings": [
                            {
                                "publicSecurityId": holding[
                                    "public_security_id"
                                ],
                                "benchmarkKind": holding["benchmark_kind"],
                                "variantId": holding["variant_id"],
                                "state": holding["state"],
                                "frozenWeightUnits": holding[
                                    "frozen_weight_units"
                                ],
                                "frozenTotalWeightUnits": holding[
                                    "frozen_total_weight_units"
                                ],
                                "frozenNotional": Decimal(
                                    holding["frozen_notional_lexeme"]
                                ),
                                "frozenAverageDailyDollarVolume": (
                                    Decimal(
                                        holding[
                                            "frozen_average_daily_dollar_volume_lexeme"
                                        ]
                                    )
                                ),
                                "grossReturn": _optional_decimal_lexeme(
                                    holding["gross_return_lexeme"]
                                ),
                                "roundTripCostRate": _optional_decimal_lexeme(
                                    holding["round_trip_cost_rate_lexeme"]
                                ),
                                "weightedGrossContribution": _optional_decimal_lexeme(
                                    holding[
                                        "weighted_gross_contribution_lexeme"
                                    ]
                                ),
                                "weightedCostContribution": _optional_decimal_lexeme(
                                    holding[
                                        "weighted_cost_contribution_lexeme"
                                    ]
                                ),
                                "weightedNetContribution": _optional_decimal_lexeme(
                                    holding[
                                        "weighted_net_contribution_lexeme"
                                    ]
                                ),
                                "priceActionEvidenceHash": holding[
                                    "price_action_evidence_hash"
                                ],
                                "sourceManifestHash": holding[
                                    "source_manifest_hash"
                                ],
                                "reasonCodes": tuple(holding["reason_codes"]),
                                "outcomeContentHash": holding[
                                    "outcome_content_hash"
                                ],
                            }
                            for holding in holdings_by_variant.get(
                                (
                                    variant["benchmark_kind"],
                                    variant["variant_id"],
                                ),
                                [],
                            )
                        ],
                        "outcomeContentHash": variant["outcome_content_hash"],
                    }
                    for variant in variants
                ],
                "families": [
                    {
                        "benchmarkKind": family["benchmark_kind"],
                        "aggregationMethod": family["aggregation_method"],
                        "state": family["state"],
                        "grossReturn": _optional_decimal_lexeme(
                            family["gross_return_lexeme"]
                        ),
                        "roundTripCostRate": _optional_decimal_lexeme(
                            family["round_trip_cost_rate_lexeme"]
                        ),
                        "netReturn": _optional_decimal_lexeme(
                            family["net_return_lexeme"]
                        ),
                        "sourceManifestHash": family["source_manifest_hash"],
                        "reasonCodes": tuple(family["reason_codes"]),
                        "outcomeContentHash": family["outcome_content_hash"],
                    }
                    for family in families
                ],
                "bindingContentHash": header["binding_content_hash"],
                "persistenceContentHash": header["persistence_content_hash"],
            }
        )

    @staticmethod
    def _security_ids(
        connection: psycopg.Connection[dict[str, Any]],
        public_ids: set[UUID],
    ) -> dict[UUID, int]:
        rows = connection.execute(
            """
            SELECT id, public_id
            FROM analytics.security
            WHERE public_id = ANY(%s)
            """,
            (list(public_ids),),
        ).fetchall()
        result = {item["public_id"]: item["id"] for item in rows}
        if set(result) != public_ids:
            raise ForwardDqvPersistenceConflict(
                "Benchmark ledger references unknown security identities"
            )
        return result

    def _insert_ledger(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        envelope: BenchmarkLedgerPersistenceV3,
    ) -> None:
        controlled = envelope.controlled_ledger
        public_ids = {item.public_security_id for item in envelope.bindings}
        public_ids.update(
            holding.public_security_id
            for family in controlled.families
            for variant in family.variants
            for holding in variant.holdings
        )
        security_ids = self._security_ids(connection, public_ids)
        connection.execute(
            """
            INSERT INTO analytics.forward_dqv_benchmark_ledger_v3 (
                id, enrollment_id, ledger_version, supersedes_ledger_id,
                contract_version, decision_completed_session, decision_cutoff,
                universe_version, universe_hash, population_identity_binding_hash,
                preregistration_seal_hash, future_price_execution_hash,
                candidate_construction_hash, benchmark_bundle_hash,
                benchmark_contract_hash, parent_liquidity_cost_policy_hash,
                cost_policy_hash,
                classification_policy_hash, controlled_ledger_reference,
                family_count, provider_network_requests,
                source_database_writes, scores_or_ranks_computed,
                ai_may_affect_deterministic_result,
                human_may_affect_deterministic_result,
                raw_provider_values_in_git_safe_manifest,
                ledger_content_hash, persistence_content_hash, sealed_at
            ) VALUES (
                %s, %s, %s, %s, 'FORWARD-DQV-BENCHMARK-OUTCOME-LEDGER-v3.0.0',
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            """,
            (
                envelope.ledger_id,
                envelope.enrollment_id,
                envelope.ledger_version,
                envelope.supersedes_ledger_id,
                controlled.decision_completed_session,
                controlled.decision_cutoff,
                controlled.universe_version,
                controlled.universe_hash,
                controlled.population_identity_binding_hash,
                controlled.preregistration_seal_hash,
                controlled.future_price_execution_hash,
                controlled.candidate_construction_hash,
                controlled.benchmark_bundle_hash,
                controlled.benchmark_contract_hash,
                controlled.parent_liquidity_cost_policy_hash,
                controlled.cost_policy_hash,
                envelope.classification_policy_hash,
                envelope.controlled_ledger_reference,
                controlled.family_count,
                controlled.provider_network_requests,
                controlled.database_writes,
                controlled.scores_or_ranks_computed,
                controlled.ai_may_affect_deterministic_result,
                controlled.human_may_affect_deterministic_result,
                controlled.raw_provider_values_in_git_safe_manifest,
                controlled.ledger_content_hash,
                envelope.persistence_content_hash,
                envelope.sealed_at,
            ),
        )
        for family_ordinal, family in enumerate(
            controlled.families,
            start=1,
        ):
            connection.execute(
                """
                INSERT INTO analytics.forward_dqv_benchmark_family_v3 (
                    ledger_id, family_ordinal, benchmark_kind,
                    benchmark_identifier,
                    construction_method, state, variant_count, reason_codes,
                    evidence_hash, source_evidence_hash, constituent_set_hash,
                    weight_hash, selection_hash, cost_evidence_hash,
                    sector_assignment_hash, terminal_hash, family_content_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                """,
                (
                    envelope.ledger_id,
                    family_ordinal,
                    family.kind.value,
                    family.benchmark_id,
                    family.construction_method,
                    family.state.value,
                    len(family.variants),
                    Jsonb(list(family.reason_codes)),
                    family.evidence_hash,
                    family.source_evidence_hash,
                    family.constituent_set_hash,
                    family.weight_hash,
                    family.selection_hash,
                    family.cost_evidence_hash,
                    family.sector_assignment_hash,
                    family.terminal_hash,
                    family.family_content_hash,
                ),
            )
            for variant_ordinal, variant in enumerate(
                family.variants,
                start=1,
            ):
                connection.execute(
                    """
                    INSERT INTO analytics.forward_dqv_benchmark_variant_v3 (
                        ledger_id, benchmark_kind, variant_ordinal,
                        variant_id, sector_identity,
                        construction_version, state, path_construction,
                        population_count, eligible_count, coverage_ratio,
                        coverage_ratio_lexeme, holding_count,
                        total_weight_units, reason_codes,
                        constituent_set_hash, weight_hash, selection_hash,
                        cost_evidence_hash, sector_assignment_hash,
                        source_evidence_hash, evidence_hash, variant_content_hash
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s
                    )
                    """,
                    (
                        envelope.ledger_id,
                        family.kind.value,
                        variant_ordinal,
                        variant.identifier,
                        variant.sector,
                        variant.construction_version,
                        variant.state.value,
                        variant.path_construction,
                        variant.population_count,
                        variant.eligible_count,
                        variant.coverage_ratio,
                        _decimal_lexeme(variant.coverage_ratio),
                        len(variant.holdings),
                        (
                            variant.holdings[0].total_weight_units
                            if variant.holdings
                            else None
                        ),
                        Jsonb(list(variant.reason_codes)),
                        variant.constituent_set_hash,
                        variant.weight_hash,
                        variant.selection_hash,
                        variant.cost_evidence_hash,
                        variant.sector_assignment_hash,
                        variant.source_evidence_hash,
                        variant.evidence_hash,
                        variant.variant_content_hash,
                    ),
                )
                for holding in variant.holdings:
                    participation_rate = (
                        holding.notional
                        / holding.average_daily_dollar_volume
                    )
                    connection.execute(
                        """
                        INSERT INTO analytics.forward_dqv_benchmark_holding_v3 (
                            ledger_id, benchmark_kind, variant_id,
                            holding_security_id, public_security_id, symbol, sector,
                            selection_rank, weight_units, total_weight_units,
                            notional, notional_lexeme,
                            average_daily_dollar_volume,
                            average_daily_dollar_volume_lexeme,
                            participation_rate, participation_rate_lexeme,
                            round_trip_cost_rate, round_trip_cost_rate_lexeme,
                            identity_source_hash, classification_effective_at,
                            classification_available_at,
                            classification_ingested_at,
                            classification_source_hash, price_available_at,
                            price_ingested_at, price_bars_hash, price_receipt_hash,
                            controlled_price_artifact_hash, price_source_hash,
                            price_first_session, price_last_session,
                            price_bar_count, action_available_at,
                            action_ingested_at, action_source_hash,
                            action_binding_hash, adjustment_mode,
                            adjustment_policy_version, liquidity_as_of_session,
                            liquidity_available_at, liquidity_ingested_at,
                            liquidity_source_hash, liquidity_quality_status,
                            selection_evidence_state,
                            selection_evidence_version, selection_lineage_hash,
                            selection_available_at, selection_ingested_at,
                            selection_source_hash, input_available_at,
                            input_ingested_at, cost_policy_hash,
                            holding_content_hash
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s
                        )
                        """,
                        (
                            envelope.ledger_id,
                            family.kind.value,
                            variant.identifier,
                            security_ids[holding.public_security_id],
                            holding.public_security_id,
                            holding.symbol,
                            holding.sector,
                            holding.selection_rank,
                            holding.weight_units,
                            holding.total_weight_units,
                            holding.notional,
                            _decimal_lexeme(holding.notional),
                            holding.average_daily_dollar_volume,
                            _decimal_lexeme(
                                holding.average_daily_dollar_volume
                            ),
                            participation_rate,
                            _decimal_lexeme(participation_rate),
                            holding.round_trip_cost_rate,
                            _decimal_lexeme(holding.round_trip_cost_rate),
                            holding.identity_source_hash,
                            holding.classification_effective_at,
                            holding.classification_available_at,
                            holding.classification_ingested_at,
                            holding.classification_source_hash,
                            holding.price_available_at,
                            holding.price_ingested_at,
                            holding.price_bars_hash,
                            holding.price_receipt_hash,
                            holding.controlled_price_artifact_hash,
                            holding.price_source_hash,
                            holding.price_first_session,
                            holding.price_last_session,
                            holding.price_bar_count,
                            holding.action_available_at,
                            holding.action_ingested_at,
                            holding.action_source_hash,
                            holding.action_binding_hash,
                            holding.adjustment_mode,
                            holding.adjustment_policy_version,
                            holding.liquidity_as_of_session,
                            holding.liquidity_available_at,
                            holding.liquidity_ingested_at,
                            holding.liquidity_source_hash,
                            holding.liquidity_quality_status,
                            holding.selection_evidence_state,
                            holding.selection_evidence_version,
                            holding.selection_lineage_hash,
                            holding.selection_available_at,
                            holding.selection_ingested_at,
                            holding.selection_source_hash,
                            holding.input_available_at,
                            holding.input_ingested_at,
                            holding.cost_policy_hash,
                            holding.holding_content_hash,
                        ),
                    )
        for binding_ordinal, binding in enumerate(
            envelope.bindings,
            start=1,
        ):
            connection.execute(
                """
                INSERT INTO analytics.forward_dqv_security_benchmark_binding_v3 (
                    ledger_id, binding_ordinal, security_id,
                    public_security_id, benchmark_kind, variant_id,
                    sector_identity, classification_effective_at,
                    classification_available_at, classification_ingested_at,
                    classification_source_hash, identity_binding_hash,
                    binding_content_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s
                )
                """,
                (
                    envelope.ledger_id,
                    binding_ordinal,
                    security_ids[binding.public_security_id],
                    binding.public_security_id,
                    binding.benchmark_kind.value,
                    binding.variant_id,
                    binding.sector_identity,
                    binding.classification_effective_at,
                    binding.classification_available_at,
                    binding.classification_ingested_at,
                    binding.classification_source_hash,
                    binding.identity_binding_hash,
                    binding.binding_content_hash,
                ),
            )

    def _insert_outcomes(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        envelope: BenchmarkOutcomePersistenceV3,
    ) -> None:
        public_ids = {
            holding.public_security_id
            for variant in envelope.variants
            for holding in variant.holdings
        }
        security_ids = self._security_ids(connection, public_ids)
        connection.execute(
            """
            INSERT INTO analytics.forward_dqv_outcome_ledger_binding_v3 (
                outcome_batch_id, ledger_id, contract_version, state,
                binding_content_hash, persistence_content_hash
            ) VALUES (
                %s, %s, 'FORWARD-DQV-BENCHMARK-OUTCOME-v3.0.0',
                %s, %s, %s
            )
            """,
            (
                envelope.outcome_batch_id,
                envelope.ledger_id,
                envelope.state,
                envelope.binding_content_hash,
                envelope.persistence_content_hash,
            ),
        )
        for variant in envelope.variants:
            for holding in variant.holdings:
                connection.execute(
                    """
                    INSERT INTO analytics.forward_dqv_benchmark_holding_outcome_v3 (
                        outcome_batch_id, ledger_id, benchmark_kind, variant_id,
                        holding_security_id, public_security_id, state,
                        frozen_weight_units, frozen_total_weight_units,
                        frozen_notional, frozen_notional_lexeme,
                        frozen_average_daily_dollar_volume,
                        frozen_average_daily_dollar_volume_lexeme,
                        gross_return, gross_return_lexeme,
                        round_trip_cost_rate, round_trip_cost_rate_lexeme,
                        weighted_gross_contribution,
                        weighted_gross_contribution_lexeme,
                        weighted_cost_contribution,
                        weighted_cost_contribution_lexeme,
                        weighted_net_contribution,
                        weighted_net_contribution_lexeme,
                        price_action_evidence_hash,
                        source_manifest_hash, reason_codes, outcome_content_hash
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        envelope.outcome_batch_id,
                        envelope.ledger_id,
                        holding.benchmark_kind.value,
                        holding.variant_id,
                        security_ids[holding.public_security_id],
                        holding.public_security_id,
                        holding.state,
                        holding.frozen_weight_units,
                        holding.frozen_total_weight_units,
                        holding.frozen_notional,
                        _decimal_lexeme(holding.frozen_notional),
                        holding.frozen_average_daily_dollar_volume,
                        _decimal_lexeme(
                            holding.frozen_average_daily_dollar_volume
                        ),
                        holding.gross_return,
                        _decimal_lexeme(holding.gross_return),
                        holding.round_trip_cost_rate,
                        _decimal_lexeme(holding.round_trip_cost_rate),
                        holding.weighted_gross_contribution,
                        _decimal_lexeme(
                            holding.weighted_gross_contribution
                        ),
                        holding.weighted_cost_contribution,
                        _decimal_lexeme(
                            holding.weighted_cost_contribution
                        ),
                        holding.weighted_net_contribution,
                        _decimal_lexeme(
                            holding.weighted_net_contribution
                        ),
                        holding.price_action_evidence_hash,
                        holding.source_manifest_hash,
                        Jsonb(list(holding.reason_codes)),
                        holding.outcome_content_hash,
                    ),
                )
            connection.execute(
                """
                INSERT INTO analytics.forward_dqv_benchmark_variant_outcome_v3 (
                    outcome_batch_id, ledger_id, benchmark_kind, variant_id,
                    state, holding_count, gross_return, gross_return_lexeme,
                    round_trip_cost_rate, round_trip_cost_rate_lexeme,
                    net_return, net_return_lexeme, price_action_evidence_hash,
                    source_manifest_hash, reason_codes, outcome_content_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    envelope.outcome_batch_id,
                    envelope.ledger_id,
                    variant.benchmark_kind.value,
                    variant.variant_id,
                    variant.state,
                    len(variant.holdings),
                    variant.gross_return,
                    _decimal_lexeme(variant.gross_return),
                    variant.round_trip_cost_rate,
                    _decimal_lexeme(variant.round_trip_cost_rate),
                    variant.net_return,
                    _decimal_lexeme(variant.net_return),
                    variant.price_action_evidence_hash,
                    variant.source_manifest_hash,
                    Jsonb(list(variant.reason_codes)),
                    variant.outcome_content_hash,
                ),
            )
        variant_counts: dict[BenchmarkKind, int] = {}
        for variant in envelope.variants:
            variant_counts[variant.benchmark_kind] = (
                variant_counts.get(variant.benchmark_kind, 0) + 1
            )
        for family in envelope.families:
            connection.execute(
                """
                INSERT INTO analytics.forward_dqv_benchmark_family_outcome_v3 (
                    outcome_batch_id, ledger_id, benchmark_kind,
                    aggregation_method, state, variant_count,
                    gross_return, gross_return_lexeme,
                    round_trip_cost_rate, round_trip_cost_rate_lexeme,
                    net_return, net_return_lexeme, source_manifest_hash,
                    reason_codes, outcome_content_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    envelope.outcome_batch_id,
                    envelope.ledger_id,
                    family.benchmark_kind.value,
                    family.aggregation_method,
                    family.state,
                    variant_counts.get(family.benchmark_kind, 0),
                    family.gross_return,
                    _decimal_lexeme(family.gross_return),
                    family.round_trip_cost_rate,
                    _decimal_lexeme(family.round_trip_cost_rate),
                    family.net_return,
                    _decimal_lexeme(family.net_return),
                    family.source_manifest_hash,
                    Jsonb(list(family.reason_codes)),
                    family.outcome_content_hash,
                ),
            )


def new_ledger_id() -> UUID:
    """Generate a caller-visible ID before the immutable transaction starts."""

    return uuid4()
