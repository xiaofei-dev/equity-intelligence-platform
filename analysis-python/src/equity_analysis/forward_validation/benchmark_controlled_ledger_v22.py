from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, ValidationInfo, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v21 import (
    BenchmarkConstructionState,
)
from equity_analysis.forward_validation.contracts_v2 import ContractModel
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

CONTROLLED_BENCHMARK_LEDGER_V22 = (
    "FORWARD-DQV-BENCHMARK-PATH-LEDGER-v2.2.0"
)
CONTROLLED_BENCHMARK_LEDGER_ARTIFACT = (
    "FORWARD_DQV_CONTROLLED_BENCHMARK_PATH_LEDGER"
)
CONTROLLED_BENCHMARK_LEDGER_STORAGE = Path(
    "storage/forward-validation/benchmark-ledgers-v2-2"
)
EXPECTED_BENCHMARK_KINDS = tuple(BenchmarkKind)
_HASH = r"^sha256:[0-9a-f]{64}$"


class ControlledBenchmarkLedgerError(ValueError):
    pass


class ControlledBenchmarkHoldingV22(ContractModel):
    public_security_id: UUID
    symbol: str = Field(min_length=1)
    sector: str | None = None
    selection_rank: int = Field(ge=1)
    weight_units: int = Field(ge=1)
    total_weight_units: int = Field(ge=1)
    notional: Decimal = Field(gt=0)
    average_daily_dollar_volume: Decimal = Field(gt=0)
    round_trip_cost_rate: Decimal = Field(ge=0)
    identity_source_hash: str = Field(pattern=_HASH)
    classification_source_hash: str | None = Field(default=None, pattern=_HASH)
    classification_effective_at: datetime | None = None
    classification_available_at: datetime | None = None
    classification_ingested_at: datetime | None = None
    price_bars_hash: str = Field(pattern=_HASH)
    price_receipt_hash: str = Field(pattern=_HASH)
    controlled_price_artifact_hash: str = Field(pattern=_HASH)
    price_source_hash: str = Field(pattern=_HASH)
    price_first_session: date
    price_last_session: date
    price_bar_count: int = Field(ge=1)
    price_available_at: datetime
    price_ingested_at: datetime
    selection_evidence_state: Literal[
        "OBJECTIVE_INPUT_BOUND",
        "PRICE_SERIES_BOUND",
        "NOT_APPLICABLE",
    ]
    selection_evidence_version: str | None = None
    selection_lineage_hash: str | None = Field(default=None, pattern=_HASH)
    selection_source_hash: str | None = Field(default=None, pattern=_HASH)
    selection_available_at: datetime | None = None
    selection_ingested_at: datetime | None = None
    adjustment_mode: Literal["TOTAL_RETURN_ADJUSTED"]
    action_state: Literal["RECONCILED"]
    adjustment_policy_version: str = Field(min_length=1)
    action_binding_hash: str = Field(pattern=_HASH)
    action_source_hash: str = Field(pattern=_HASH)
    action_available_at: datetime
    action_ingested_at: datetime
    liquidity_as_of_session: date
    liquidity_quality_status: Literal["VALIDATED"]
    liquidity_available_at: datetime
    liquidity_ingested_at: datetime
    liquidity_source_hash: str = Field(pattern=_HASH)
    cost_policy_hash: str = Field(pattern=_HASH)
    input_available_at: datetime
    input_ingested_at: datetime
    holding_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_holding(
        self,
        info: ValidationInfo,
    ) -> ControlledBenchmarkHoldingV22:
        if self.sector is not None and not self.sector.strip():
            raise ValueError("A present benchmark holding sector cannot be blank")
        if self.weight_units > self.total_weight_units:
            raise ValueError("Benchmark weight units cannot exceed total weight units")
        classification_times = (
            self.classification_effective_at,
            self.classification_available_at,
            self.classification_ingested_at,
        )
        if self.classification_source_hash is None:
            if any(value is not None for value in classification_times):
                raise ValueError(
                    "Classification chronology requires a classification source hash"
                )
        elif any(value is None for value in classification_times):
            raise ValueError(
                "Classification source evidence requires complete chronology"
            )
        for label, value in (
            ("priceAvailableAt", self.price_available_at),
            ("priceIngestedAt", self.price_ingested_at),
            ("actionAvailableAt", self.action_available_at),
            ("actionIngestedAt", self.action_ingested_at),
            ("liquidityAvailableAt", self.liquidity_available_at),
            ("liquidityIngestedAt", self.liquidity_ingested_at),
            ("inputAvailableAt", self.input_available_at),
            ("inputIngestedAt", self.input_ingested_at),
        ):
            _aware(value, label)
        for value in classification_times:
            if value is not None:
                _aware(value, "classification chronology")
        if self.price_first_session > self.price_last_session:
            raise ValueError("Benchmark price-session chronology is invalid")
        selection_fields = (
            self.selection_evidence_version,
            self.selection_lineage_hash,
            self.selection_source_hash,
            self.selection_available_at,
            self.selection_ingested_at,
        )
        if self.selection_evidence_state == "NOT_APPLICABLE":
            if any(value is not None for value in selection_fields):
                raise ValueError(
                    "NOT_APPLICABLE selection evidence cannot carry source fields"
                )
        else:
            if any(value is None for value in selection_fields):
                raise ValueError(
                    "Bound benchmark selection evidence requires complete lineage"
                )
            _aware(self.selection_available_at, "selectionAvailableAt")
            _aware(self.selection_ingested_at, "selectionIngestedAt")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"holding_content_hash"},
            )
            if canonical_hash(body) != self.holding_content_hash:
                raise ValueError("Benchmark holding content hash is invalid")
        return self


