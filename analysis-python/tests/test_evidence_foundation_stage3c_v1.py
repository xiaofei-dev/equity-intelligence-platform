from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from equity_analysis.daily_refresh.models import (
    Dataset,
    RefreshPlan,
    SecurityTarget,
    WorkItem,
)
from equity_analysis.dual_system_contract import ModelApplicability
from equity_analysis.evidence_foundation import (
    EvidenceFoundationIntegrityConflict,
    EvidenceFoundationRepository,
    EvidenceSelectionRequest,
    ModelApplicabilityRouting,
    PersistedEvidenceEnvelope,
    PersistedSelectorAggregate,
    UnifiedEvidenceContractViolation,
    select_evidence,
)
from equity_analysis.evidence_foundation.domain_contracts_v1 import EvidenceDomain
from equity_analysis.evidence_foundation.provider_adapter_v1 import (
    PROVIDER_ADAPTER_CONTRACT_VERSION,
    CanonicalEvidenceBatchV1,
    ProviderAdapterDescriptorV1,
    ProviderEvidenceRequestV1,
    _evidence_matches_requested_scope,
)
from equity_analysis.evidence_foundation.refresh_v1 import (
    EVIDENCE_REFRESH_PLAN_VERSION,
    EvidenceRefreshBlocked,
    EvidenceRefreshItemStatus,
    EvidenceRefreshItemV1,
    EvidenceRefreshOutcome,
    EvidenceRefreshPlanV1,
    ProviderAdapterFailure,
    ProviderNeutralEvidenceRefreshCoordinatorV1,
    bind_daily_refresh_plan_v1,
)
from equity_analysis.evidence_foundation.routes_v1 import (
    SELECTION_COMMAND_VERSION,
    get_evidence_repository,
)
from equity_analysis.main import app
from equity_analysis.market_data.models import AdjustmentMode
from equity_analysis.provider_validation.execution_safety import (
    SymbolExecutionJournal,
)

FIXTURE = (
    Path(__file__).parents[2]
    / "contracts"
    / "unified-market-data-evidence-v1"
    / "selector-request.example.json"
)
DOMAIN_FIXTURE = (
    Path(__file__).parents[2]
    / "contracts"
    / "unified-market-data-evidence-v1"
    / "domain-canonical-data.example.json"
)


@dataclass
class FakeEvidenceRepository:
    envelopes: dict[str, PersistedEvidenceEnvelope]
    routing: ModelApplicabilityRouting
    aggregate: PersistedSelectorAggregate | None = None

    def load_candidate(self, evidence_id: str) -> PersistedEvidenceEnvelope:
        try:
            return self.envelopes[evidence_id]
        except KeyError as error:
            raise LookupError(f"Evidence {evidence_id} was not found") from error

    def execute_selector(
        self,
        request: EvidenceSelectionRequest,
    ) -> PersistedSelectorAggregate:
        if self.aggregate is None:
            self.aggregate = PersistedSelectorAggregate(
                request_id=str(uuid4()),
                request=request,
                result=select_evidence(request),
            )
            return self.aggregate
        return replace(self.aggregate, replayed=True)

    def load_selector_aggregate(
        self,
        request_id: str,
    ) -> PersistedSelectorAggregate:
        if self.aggregate is None or self.aggregate.request_id != request_id:
            raise LookupError(f"Selector request {request_id} was not found")
        return self.aggregate

    def load_latest_applicability_routing(
        self,
        company_id: str,
        routing_version: str,
    ) -> ModelApplicabilityRouting:
        if (
            company_id != self.routing.company_id
            or routing_version != self.routing.routing_version
        ):
            raise LookupError("Applicability routing was not found")
        return self.routing


class RecordingPersistence:
    def __init__(self) -> None:
        self.persisted: list[PersistedEvidenceEnvelope] = []

    def persist_candidate(self, envelope: PersistedEvidenceEnvelope) -> None:
        if envelope in self.persisted:
            raise AssertionError("Duplicate evidence persistence was attempted")
        self.persisted.append(envelope)


class ContentIdempotentPersistence:
    def __init__(self) -> None:
        self.persisted: dict[str, PersistedEvidenceEnvelope] = {}
        self.calls = 0

    def persist_candidate(self, envelope: PersistedEvidenceEnvelope) -> None:
        self.calls += 1
        evidence_id = envelope.candidate.evidence_id
        existing = self.persisted.get(evidence_id)
        if existing is None:
            self.persisted[evidence_id] = envelope
        elif existing != envelope:
            raise EvidenceFoundationIntegrityConflict(
                "Evidence identity reuse conflicts with persisted canonical content"
            )


class FakeProviderAdapter:
    def __init__(
        self,
        descriptor: ProviderAdapterDescriptorV1,
        evidence_by_request: dict[str, PersistedEvidenceEnvelope],
        fail_once: set[str] | None = None,
    ) -> None:
        self._descriptor = descriptor
        self._evidence_by_request = evidence_by_request
        self._fail_once = set(fail_once or ())
        self.calls: list[str] = []

    @property
    def descriptor(self) -> ProviderAdapterDescriptorV1:
        return self._descriptor

    def fetch_canonical_evidence(
        self,
        request: ProviderEvidenceRequestV1,
    ) -> CanonicalEvidenceBatchV1:
        self.calls.append(request.request_id)
        if request.request_id in self._fail_once:
            self._fail_once.remove(request.request_id)
            raise ProviderAdapterFailure("FIXTURE_PARTIAL_FAILURE")
        return CanonicalEvidenceBatchV1(
            contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
            request_id=request.request_id,
            provider_code=request.provider_code,
            evidence=(self._evidence_by_request[request.request_id],),
        )


class RowCountCursor:
    def __init__(self, row_count: int) -> None:
        self._rows = [{} for _ in range(row_count)]

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, *_args, **_kwargs) -> None:
        return None

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class RowCountConnection:
    def __init__(self, row_count: int) -> None:
        self._cursor = RowCountCursor(row_count)

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def cursor(self) -> RowCountCursor:
        return self._cursor