class ControlledBenchmarkVariantV22(ContractModel):
    identifier: str = Field(min_length=1)
    construction_version: str = Field(min_length=1)
    sector: str | None = None
    state: BenchmarkConstructionState
    reason_codes: tuple[str, ...] = ()
    population_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    coverage_ratio: Decimal = Field(ge=0, le=1)
    path_construction: Literal["FIXED_WEIGHT_BUY_AND_HOLD"]
    constituent_set_hash: str | None = Field(default=None, pattern=_HASH)
    weight_hash: str | None = Field(default=None, pattern=_HASH)
    source_evidence_hash: str = Field(pattern=_HASH)
    selection_hash: str | None = Field(default=None, pattern=_HASH)
    cost_evidence_hash: str | None = Field(default=None, pattern=_HASH)
    sector_assignment_hash: str | None = Field(default=None, pattern=_HASH)
    evidence_hash: str = Field(pattern=_HASH)
    holdings: tuple[ControlledBenchmarkHoldingV22, ...]
    variant_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_variant(
        self,
        info: ValidationInfo,
    ) -> ControlledBenchmarkVariantV22:
        ids = tuple(item.public_security_id for item in self.holdings)
        if len(set(ids)) != len(ids):
            raise ValueError("Benchmark variant holding UUIDs must be unique")
        ranks = tuple(item.selection_rank for item in self.holdings)
        if ranks and tuple(sorted(ranks)) != tuple(range(1, len(ranks) + 1)):
            raise ValueError("Benchmark selection ranks must be complete and unique")
        if self.state == BenchmarkConstructionState.AVAILABLE:
            if self.reason_codes or not self.holdings:
                raise ValueError(
                    "AVAILABLE benchmark variant requires holdings and no reasons"
                )
            required = (
                self.constituent_set_hash,
                self.weight_hash,
                self.selection_hash,
                self.cost_evidence_hash,
            )
            if any(value is None for value in required):
                raise ValueError(
                    "AVAILABLE benchmark variant requires complete construction hashes"
                )
            denominators = {item.total_weight_units for item in self.holdings}
            if len(denominators) != 1:
                raise ValueError("Benchmark variant weight denominators must match")
            denominator = next(iter(denominators))
            if sum(item.weight_units for item in self.holdings) != denominator:
                raise ValueError("Benchmark variant weight units must sum exactly")
        elif self.holdings or not self.reason_codes:
            raise ValueError(
                "Unavailable benchmark variant requires reasons and no holdings"
            )
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"variant_content_hash"},
            )
            if canonical_hash(body) != self.variant_content_hash:
                raise ValueError("Benchmark variant content hash is invalid")
        return self


class ControlledBenchmarkFamilyV22(ContractModel):
    kind: BenchmarkKind
    benchmark_id: str = Field(min_length=1)
    construction_method: str = Field(min_length=1)
    state: BenchmarkConstructionState
    reason_codes: tuple[str, ...] = ()
    variants: tuple[ControlledBenchmarkVariantV22, ...]
    evidence_hash: str | None = Field(default=None, pattern=_HASH)
    source_evidence_hash: str | None = Field(default=None, pattern=_HASH)
    constituent_set_hash: str | None = Field(default=None, pattern=_HASH)
    weight_hash: str | None = Field(default=None, pattern=_HASH)
    selection_hash: str | None = Field(default=None, pattern=_HASH)
    cost_evidence_hash: str | None = Field(default=None, pattern=_HASH)
    sector_assignment_hash: str | None = Field(default=None, pattern=_HASH)
    terminal_hash: str = Field(pattern=_HASH)
    family_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_family(
        self,
        info: ValidationInfo,
    ) -> ControlledBenchmarkFamilyV22:
        identifiers = tuple(item.identifier for item in self.variants)
        if not identifiers or len(set(identifiers)) != len(identifiers):
            raise ValueError("Benchmark family variants must be present and unique")
        if self.state == BenchmarkConstructionState.AVAILABLE:
            if self.reason_codes or any(
                item.state != BenchmarkConstructionState.AVAILABLE
                for item in self.variants
            ):
                raise ValueError(
                    "AVAILABLE benchmark family requires available variants and no reasons"
                )
            required = (
                self.evidence_hash,
                self.source_evidence_hash,
                self.constituent_set_hash,
                self.weight_hash,
                self.selection_hash,
                self.cost_evidence_hash,
            )
            if any(value is None for value in required):
                raise ValueError(
                    "AVAILABLE benchmark family requires complete construction hashes"
                )
        elif not self.reason_codes:
            raise ValueError("Unavailable benchmark family requires reasons")
        if self.kind == BenchmarkKind.SECTOR:
            sectors = tuple(item.sector for item in self.variants)
            if any(value is None for value in sectors) or len(set(sectors)) != len(
                sectors
            ):
                raise ValueError(
                    "SECTOR benchmark variants require unique dated sector identities"
                )
        elif any(item.sector is not None for item in self.variants):
            raise ValueError("Only SECTOR benchmark variants may carry sectors")
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"family_content_hash"},
            )
            if canonical_hash(body) != self.family_content_hash:
                raise ValueError("Benchmark family content hash is invalid")
        return self