def test_internal_v22_selection_and_applicability_endpoints() -> None:
    request, envelopes = _request_and_envelopes()
    routing = ModelApplicabilityRouting.create(
        routing_id=str(uuid4()),
        company_id=request.security.company_id,
        classification_evidence_id=str(uuid4()),
        company_type="MATURE_OPERATING_COMPANY",
        applicability=ModelApplicability.APPLICABLE,
        specialized_model_code=None,
        routing_version="fundamental-applicability-routing-v1.0.0",
        routing_revision=1,
        effective_at=request.decision_cutoff,
    )
    repository = FakeEvidenceRepository(
        envelopes={
            envelope.candidate.evidence_id: envelope for envelope in envelopes
        },
        routing=routing,
    )
    app.dependency_overrides[get_evidence_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            create = client.post(
                "/internal/v1/evidence-foundation/selections",
                json=_selection_command(request),
            )
            assert create.status_code == 201
            created = create.json()
            assert created["contractVersion"] == (
                "internal-evidence-selection-result-v1.0.0"
            )
            assert created["state"] == "VALID"
            assert created["selectedEvidenceId"] == (
                request.candidates[0].evidence_id
            )
            replay = client.post(
                "/internal/v1/evidence-foundation/selections",
                json=_selection_command(request),
            )
            assert replay.status_code == 200
            assert replay.json() == created

            malformed = _selection_command(request)
            malformed["unexpectedField"] = True
            invalid = client.post(
                "/internal/v1/evidence-foundation/selections",
                json=malformed,
            )
            assert invalid.status_code == 422
            readback = client.get(
                f"/internal/v1/evidence-foundation/selections/{created['requestId']}"
            )
            assert readback.status_code == 200
            assert readback.json() == created

            applicability = client.get(
                "/internal/v1/evidence-foundation/model-applicability/"
                f"{routing.company_id}",
                params={"routingVersion": routing.routing_version},
            )
            assert applicability.status_code == 200
            assert applicability.json()["applicability"] == "APPLICABLE"
            assert applicability.json()["modelFamily"] == "FUNDAMENTAL_VALUE"
    finally:
        app.dependency_overrides.clear()


def test_internal_selection_rejects_unknown_and_duplicate_candidate_ids() -> None:
    request, envelopes = _request_and_envelopes()
    routing = ModelApplicabilityRouting.create(
        routing_id=str(uuid4()),
        company_id=request.security.company_id,
        classification_evidence_id=str(uuid4()),
        company_type="MATURE_OPERATING_COMPANY",
        applicability=ModelApplicability.APPLICABLE,
        specialized_model_code=None,
        routing_version="fundamental-applicability-routing-v1.0.0",
        routing_revision=1,
        effective_at=request.decision_cutoff,
    )
    repository = FakeEvidenceRepository(
        envelopes={
            envelope.candidate.evidence_id: envelope for envelope in envelopes
        },
        routing=routing,
    )
    app.dependency_overrides[get_evidence_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            unknown = _selection_command(request)
            unknown["candidateEvidenceIds"] = [str(uuid4())]
            response = client.post(
                "/internal/v1/evidence-foundation/selections",
                json=unknown,
            )
            assert response.status_code == 404

            duplicate = _selection_command(request)
            duplicate["candidateEvidenceIds"] = [
                request.candidates[0].evidence_id,
                request.candidates[0].evidence_id,
            ]
            response = client.post(
                "/internal/v1/evidence-foundation/selections",
                json=duplicate,
            )
            assert response.status_code == 422

            equivalent_duplicate = _selection_command(request)
            equivalent_duplicate["candidateEvidenceIds"] = [
                request.candidates[0].evidence_id.lower(),
                request.candidates[0].evidence_id.upper(),
            ]
            response = client.post(
                "/internal/v1/evidence-foundation/selections",
                json=equivalent_duplicate,
            )
            assert response.status_code == 422
            assert "identifiers must be unique" in response.text

            missing_applicability = client.get(
                "/internal/v1/evidence-foundation/model-applicability/"
                f"{uuid4()}",
                params={"routingVersion": routing.routing_version},
            )
            assert missing_applicability.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_internal_selection_integrity_conflict_is_never_reported_as_not_found() -> None:
    request, envelopes = _request_and_envelopes()
    routing = ModelApplicabilityRouting.create(
        routing_id=str(uuid4()),
        company_id=request.security.company_id,
        classification_evidence_id=str(uuid4()),
        company_type="MATURE_OPERATING_COMPANY",
        applicability=ModelApplicability.APPLICABLE,
        specialized_model_code=None,
        routing_version="fundamental-applicability-routing-v1.0.0",
        routing_revision=1,
        effective_at=request.decision_cutoff,
    )

    class ConflictingRepository(FakeEvidenceRepository):
        def execute_selector(
            self,
            request: EvidenceSelectionRequest,
        ) -> PersistedSelectorAggregate:
            raise EvidenceFoundationIntegrityConflict(
                "fixture selector integrity conflict"
            )

    repository = ConflictingRepository(
        envelopes={
            envelope.candidate.evidence_id: envelope for envelope in envelopes
        },
        routing=routing,
    )
    app.dependency_overrides[get_evidence_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/v1/evidence-foundation/selections",
                json=_selection_command(request),
            )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == (
            "EVIDENCE_FOUNDATION_INTEGRITY_CONFLICT"
        )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("row_count", "error_type", "message"),
    (
        (0, LookupError, "No current applicability routing"),
        (
            2,
            UnifiedEvidenceContractViolation,
            "multiple unsuperseded rows",
        ),
    ),
)
def test_latest_applicability_lookup_fails_closed_on_invalid_cardinality(
    row_count: int,
    error_type: type[Exception],
    message: str,
) -> None:
    repository = EvidenceFoundationRepository(
        "postgresql://fixture",
        connect=lambda *_args, **_kwargs: RowCountConnection(row_count),
    )
    with pytest.raises(error_type, match=message):
        repository.load_latest_applicability_routing(
            str(uuid4()),
            "applicability-routing-v1.0.0",
        )


def test_fastapi_startup_does_not_resolve_evidence_or_fetch_provider() -> None:
    calls = 0

    def forbidden_repository():
        nonlocal calls
        calls += 1
        raise AssertionError("Evidence repository resolved during startup")

    app.dependency_overrides[get_evidence_repository] = forbidden_repository
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
        assert calls == 0
    finally:
        app.dependency_overrides.clear()


def test_provider_request_fields_require_an_immutable_tuple() -> None:
    selection_request, envelopes = _request_and_envelopes(provider_code="YAHOO")
    canonical = _refresh_item(selection_request, envelopes[0]).request
    mutable_fields = ["CLOSE_PRICE"]

    with pytest.raises(ValueError, match="immutable tuple"):
        ProviderEvidenceRequestV1.create(
            provider_code=canonical.provider_code,
            security=canonical.security,
            completed_session=canonical.completed_session,
            domain=canonical.domain,
            requested_field_codes=mutable_fields,  # type: ignore[arg-type]
            start_date=canonical.start_date,
            end_date=canonical.end_date,
        )

    with pytest.raises(ValueError, match="immutable tuple"):
        ProviderEvidenceRequestV1(
            **{
                **canonical.__dict__,
                "requested_field_codes": mutable_fields,
            }
        )


@pytest.mark.parametrize(
    "supported_domains",
    (
        [EvidenceDomain.DAILY_PRICE],
        ("DAILY_PRICE",),
    ),
)
def test_provider_descriptor_domains_require_canonical_tuple_members(
    supported_domains: object,
) -> None:
    with pytest.raises(ValueError, match="immutable tuple of canonical domains"):
        ProviderAdapterDescriptorV1(
            contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
            provider_code="YAHOO",
            provider_schema_version="fixture-provider-schema-v1",
            adapter_version="fixture-adapter-v1.0.0",
            supported_domains=supported_domains,  # type: ignore[arg-type]
        )


def test_offline_refresh_duplicate_partial_failure_and_resume(
    tmp_path: Path,
) -> None:
    request, envelopes = _request_and_envelopes(provider_code="YAHOO")
    descriptor = ProviderAdapterDescriptorV1(
        contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
        provider_code="YAHOO",
        provider_schema_version="fixture-provider-schema-v1",
        adapter_version="fixture-adapter-v1.0.0",
        supported_domains=(EvidenceDomain.DAILY_PRICE,),
    )
    items = tuple(
        _refresh_item(request, envelope, field_code=field_code)
        for envelope, field_code in zip(
            envelopes,
            ("CLOSE_PRICE", "VOLUME"),
            strict=True,
        )
    )
    adapter = FakeProviderAdapter(
        descriptor,
        {
            item.request.request_id: envelope
            for item, envelope in zip(items, envelopes, strict=True)
        },
        fail_once={items[1].item_id},
    )
    persistence = RecordingPersistence()
    coordinator = ProviderNeutralEvidenceRefreshCoordinatorV1(
        repository=persistence,
        adapters=(adapter,),
        private_runtime_root=tmp_path / "private-runtime",
    )
    plan = EvidenceRefreshPlanV1(
        run_id=str(uuid4()),
        plan_version=EVIDENCE_REFRESH_PLAN_VERSION,
        items=items,
    )

    first = coordinator.run(plan)
    assert first.outcome == EvidenceRefreshOutcome.PARTIAL
    assert [result.status for result in first.item_results] == [
        EvidenceRefreshItemStatus.PERSISTED,
        EvidenceRefreshItemStatus.FAILED,
    ]
    assert persistence.persisted == [envelopes[0]]

    resumed = coordinator.run(plan)
    assert resumed.outcome == EvidenceRefreshOutcome.SUCCEEDED
    assert [result.status for result in resumed.item_results] == [
        EvidenceRefreshItemStatus.REPLAYED,
        EvidenceRefreshItemStatus.PERSISTED,
    ]
    assert persistence.persisted == list(envelopes)
    assert adapter.calls == [
        items[0].item_id,
        items[1].item_id,
        items[1].item_id,
    ]

    duplicate = coordinator.run(plan)
    assert duplicate.outcome == EvidenceRefreshOutcome.SUCCEEDED
    assert all(
        result.status == EvidenceRefreshItemStatus.REPLAYED
        for result in duplicate.item_results
    )
    assert len(adapter.calls) == 3
    assert persistence.persisted == list(envelopes)

    changed_security = replace(
        items[0].request.security,
        listing_id=str(uuid4()),
    )
    changed_identity_request = ProviderEvidenceRequestV1.create(
        provider_code=items[0].request.provider_code,
        security=changed_security,
        completed_session=items[0].request.completed_session,
        domain=items[0].request.domain,
        requested_field_codes=items[0].request.requested_field_codes,
        start_date=items[0].request.start_date,
        end_date=items[0].request.end_date,
    )
    mismatched_replay = replace(
        plan,
        items=(
            EvidenceRefreshItemV1(
                item_id=changed_identity_request.request_id,
                request=changed_identity_request,
            ),
            items[1],
        ),
    )
    with pytest.raises(
        EvidenceRefreshBlocked,
        match="EVIDENCE_REFRESH_PLAN_REPLAY_MISMATCH",
    ):
        coordinator.run(mismatched_replay)
    assert len(adapter.calls) == 3


def test_existing_daily_refresh_plan_binds_to_one_canonical_physical_request() -> None:
    request, _ = _request_and_envelopes(provider_code="YAHOO")
    target = SecurityTarget(
        security_id=request.security.security_id,
        symbol=request.security.ticker,
    )
    common = {
        "security": target,
        "dataset": Dataset.DAILY_PRICE,
        "provider_code": "yfinance",
        "start_date": date(2026, 7, 28),
        "end_date": date(2026, 7, 29),
        "expected_session_date": date(2026, 7, 29),
        "estimated_weighted_calls": 1,
    }
    daily_plan = RefreshPlan(
        as_of=datetime(2026, 7, 29, 20, 7, tzinfo=UTC),
        provider_code="yfinance",
        universe_version="fixture-universe-v1",
        configuration_hash=_hash("fixture-refresh-plan"),
        expected_session_date=date(2026, 7, 29),
        items=(
            WorkItem(
                **common,
                adjustment_mode=AdjustmentMode.UNADJUSTED,
            ),
            WorkItem(
                **common,
                adjustment_mode=AdjustmentMode.TOTAL_RETURN_ADJUSTED,
            ),
        ),
        estimated_weighted_calls=1,
        available_weighted_calls=None,
    )
    keyword_arguments = {
        "securities": {
            request.security.security_id: request.security,
        },
        "completed_session": request.completed_session,
        "provider_routes": {"yfinance": "YAHOO"},
    }
    bound = bind_daily_refresh_plan_v1(
        daily_plan,
        **keyword_arguments,
    )
    replay = bind_daily_refresh_plan_v1(
        daily_plan,
        **keyword_arguments,
    )

    assert bound == replay
    assert len(bound.items) == 1
    assert bound.items[0].request.provider_code == "YAHOO"
    assert bound.items[0].request.requested_field_codes == (
        "OPEN_PRICE",
        "HIGH_PRICE",
        "LOW_PRICE",
        "CLOSE_PRICE",
        "ADJUSTED_CLOSE",
        "VOLUME",
    )

    changed_listing = replace(
        request.security,
        listing_id=str(uuid4()),
    )
    listing_bound = bind_daily_refresh_plan_v1(
        daily_plan,
        securities={request.security.security_id: changed_listing},
        completed_session=request.completed_session,
        provider_routes={"yfinance": "YAHOO"},
    )
    changed_calendar = replace(
        request.completed_session,
        calendar_version="XNYS-calendar-v1.0.1",
    )
    calendar_bound = bind_daily_refresh_plan_v1(
        daily_plan,
        securities={request.security.security_id: request.security},
        completed_session=changed_calendar,
        provider_routes={"yfinance": "YAHOO"},
    )
    assert listing_bound.items[0].item_id != bound.items[0].item_id
    assert calendar_bound.items[0].item_id != bound.items[0].item_id
    assert listing_bound.run_id != bound.run_id
    assert calendar_bound.run_id != bound.run_id
    assert listing_bound.content_hash != bound.content_hash
    assert calendar_bound.content_hash != bound.content_hash

    with pytest.raises(ValueError, match="canonical context"):
        ProviderEvidenceRequestV1(
            **{
                **bound.items[0].request.__dict__,
                "request_id": str(uuid4()),
            }
        )

    mismatched_item = replace(
        daily_plan,
        items=(
            replace(
                daily_plan.items[0],
                expected_session_date=date(2026, 7, 28),
            ),
        ),
    )
    with pytest.raises(ValueError, match="item session"):
        bind_daily_refresh_plan_v1(
            mismatched_item,
            **keyword_arguments,
        )

    hidden_duplicate_mismatch = replace(
        daily_plan,
        items=(
            daily_plan.items[0],
            replace(
                daily_plan.items[1],
                security=replace(
                    daily_plan.items[1].security,
                    symbol="WRONG",
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="identity is inconsistent"):
        bind_daily_refresh_plan_v1(
            hidden_duplicate_mismatch,
            **keyword_arguments,
        )


def test_daily_refresh_fundamental_item_accepts_prior_quarter_snapshot() -> None:
    base_request, _ = _request_and_envelopes(provider_code="EODHD")
    completed_date = base_request.completed_session.session_date
    daily_plan = RefreshPlan(
        as_of=datetime(2026, 7, 29, 20, 7, tzinfo=UTC),
        provider_code="eodhd",
        universe_version="fixture-universe-v1",
        configuration_hash=_hash("fixture-fundamental-refresh-plan"),
        expected_session_date=completed_date,
        items=(
            WorkItem(
                security=SecurityTarget(
                    security_id=base_request.security.security_id,
                    symbol=base_request.security.ticker,
                ),
                dataset=Dataset.FUNDAMENTALS,
                provider_code="eodhd",
                adjustment_mode=None,
                start_date=completed_date,
                end_date=completed_date,
                expected_session_date=completed_date,
                estimated_weighted_calls=1,
            ),
        ),
        estimated_weighted_calls=1,
        available_weighted_calls=None,
    )
    bound = bind_daily_refresh_plan_v1(
        daily_plan,
        securities={
            base_request.security.security_id: base_request.security,
        },
        completed_session=base_request.completed_session,
        provider_routes={"eodhd": "EODHD"},
    )
    _, descriptor, prior_quarter = _domain_adapter_case(
        EvidenceDomain.FUNDAMENTAL,
        requested_field_codes=("REVENUE",),
        start_date=completed_date,
        end_date=completed_date,
        canonical_data=_domain_canonical_data("FUNDAMENTAL"),
    )

    request = bound.items[0].request
    assert request.start_date == request.end_date == completed_date
    assert date.fromisoformat(
        prior_quarter.candidate.canonical_data["periodEnd"]
    ) < request.start_date
    _batch_for(request, prior_quarter).validate_for(request, descriptor)


def test_offline_refresh_unknown_state_fails_before_adapter_call(
    tmp_path: Path,
) -> None:
    request, envelopes = _request_and_envelopes(provider_code="EODHD")
    descriptor = ProviderAdapterDescriptorV1(
        contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
        provider_code="EODHD",
        provider_schema_version="fixture-provider-schema-v1",
        adapter_version="fixture-adapter-v1.0.0",
        supported_domains=(EvidenceDomain.DAILY_PRICE,),
    )
    item = _refresh_item(request, envelopes[0])
    adapter = FakeProviderAdapter(
        descriptor,
        {item.item_id: envelopes[0]},
    )
    private_root = tmp_path / "private-runtime"
    plan = EvidenceRefreshPlanV1(
        run_id=str(uuid4()),
        plan_version=EVIDENCE_REFRESH_PLAN_VERSION,
        items=(item,),
    )
    SymbolExecutionJournal(
        private_root / "journals",
        plan.run_id,
    ).append(
        item.item_id,
        "INTENT",
        {"planHash": plan.content_hash},
    )
    coordinator = ProviderNeutralEvidenceRefreshCoordinatorV1(
        repository=RecordingPersistence(),
        adapters=(adapter,),
        private_runtime_root=private_root,
    )

    with pytest.raises(
        EvidenceRefreshBlocked,
        match="UNKNOWN_EVIDENCE_REFRESH_STATE",
    ):
        coordinator.run(plan)
    assert adapter.calls == []


def test_offline_refresh_reuses_identical_cross_run_evidence_and_rejects_drift(
    tmp_path: Path,
) -> None:
    request, envelopes = _request_and_envelopes(provider_code="YAHOO")
    descriptor = ProviderAdapterDescriptorV1(
        contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
        provider_code="YAHOO",
        provider_schema_version="fixture-provider-schema-v1",
        adapter_version="fixture-adapter-v1.0.0",
        supported_domains=(EvidenceDomain.DAILY_PRICE,),
    )
    first_item = _refresh_item(request, envelopes[0])
    second_item = _refresh_item(request, envelopes[0])
    adapter = FakeProviderAdapter(
        descriptor,
        {
            first_item.item_id: envelopes[0],
            second_item.item_id: envelopes[0],
        },
    )
    persistence = ContentIdempotentPersistence()
    coordinator = ProviderNeutralEvidenceRefreshCoordinatorV1(
        repository=persistence,
        adapters=(adapter,),
        private_runtime_root=tmp_path / "private-runtime",
    )
    first = coordinator.run(
        EvidenceRefreshPlanV1(
            run_id=str(uuid4()),
            plan_version=EVIDENCE_REFRESH_PLAN_VERSION,
            items=(first_item,),
        )
    )
    second = coordinator.run(
        EvidenceRefreshPlanV1(
            run_id=str(uuid4()),
            plan_version=EVIDENCE_REFRESH_PLAN_VERSION,
            items=(second_item,),
        )
    )
    assert first.outcome == EvidenceRefreshOutcome.SUCCEEDED
    assert second.outcome == EvidenceRefreshOutcome.SUCCEEDED
    assert persistence.calls == 2
    assert tuple(persistence.persisted.values()) == (envelopes[0],)

    conflicting = replace(
        envelopes[0],
        candidate=replace(
            envelopes[0].candidate,
            observation_reference=f"fixture:conflict:{uuid4()}",
        ),
    )
    third_item = _refresh_item(request, conflicting)
    adapter._evidence_by_request[third_item.item_id] = conflicting
    with pytest.raises(
        EvidenceFoundationIntegrityConflict,
        match="identity reuse conflicts",
    ):
        coordinator.run(
            EvidenceRefreshPlanV1(
                run_id=str(uuid4()),
                plan_version=EVIDENCE_REFRESH_PLAN_VERSION,
                items=(third_item,),
            )
        )


def test_adapter_batch_rejects_provider_native_cross_boundary() -> None:
    request, envelopes = _request_and_envelopes(provider_code="YAHOO")
    item = _refresh_item(request, envelopes[0])
    wrong_descriptor = ProviderAdapterDescriptorV1(
        contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
        provider_code="YAHOO",
        provider_schema_version="wrong-provider-schema",
        adapter_version="fixture-adapter-v1.0.0",
        supported_domains=(EvidenceDomain.DAILY_PRICE,),
    )
    batch = CanonicalEvidenceBatchV1(
        contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
        request_id=item.item_id,
        provider_code="YAHOO",
        evidence=(envelopes[0],),
    )
    with pytest.raises(
        ValueError,
        match="canonical routing boundary",
    ):
        batch.validate_for(item.request, wrong_descriptor)


def test_adapter_batch_revalidates_nonempty_unique_bound_evidence() -> None:
    request, envelopes = _request_and_envelopes(provider_code="YAHOO")
    item = _refresh_item(request, envelopes[0])
    descriptor = ProviderAdapterDescriptorV1(
        contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
        provider_code="YAHOO",
        provider_schema_version="fixture-provider-schema-v1",
        adapter_version="fixture-adapter-v1.0.0",
        supported_domains=(EvidenceDomain.DAILY_PRICE,),
    )

    with pytest.raises(ValueError, match="must contain canonical evidence"):
        CanonicalEvidenceBatchV1(
            contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
            request_id=item.item_id,
            provider_code="YAHOO",
            evidence=(),
        ).validate_for(item.request, descriptor)

    equivalent_id = replace(
        envelopes[0].candidate,
        evidence_id=envelopes[0].candidate.evidence_id.upper(),
    )
    with pytest.raises(ValueError, match="identifiers must be unique"):
        CanonicalEvidenceBatchV1(
            contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
            request_id=item.item_id,
            provider_code="YAHOO",
            evidence=(
                envelopes[0],
                replace(envelopes[0], candidate=equivalent_id),
            ),
        ).validate_for(item.request, descriptor)

    provider_native = replace(
        envelopes[0].candidate,
        canonical_data={
            **envelopes[0].candidate.canonical_data,
            "providerNativeScore": "99",
        },
    )
    with pytest.raises(ValueError, match="canonicalData"):
        CanonicalEvidenceBatchV1(
            contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
            request_id=item.item_id,
            provider_code="YAHOO",
            evidence=(replace(envelopes[0], candidate=provider_native),),
        ).validate_for(item.request, descriptor)

    wrong_listing = replace(
        envelopes[0].candidate,
        security=replace(
            envelopes[0].candidate.security,
            listing_id=str(uuid4()),
        ),
    )
    with pytest.raises(ValueError, match="routing boundary"):
        CanonicalEvidenceBatchV1(
            contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
            request_id=item.item_id,
            provider_code="YAHOO",
            evidence=(replace(envelopes[0], candidate=wrong_listing),),
        ).validate_for(item.request, descriptor)

    missing_payload = envelopes[0].to_payload()
    missing_payload["state"] = "MISSING"
    missing_payload["reasonCode"] = "NO_PROVIDER_OBSERVATION"
    missing_payload["canonicalData"] = None
    missing = PersistedEvidenceEnvelope.from_payload(
        missing_payload,
        raw_storage_reference=envelopes[0].raw_storage_reference,
    )
    CanonicalEvidenceBatchV1(
        contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
        request_id=item.item_id,
        provider_code="YAHOO",
        evidence=(missing,),
    ).validate_for(item.request, descriptor)


@pytest.mark.parametrize("backfill_size", (3, 260))
def test_adapter_batch_accepts_overlap_and_backfill_within_request_range(
    backfill_size: int,
) -> None:
    request, envelopes = _request_and_envelopes(provider_code="YAHOO")
    end_date = request.completed_session.session_date
    start_date = end_date - timedelta(days=backfill_size - 1)
    item = _refresh_item(request, envelopes[0])
    ranged_request = ProviderEvidenceRequestV1.create(
        provider_code=item.request.provider_code,
        security=item.request.security,
        completed_session=item.request.completed_session,
        domain=item.request.domain,
        requested_field_codes=item.request.requested_field_codes,
        start_date=start_date,
        end_date=end_date,
    )
    descriptor = ProviderAdapterDescriptorV1(
        contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
        provider_code="YAHOO",
        provider_schema_version="fixture-provider-schema-v1",
        adapter_version="fixture-adapter-v1.0.0",
        supported_domains=(EvidenceDomain.DAILY_PRICE,),
    )
    ranged_envelopes = tuple(
        _daily_envelope_for_session(
            envelopes[0],
            session_date=start_date + timedelta(days=ordinal),
            ordinal=ordinal,
        )
        for ordinal in range(backfill_size)
    )
    CanonicalEvidenceBatchV1(
        contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
        request_id=ranged_request.request_id,
        provider_code="YAHOO",
        evidence=ranged_envelopes,
    ).validate_for(ranged_request, descriptor)

    outside = _daily_envelope_for_session(
        envelopes[0],
        session_date=start_date - timedelta(days=1),
        ordinal=backfill_size + 1,
    )
    with pytest.raises(ValueError, match="requested domain scope"):
        CanonicalEvidenceBatchV1(
            contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
            request_id=ranged_request.request_id,
            provider_code="YAHOO",
            evidence=(outside,),
        ).validate_for(ranged_request, descriptor)


@pytest.mark.parametrize("effective_date", ("2026-06-30", "2026-07-30"))
def test_adapter_rejects_corporate_actions_outside_request_range(
    effective_date: str,
) -> None:
    request, descriptor, envelope = _domain_adapter_case(
        EvidenceDomain.CORPORATE_ACTION,
        requested_field_codes=("CORPORATE_ACTION",),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 29),
        canonical_data={
            **_domain_canonical_data("CORPORATE_ACTION"),
            "effectiveDate": effective_date,
        },
    )
    with pytest.raises(ValueError, match="requested domain scope"):
        _batch_for(request, envelope).validate_for(request, descriptor)


def test_adapter_binds_fundamental_metric_and_as_of_period() -> None:
    canonical = _domain_canonical_data("FUNDAMENTAL")
    valid_request, descriptor, valid = _domain_adapter_case(
        EvidenceDomain.FUNDAMENTAL,
        requested_field_codes=("REVENUE",),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 7, 29),
        canonical_data=canonical,
    )
    _batch_for(valid_request, valid).validate_for(valid_request, descriptor)

    unrequested_request, descriptor, unrequested = _domain_adapter_case(
        EvidenceDomain.FUNDAMENTAL,
        requested_field_codes=("NET_INCOME",),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 7, 29),
        canonical_data=canonical,
    )
    with pytest.raises(ValueError, match="requested domain scope"):
        _batch_for(unrequested_request, unrequested).validate_for(
            unrequested_request,
            descriptor,
        )

    prior_period_request, descriptor, prior_period = _domain_adapter_case(
        EvidenceDomain.FUNDAMENTAL,
        requested_field_codes=("REVENUE",),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 29),
        canonical_data=canonical,
    )
    _batch_for(prior_period_request, prior_period).validate_for(
        prior_period_request,
        descriptor,
    )

    future_request, descriptor, future = _domain_adapter_case(
        EvidenceDomain.FUNDAMENTAL,
        requested_field_codes=("REVENUE",),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 29),
        canonical_data={
            **canonical,
            "periodEnd": "2026-07-30",
        },
    )
    with pytest.raises(ValueError, match="requested domain scope"):
        _batch_for(future_request, future).validate_for(
            future_request,
            descriptor,
        )