class ControlledBenchmarkLedgerSetV22(ContractModel):
    artifact_type: Literal["FORWARD_DQV_CONTROLLED_BENCHMARK_PATH_LEDGER"]
    schema_version: Literal["FORWARD-DQV-BENCHMARK-PATH-LEDGER-v2.2.0"]
    status: Literal["READY", "BLOCKED"]
    decision_completed_session: date
    decision_cutoff: datetime
    decision_as_of: datetime
    universe_version: str = Field(min_length=1)
    universe_hash: str = Field(pattern=_HASH)
    population_identity_binding_hash: str = Field(pattern=_HASH)
    preregistration_seal_hash: str = Field(pattern=_HASH)
    future_price_execution_hash: str = Field(pattern=_HASH)
    candidate_construction_hash: str = Field(pattern=_HASH)
    benchmark_bundle_hash: str = Field(pattern=_HASH)
    benchmark_contract_hash: str = Field(pattern=_HASH)
    parent_liquidity_cost_policy_hash: str = Field(pattern=_HASH)
    cost_policy_hash: str = Field(pattern=_HASH)
    family_count: Literal[6] = 6
    families: tuple[ControlledBenchmarkFamilyV22, ...]
    provider_network_requests: Literal[0] = 0
    database_writes: Literal[0] = 0
    scores_or_ranks_computed: Literal[False] = False
    ai_may_affect_deterministic_result: Literal[False] = False
    human_may_affect_deterministic_result: Literal[False] = False
    raw_provider_values_in_git_safe_manifest: Literal[False] = False
    ledger_content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def enforce_ledger(
        self,
        info: ValidationInfo,
    ) -> ControlledBenchmarkLedgerSetV22:
        cutoff = _aware(self.decision_cutoff, "Decision cutoff")
        if _aware(self.decision_as_of, "Decision asOf") != cutoff:
            raise ValueError("Benchmark ledger decision asOf must equal the cutoff")
        kinds = tuple(item.kind for item in self.families)
        if len(kinds) != 6 or set(kinds) != set(EXPECTED_BENCHMARK_KINDS):
            raise ValueError("Benchmark ledger requires the exact six families")
        if len(set(kinds)) != 6:
            raise ValueError("Benchmark ledger families must be unique")
        ready = all(
            item.state == BenchmarkConstructionState.AVAILABLE
            for item in self.families
        )
        if (self.status == "READY") != ready:
            raise ValueError("Benchmark ledger status does not match family states")
        for family in self.families:
            for variant in family.variants:
                for holding in variant.holdings:
                    evidence_times = (
                        holding.action_available_at,
                        holding.action_ingested_at,
                        holding.liquidity_available_at,
                        holding.liquidity_ingested_at,
                        holding.price_available_at,
                        holding.price_ingested_at,
                        holding.selection_available_at,
                        holding.selection_ingested_at,
                        holding.input_available_at,
                        holding.input_ingested_at,
                        holding.classification_available_at,
                        holding.classification_ingested_at,
                    )
                    if any(
                        value is not None and _aware(value, "Holding evidence") > cutoff
                        for value in evidence_times
                    ):
                        raise ValueError(
                            "Benchmark ledger contains future-available evidence"
                        )
                    if (
                        holding.liquidity_as_of_session
                        != self.decision_completed_session
                    ):
                        raise ValueError(
                            "Benchmark liquidity must use the decision completed session"
                        )
                    if holding.cost_policy_hash != self.cost_policy_hash:
                        raise ValueError(
                            "Benchmark holding cost-policy binding changed"
                        )
        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"ledger_content_hash"},
            )
            if canonical_hash(body) != self.ledger_content_hash:
                raise ValueError("Benchmark ledger content hash is invalid")
        return self

    @property
    def controlled_reference(self) -> str:
        filename = self.ledger_content_hash.removeprefix("sha256:") + ".json"
        return (CONTROLLED_BENCHMARK_LEDGER_STORAGE / filename).as_posix()

    def git_safe_manifest(self) -> dict[str, Any]:
        family_rows = []
        for family in self.families:
            family_rows.append(
                {
                    "kind": family.kind.value,
                    "benchmarkId": family.benchmark_id,
                    "state": family.state.value,
                    "reasonCodes": list(family.reason_codes),
                    "variantCount": len(family.variants),
                    "holdingCount": sum(
                        len(variant.holdings) for variant in family.variants
                    ),
                    "evidenceHash": family.evidence_hash,
                    "sourceEvidenceHash": family.source_evidence_hash,
                    "constituentSetHash": family.constituent_set_hash,
                    "weightHash": family.weight_hash,
                    "selectionHash": family.selection_hash,
                    "costEvidenceHash": family.cost_evidence_hash,
                    "sectorAssignmentHash": family.sector_assignment_hash,
                    "terminalHash": family.terminal_hash,
                    "familyContentHash": family.family_content_hash,
                }
            )
        body = {
            "artifactType": "FORWARD_DQV_BENCHMARK_LEDGER_MANIFEST",
            "schemaVersion": CONTROLLED_BENCHMARK_LEDGER_V22,
            "status": self.status,
            "decisionCompletedSession": self.decision_completed_session,
            "decisionCutoff": self.decision_cutoff,
            "universeVersion": self.universe_version,
            "universeHash": self.universe_hash,
            "populationIdentityBindingHash": self.population_identity_binding_hash,
            "benchmarkBundleHash": self.benchmark_bundle_hash,
            "benchmarkContractHash": self.benchmark_contract_hash,
            "costPolicyHash": self.cost_policy_hash,
            "familyCount": self.family_count,
            "families": family_rows,
            "controlledLedgerSetHash": self.ledger_content_hash,
            "controlledLedgerSetReference": self.controlled_reference,
            "rawProviderValuesIncluded": False,
            "numericDecisionValuesIncluded": False,
            "providerNetworkRequests": 0,
            "databaseWrites": 0,
            "scoresOrRanksComputed": False,
        }
        return {**body, "artifactContentHash": canonical_hash(body)}


class ControlledBenchmarkLedgerReceiptV22(ContractModel):
    artifact_type: Literal["FORWARD_DQV_BENCHMARK_LEDGER_RECEIPT"]
    schema_version: Literal["FORWARD-DQV-BENCHMARK-PATH-LEDGER-v2.2.0"]
    content_hash: str = Field(pattern=_HASH)
    reference: str = Field(min_length=1)
    file_sha256: str = Field(pattern=_HASH)
    replayed: bool


def build_controlled_benchmark_ledger_set_v22(
    *,
    bundle: Any,
    request: Any,
) -> ControlledBenchmarkLedgerSetV22:
    base = request.base_request
    members = {item.public_security_id: item for item in base.members}
    bindings = {item.public_security_id: item for item in request.price_series_bindings}
    actions = {item.public_security_id: item for item in request.action_evidence}
    liquidity = {item.public_security_id: item for item in base.liquidity}
    price_sources: dict[str, dict[str, Any]] = {}
    for public_id in members:
        price_rows = tuple(
            item
            for item in base.prices
            if item.public_security_id == public_id
        )
        if not price_rows:
            raise ControlledBenchmarkLedgerError(
                "BENCHMARK_LEDGER_PRICE_SOURCE_EVIDENCE_MISSING"
            )
        price_sources[public_id] = {
            "sourceHash": canonical_hash(
                sorted(item.source_hash for item in price_rows)
            ),
            "firstSession": min(item.session_date for item in price_rows),
            "lastSession": max(item.session_date for item in price_rows),
            "barCount": len(price_rows),
            "availableAt": max(item.available_at for item in price_rows),
            "ingestedAt": max(item.ingested_at for item in price_rows),
        }
    capture_rows = {
        str(item["publicSecurityId"]): item
        for item in request.input_capture.get("securities", ())
    }
    objective_selection_sources: dict[str, dict[str, Any]] = {}
    for public_id, item in capture_rows.items():
        retrieved_at = datetime.fromisoformat(
            str(item["retrievedAt"]).replace("Z", "+00:00")
        )
        objective_selection_sources[public_id] = {
            "version": str(request.candidate_construction["schemaVersion"]),
            "lineageHash": canonical_hash(
                {
                    "candidateConstructionHash": bundle.candidate_construction_hash,
                    "captureArtifactHash": request.input_capture[
                        "artifactContentHash"
                    ],
                    "coverageArtifactHash": request.input_coverage[
                        "artifactContentHash"
                    ],
                    "controlledPayloadContentHash": item[
                        "controlledPayloadContentHash"
                    ],
                }
            ),
            "sourceHash": str(item["sourceResponseContentHash"]),
            "availableAt": retrieved_at,
            "ingestedAt": retrieved_at,
        }
    expected_ids = set(members)
    if (
        set(bindings) != expected_ids
        or set(actions) != expected_ids
        or set(liquidity) != expected_ids
    ):
        raise ControlledBenchmarkLedgerError(
            "BENCHMARK_LEDGER_SOURCE_BINDING_COVERAGE_INCOMPLETE"
        )

    families = tuple(
        _seal_family(
            family,
            members=members,
            bindings=bindings,
            actions=actions,
            liquidity=liquidity,
            price_sources=price_sources,
            objective_selection_sources=objective_selection_sources,
            cost_policy_hash=bundle.cost_hash,
        )
        for family in bundle.benchmarks
    )
    body = {
        "artifactType": CONTROLLED_BENCHMARK_LEDGER_ARTIFACT,
        "schemaVersion": CONTROLLED_BENCHMARK_LEDGER_V22,
        "status": (
            "READY"
            if all(
                item.state == BenchmarkConstructionState.AVAILABLE
                for item in families
            )
            else "BLOCKED"
        ),
        "decisionCompletedSession": bundle.completed_session,
        "decisionCutoff": bundle.decision_cutoff,
        "decisionAsOf": bundle.decision_cutoff,
        "universeVersion": bundle.universe_version,
        "universeHash": bundle.universe_hash,
        "populationIdentityBindingHash": request.parent_preregistration[
            "prospectiveUniverse"
        ]["identityBindingHash"],
        "preregistrationSealHash": bundle.preregistration_seal_hash,
        "futurePriceExecutionHash": bundle.future_price_execution_hash,
        "candidateConstructionHash": bundle.candidate_construction_hash,
        "benchmarkBundleHash": bundle.bundle_hash,
        "benchmarkContractHash": bundle.benchmark_contract_hash,
        "parentLiquidityCostPolicyHash": (
            bundle.parent_liquidity_cost_policy_hash
        ),
        "costPolicyHash": bundle.cost_hash,
        "familyCount": 6,
        "families": [
            item.model_dump(mode="json", by_alias=True) for item in families
        ],
        "providerNetworkRequests": 0,
        "databaseWrites": 0,
        "scoresOrRanksComputed": False,
        "aiMayAffectDeterministicResult": False,
        "humanMayAffectDeterministicResult": False,
        "rawProviderValuesInGitSafeManifest": False,
    }
    return ControlledBenchmarkLedgerSetV22.model_validate(
        {**body, "ledgerContentHash": canonical_hash(body)}
    )