def test_adapter_classification_snapshot_allows_prestart_and_rejects_future() -> None:
    canonical = _domain_canonical_data("CLASSIFICATION")
    request, descriptor, prestart = _domain_adapter_case(
        EvidenceDomain.CLASSIFICATION,
        requested_field_codes=(
            "SECTOR_CODE",
            "INDUSTRY_CODE",
            "COMPANY_TYPE",
        ),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 29),
        canonical_data=canonical,
    )
    _batch_for(request, prestart).validate_for(request, descriptor)

    future_request, descriptor, future = _domain_adapter_case(
        EvidenceDomain.CLASSIFICATION,
        requested_field_codes=("SECTOR_CODE",),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 29),
        canonical_data={
            **canonical,
            "effectiveFrom": "2026-07-30",
        },
    )
    with pytest.raises(ValueError, match="requested domain scope"):
        _batch_for(future_request, future).validate_for(
            future_request,
            descriptor,
        )


@pytest.mark.parametrize(
    ("domain", "field_codes", "inside_date", "outside_date"),
    (
        (
            EvidenceDomain.CORPORATE_ACTION,
            ("CORPORATE_ACTION",),
            date(2026, 7, 15),
            date(2026, 6, 30),
        ),
        (
            EvidenceDomain.FUNDAMENTAL,
            ("REVENUE",),
            date(2026, 6, 30),
            date(2026, 7, 30),
        ),
        (
            EvidenceDomain.CLASSIFICATION,
            ("SECTOR_CODE",),
            date(2026, 6, 1),
            date(2026, 7, 30),
        ),
    ),
)
def test_adapter_nonvalid_scope_uses_effective_date_without_fake_canonical_data(
    domain: EvidenceDomain,
    field_codes: tuple[str, ...],
    inside_date: date,
    outside_date: date,
) -> None:
    request, descriptor, inside = _domain_adapter_case(
        domain,
        requested_field_codes=field_codes,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 29),
        canonical_data=None,
        state="MISSING",
        effective_date=inside_date,
    )
    _batch_for(request, inside).validate_for(request, descriptor)
    assert inside.candidate.canonical_data is None
    assert inside.candidate.reason_code == "NO_PROVIDER_OBSERVATION"

    outside_request, descriptor, outside = _domain_adapter_case(
        domain,
        requested_field_codes=field_codes,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 29),
        canonical_data=None,
        state="MISSING",
        effective_date=outside_date,
    )
    with pytest.raises(ValueError, match="requested domain scope"):
        _batch_for(outside_request, outside).validate_for(
            outside_request,
            descriptor,
        )