def write_or_verify_controlled_benchmark_ledger_v22(
    *,
    ledger: ControlledBenchmarkLedgerSetV22,
    repository_root: Path,
) -> ControlledBenchmarkLedgerReceiptV22:
    verified = ControlledBenchmarkLedgerSetV22.model_validate(
        ledger.model_dump(mode="json", by_alias=True)
    )
    reference = verified.controlled_reference
    root = repository_root.resolve()
    path = (root / reference).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ControlledBenchmarkLedgerError(
            "BENCHMARK_LEDGER_REFERENCE_ESCAPES_REPOSITORY"
        ) from exc
    encoded = _encoded(verified.model_dump(mode="json", by_alias=True))
    replayed = _write_or_verify(
        path,
        encoded,
        "IMMUTABLE_BENCHMARK_LEDGER_CONFLICT",
    )
    return ControlledBenchmarkLedgerReceiptV22(
        artifact_type="FORWARD_DQV_BENCHMARK_LEDGER_RECEIPT",
        schema_version=CONTROLLED_BENCHMARK_LEDGER_V22,
        content_hash=verified.ledger_content_hash,
        reference=reference,
        file_sha256="sha256:" + hashlib.sha256(encoded).hexdigest(),
        replayed=replayed,
    )


def load_controlled_benchmark_ledger_v22(
    *,
    repository_root: Path,
    reference: str,
    expected_hash: str,
) -> ControlledBenchmarkLedgerSetV22:
    root = repository_root.resolve()
    path = (root / reference).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ControlledBenchmarkLedgerError(
            "BENCHMARK_LEDGER_REFERENCE_ESCAPES_REPOSITORY"
        ) from exc
    payload = json.loads(path.read_text(encoding="utf-8"))
    ledger = ControlledBenchmarkLedgerSetV22.model_validate(payload)
    if ledger.ledger_content_hash != expected_hash:
        raise ControlledBenchmarkLedgerError(
            "BENCHMARK_LEDGER_EXPECTED_HASH_MISMATCH"
        )
    return ledger


def _seal_family(
    family: Any,
    *,
    members: dict[str, Any],
    bindings: dict[str, Any],
    actions: dict[str, Any],
    liquidity: dict[str, Any],
    price_sources: dict[str, dict[str, Any]],
    objective_selection_sources: dict[str, dict[str, Any]],
    cost_policy_hash: str,
) -> ControlledBenchmarkFamilyV22:
    variants = tuple(
        _seal_variant(
            variant,
            members=members,
            bindings=bindings,
            actions=actions,
            liquidity=liquidity,
            price_sources=price_sources,
            objective_selection_sources=objective_selection_sources,
            benchmark_kind=family.kind,
            cost_policy_hash=cost_policy_hash,
        )
        for variant in family.variants
    )
    body = {
        "kind": family.kind.value,
        "benchmarkId": family.benchmark_id,
        "constructionMethod": family.construction_method,
        "state": family.state.value,
        "reasonCodes": list(family.reason_codes),
        "variants": [
            item.model_dump(mode="json", by_alias=True) for item in variants
        ],
        "evidenceHash": family.evidence_hash,
        "sourceEvidenceHash": family.source_evidence_hash,
        "constituentSetHash": family.constituent_set_hash,
        "weightHash": family.weight_hash,
        "selectionHash": family.selection_hash,
        "costEvidenceHash": family.cost_evidence_hash,
        "sectorAssignmentHash": family.sector_assignment_hash,
        "terminalHash": family.terminal_hash,
    }
    return ControlledBenchmarkFamilyV22.model_validate(
        {**body, "familyContentHash": canonical_hash(body)}
    )


def _seal_variant(
    variant: Any,
    *,
    members: dict[str, Any],
    bindings: dict[str, Any],
    actions: dict[str, Any],
    liquidity: dict[str, Any],
    price_sources: dict[str, dict[str, Any]],
    objective_selection_sources: dict[str, dict[str, Any]],
    benchmark_kind: BenchmarkKind,
    cost_policy_hash: str,
) -> ControlledBenchmarkVariantV22:
    holdings = tuple(
        _seal_holding(
            holding,
            member=members[holding.public_security_id],
            binding=bindings[holding.public_security_id],
            action=actions[holding.public_security_id],
            liquidity=liquidity[holding.public_security_id],
            price_evidence=price_sources[holding.public_security_id],
            selection_evidence=_selection_evidence(
                benchmark_kind=benchmark_kind,
                public_security_id=holding.public_security_id,
                price_evidence=price_sources[holding.public_security_id],
                objective_selection_sources=objective_selection_sources,
                construction_version=variant.construction_version,
            ),
            cost_policy_hash=cost_policy_hash,
        )
        for holding in variant.holdings
    )
    body = {
        "identifier": variant.identifier,
        "constructionVersion": variant.construction_version,
        "sector": variant.sector,
        "state": variant.state.value,
        "reasonCodes": list(variant.reason_codes),
        "populationCount": variant.population_count,
        "eligibleCount": variant.eligible_count,
        "coverageRatio": variant.coverage_ratio,
        "pathConstruction": "FIXED_WEIGHT_BUY_AND_HOLD",
        "constituentSetHash": variant.constituent_set_hash,
        "weightHash": variant.weight_hash,
        "sourceEvidenceHash": variant.source_evidence_hash,
        "selectionHash": variant.selection_hash,
        "costEvidenceHash": variant.cost_evidence_hash,
        "sectorAssignmentHash": variant.sector_assignment_hash,
        "evidenceHash": variant.evidence_hash,
        "holdings": [
            item.model_dump(mode="json", by_alias=True) for item in holdings
        ],
    }
    return ControlledBenchmarkVariantV22.model_validate(
        {**body, "variantContentHash": canonical_hash(body)}
    )