def test_adapter_nonvalid_scope_uses_completed_session_timezone() -> None:
    request, descriptor, envelope = _domain_adapter_case(
        EvidenceDomain.CORPORATE_ACTION,
        requested_field_codes=("CORPORATE_ACTION",),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 29),
        canonical_data=None,
        state="MISSING",
        effective_date=date(2026, 7, 29),
    )
    payload = envelope.to_payload()
    payload["lineage"].update(
        {
            "effectiveAt": "2026-07-30T02:00:00Z",
            "availableAt": "2026-07-30T02:01:00Z",
            "retrievedAt": "2026-07-30T02:03:00Z",
            "ingestedAt": "2026-07-30T02:04:00Z",
            "staleAfter": "2026-07-31T02:00:00Z",
        }
    )
    local_session_envelope = PersistedEvidenceEnvelope.from_payload(
        payload,
        raw_storage_reference=envelope.raw_storage_reference,
    )

    assert request.completed_session.timezone == "America/New_York"
    _batch_for(request, local_session_envelope).validate_for(
        request,
        descriptor,
    )


@pytest.mark.parametrize(
    "domain",
    (
        EvidenceDomain.MARKET_BENCHMARK,
        EvidenceDomain.SECTOR_BENCHMARK,
        EvidenceDomain.LIQUIDITY,
    ),
)
@pytest.mark.parametrize("state", ("VALID", "MISSING"))
def test_adapter_scope_defaults_reject_unimplemented_domains(
    domain: EvidenceDomain,
    state: str,
) -> None:
    base_request, envelopes = _request_and_envelopes(provider_code="EODHD")
    candidate_state = type(envelopes[0].candidate.state)(state)
    candidate = replace(
        envelopes[0].candidate,
        domain=domain.value,
        state=candidate_state,
        reason_code=None if state == "VALID" else "NO_PROVIDER_OBSERVATION",
        canonical_data=(
            _domain_canonical_data(domain.value) if state == "VALID" else None
        ),
    )
    request = ProviderEvidenceRequestV1.create(
        provider_code="EODHD",
        security=base_request.security,
        completed_session=base_request.completed_session,
        domain=domain,
        requested_field_codes=(
            ("BENCHMARK_MAPPING",)
            if domain != EvidenceDomain.LIQUIDITY
            else ("AVERAGE_DAILY_DOLLAR_VOLUME",)
        ),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 29),
    )

    assert not _evidence_matches_requested_scope(candidate, request)