def _seal_holding(
    holding: Any,
    *,
    member: Any,
    binding: Any,
    action: Any,
    liquidity: Any,
    price_evidence: dict[str, Any],
    selection_evidence: dict[str, Any],
    cost_policy_hash: str,
) -> ControlledBenchmarkHoldingV22:
    classification_times = (
        member.classification_effective_at,
        member.classification_available_at,
        member.classification_ingested_at,
    )
    source_available = tuple(
        value
        for value in (
            member.classification_available_at,
            price_evidence["availableAt"],
            selection_evidence.get("availableAt"),
            action.available_at,
            liquidity.available_at,
        )
        if value is not None
    )
    source_ingested = tuple(
        value
        for value in (
            member.classification_ingested_at,
            price_evidence["ingestedAt"],
            selection_evidence.get("ingestedAt"),
            action.ingested_at,
            liquidity.ingested_at,
        )
        if value is not None
    )
    if not source_available or not source_ingested:
        raise ControlledBenchmarkLedgerError(
            "BENCHMARK_HOLDING_SOURCE_CHRONOLOGY_INCOMPLETE"
        )
    body = {
        "publicSecurityId": str(UUID(str(holding.public_security_id))),
        "symbol": holding.symbol,
        "sector": holding.sector,
        "selectionRank": holding.selection_rank,
        "weightUnits": holding.weight_units,
        "totalWeightUnits": holding.total_weight_units,
        "notional": holding.notional,
        "averageDailyDollarVolume": holding.average_daily_dollar_volume,
        "roundTripCostRate": holding.round_trip_cost_rate,
        "identitySourceHash": member.identity_source_hash,
        "classificationSourceHash": member.classification_source_hash,
        "classificationEffectiveAt": classification_times[0],
        "classificationAvailableAt": classification_times[1],
        "classificationIngestedAt": classification_times[2],
        "priceBarsHash": binding.bars_hash,
        "priceReceiptHash": binding.receipt_hash,
        "controlledPriceArtifactHash": binding.controlled_artifact_hash,
        "priceSourceHash": price_evidence["sourceHash"],
        "priceFirstSession": price_evidence["firstSession"],
        "priceLastSession": price_evidence["lastSession"],
        "priceBarCount": price_evidence["barCount"],
        "priceAvailableAt": price_evidence["availableAt"],
        "priceIngestedAt": price_evidence["ingestedAt"],
        "selectionEvidenceState": selection_evidence["state"],
        "selectionEvidenceVersion": selection_evidence.get("version"),
        "selectionLineageHash": selection_evidence.get("lineageHash"),
        "selectionSourceHash": selection_evidence.get("sourceHash"),
        "selectionAvailableAt": selection_evidence.get("availableAt"),
        "selectionIngestedAt": selection_evidence.get("ingestedAt"),
        "adjustmentMode": "TOTAL_RETURN_ADJUSTED",
        "actionState": action.state,
        "adjustmentPolicyVersion": action.adjustment_policy_version,
        "actionBindingHash": action.action_binding_hash,
        "actionSourceHash": action.source_hash,
        "actionAvailableAt": action.available_at,
        "actionIngestedAt": action.ingested_at,
        "liquidityAsOfSession": liquidity.as_of_session,
        "liquidityQualityStatus": liquidity.quality_status,
        "liquidityAvailableAt": liquidity.available_at,
        "liquidityIngestedAt": liquidity.ingested_at,
        "liquiditySourceHash": liquidity.source_hash,
        "costPolicyHash": cost_policy_hash,
        "inputAvailableAt": max(source_available),
        "inputIngestedAt": max(source_ingested),
    }
    return ControlledBenchmarkHoldingV22.model_validate(
        {**body, "holdingContentHash": canonical_hash(body)}
    )


def _selection_evidence(
    *,
    benchmark_kind: BenchmarkKind,
    public_security_id: str,
    price_evidence: dict[str, Any],
    objective_selection_sources: dict[str, dict[str, Any]],
    construction_version: str,
) -> dict[str, Any]:
    if benchmark_kind in {
        BenchmarkKind.PURE_VALUE,
        BenchmarkKind.PURE_QUALITY,
    }:
        source = objective_selection_sources.get(public_security_id)
        if source is None:
            raise ControlledBenchmarkLedgerError(
                "BENCHMARK_OBJECTIVE_SELECTION_SOURCE_MISSING"
            )
        return {
            "state": "OBJECTIVE_INPUT_BOUND",
            **source,
        }
    if benchmark_kind == BenchmarkKind.PURE_MOMENTUM:
        return {
            "state": "PRICE_SERIES_BOUND",
            "version": construction_version,
            "lineageHash": canonical_hash(
                {
                    "constructionVersion": construction_version,
                    "priceSourceHash": price_evidence["sourceHash"],
                    "firstSession": price_evidence["firstSession"],
                    "lastSession": price_evidence["lastSession"],
                    "barCount": price_evidence["barCount"],
                }
            ),
            "sourceHash": price_evidence["sourceHash"],
            "availableAt": price_evidence["availableAt"],
            "ingestedAt": price_evidence["ingestedAt"],
        }
    return {"state": "NOT_APPLICABLE"}


def _encoded(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")


def _write_or_verify(path: Path, encoded: bytes, conflict_code: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise ControlledBenchmarkLedgerError(conflict_code)
        return True
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return False


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")