def test_adapter_descriptor_cannot_advertise_unimplemented_domain_as_passthrough() -> None:
    request, descriptor, envelope = _domain_adapter_case(
        EvidenceDomain.MARKET_BENCHMARK,
        requested_field_codes=("BENCHMARK_MAPPING",),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 29),
        canonical_data=_domain_canonical_data("MARKET_BENCHMARK"),
    )

    with pytest.raises(ValueError, match="requested domain scope"):
        _batch_for(request, envelope).validate_for(request, descriptor)


def _request_and_envelopes(
    provider_code: str | None = None,
) -> tuple[EvidenceSelectionRequest, tuple[PersistedEvidenceEnvelope, ...]]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if provider_code is not None:
        payload["selectorPolicy"]["providerFallbackPriority"] = [provider_code]
        payload["candidates"] = payload["candidates"][:2]
        for ordinal, candidate in enumerate(payload["candidates"], start=1):
            candidate["evidenceId"] = str(uuid4())
            candidate["observationReference"] = (
                f"fixture:canonical-evidence:{ordinal}:{uuid4()}"
            )
            candidate["lineage"]["providerCode"] = provider_code
            candidate["lineage"]["providerSchemaVersion"] = (
                "fixture-provider-schema-v1"
            )
            candidate["lineage"]["adapterVersion"] = (
                "fixture-adapter-v1.0.0"
            )
            candidate["lineage"]["sourceRecordId"] = str(uuid4())
            candidate["lineage"]["sourceRevision"] = ordinal
            source_hash = _hash(f"source:{provider_code}:{uuid4()}")
            candidate["lineage"]["sourceContentHash"] = source_hash
            candidate["lineage"]["normalizedRecordHash"] = _hash(
                f"normalized:{provider_code}:{uuid4()}"
            )
            candidate["rawManifest"]["sourceContentHash"] = source_hash
    request = EvidenceSelectionRequest.parse(payload)
    envelopes = tuple(
        PersistedEvidenceEnvelope(
            candidate=candidate,
            raw_storage_reference=(
                f"storage/private/fixtures/{candidate.evidence_id}"
            ),
        )
        for candidate in request.candidates
    )
    return request, envelopes


def _selection_command(request: EvidenceSelectionRequest) -> dict[str, Any]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {
        "contractVersion": SELECTION_COMMAND_VERSION,
        "evidenceContractVersion": request.contract_version,
        "decisionTiming": copy.deepcopy(payload["decisionTiming"]),
        "security": copy.deepcopy(payload["security"]),
        "completedSession": copy.deepcopy(payload["completedSession"]),
        "selectorPolicy": copy.deepcopy(payload["selectorPolicy"]),
        "candidateEvidenceIds": [
            candidate.evidence_id for candidate in request.candidates
        ],
    }


def _refresh_item(
    request: EvidenceSelectionRequest,
    envelope: PersistedEvidenceEnvelope,
    *,
    field_code: str | None = None,
) -> EvidenceRefreshItemV1:
    adapter_request = ProviderEvidenceRequestV1.create(
        provider_code=envelope.candidate.provider_code,
        security=request.security,
        completed_session=request.completed_session,
        domain=EvidenceDomain(envelope.candidate.domain),
        requested_field_codes=(field_code or request.policy.field_code,),
        start_date=date(2026, 7, 29),
        end_date=date(2026, 7, 29),
    )
    return EvidenceRefreshItemV1(
        item_id=adapter_request.request_id,
        request=adapter_request,
    )


def _daily_envelope_for_session(
    template: PersistedEvidenceEnvelope,
    *,
    session_date: date,
    ordinal: int,
) -> PersistedEvidenceEnvelope:
    payload = template.to_payload()
    source_hash = _hash(f"backfill-source:{ordinal}:{uuid4()}")
    payload["evidenceId"] = str(uuid4())
    payload["observationReference"] = f"fixture:backfill:{ordinal}:{uuid4()}"
    payload["canonicalData"]["sessionDate"] = session_date.isoformat()
    payload["lineage"].update(
        {
            "sourceRecordId": str(uuid4()),
            "sourceRevision": 1,
            "sourceContentHash": source_hash,
            "normalizedRecordHash": _hash(
                f"backfill-normalized:{ordinal}:{uuid4()}"
            ),
        }
    )
    payload["rawManifest"]["sourceContentHash"] = source_hash
    return PersistedEvidenceEnvelope.from_payload(
        payload,
        raw_storage_reference=f"storage/private/fixtures/backfill/{uuid4()}",
    )


def _domain_adapter_case(
    domain: EvidenceDomain,
    *,
    requested_field_codes: tuple[str, ...],
    start_date: date,
    end_date: date,
    canonical_data: dict[str, Any] | None,
    state: str = "VALID",
    effective_date: date | None = None,
) -> tuple[
    ProviderEvidenceRequestV1,
    ProviderAdapterDescriptorV1,
    PersistedEvidenceEnvelope,
]:
    base_request, base_envelopes = _request_and_envelopes(
        provider_code="EODHD"
    )
    payload = base_envelopes[0].to_payload()
    source_hash = _hash(f"domain-source:{domain.value}:{uuid4()}")
    payload["evidenceId"] = str(uuid4())
    payload["domain"] = domain.value
    payload["state"] = state
    payload["observationReference"] = (
        f"fixture:adapter-domain:{domain.value.lower()}:{uuid4()}"
    )
    payload["canonicalData"] = copy.deepcopy(canonical_data)
    payload["lineage"].update(
        {
            "sourceRecordId": str(uuid4()),
            "sourceRevision": 1,
            "sourceContentHash": source_hash,
            "normalizedRecordHash": _hash(
                f"domain-normalized:{domain.value}:{uuid4()}"
            ),
        }
    )
    payload["rawManifest"]["sourceContentHash"] = source_hash
    if state != "VALID":
        payload["reasonCode"] = "NO_PROVIDER_OBSERVATION"
        scoped_date = effective_date or end_date
        next_date = scoped_date + timedelta(days=1)
        payload["lineage"].update(
            {
                "effectiveAt": f"{scoped_date.isoformat()}T20:00:00Z",
                "availableAt": f"{scoped_date.isoformat()}T20:01:00Z",
                "retrievedAt": f"{scoped_date.isoformat()}T20:03:00Z",
                "ingestedAt": f"{scoped_date.isoformat()}T20:04:00Z",
                "staleAfter": f"{next_date.isoformat()}T20:00:00Z",
            }
        )
    envelope = PersistedEvidenceEnvelope.from_payload(
        payload,
        raw_storage_reference=f"storage/private/fixtures/domain/{uuid4()}",
    )
    request = ProviderEvidenceRequestV1.create(
        provider_code="EODHD",
        security=base_request.security,
        completed_session=base_request.completed_session,
        domain=domain,
        requested_field_codes=requested_field_codes,
        start_date=start_date,
        end_date=end_date,
    )
    descriptor = ProviderAdapterDescriptorV1(
        contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
        provider_code="EODHD",
        provider_schema_version="fixture-provider-schema-v1",
        adapter_version="fixture-adapter-v1.0.0",
        supported_domains=(domain,),
    )
    return request, descriptor, envelope


def _domain_canonical_data(domain: str) -> dict[str, Any]:
    fixture = json.loads(DOMAIN_FIXTURE.read_text(encoding="utf-8"))
    return copy.deepcopy(
        next(
            example["canonicalData"]
            for example in fixture["examples"]
            if example["domain"] == domain
        )
    )


def _batch_for(
    request: ProviderEvidenceRequestV1,
    envelope: PersistedEvidenceEnvelope,
) -> CanonicalEvidenceBatchV1:
    return CanonicalEvidenceBatchV1(
        contract_version=PROVIDER_ADAPTER_CONTRACT_VERSION,
        request_id=request.request_id,
        provider_code=request.provider_code,
        evidence=(envelope,),
    )


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
