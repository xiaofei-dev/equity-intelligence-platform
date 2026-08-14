from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi.testclient import TestClient

from equity_analysis.dual_system_contract import (
    DataState,
    EvidenceClaimClass,
    EvidenceStrictness,
)
from equity_analysis.evidence_foundation.contracts_v1 import (
    CONTRACT_VERSION as EVIDENCE_CONTRACT_VERSION,
)
from equity_analysis.evidence_foundation.contracts_v1 import (
    SELECTOR_VERSION,
    CompletedSession,
    ConflictCriticality,
    ConflictStatus,
    EvidenceCandidate,
    EvidenceDomain,
    EvidenceLayer,
    EvidenceSelectionRequest,
    SecurityIdentity,
    SelectorPolicy,
)
from equity_analysis.evidence_foundation.persistence_v1 import (
    PersistedSelectorAggregate,
    _request_id,
)
from equity_analysis.evidence_foundation.selector_v1 import select_evidence
from equity_analysis.quant_trading.evidence_assembly_v11 import (
    IDENTITY_REGISTRY_VERSION,
    PRICE_ADJUSTMENT_MODE,
    PRICE_FRESHNESS_VERSION,
    PRICE_NORMALIZATION_VERSION,
    PRICE_POLICY_VERSION,
    PostgresQuantV22RepositoryV11,
    QuantApplicability,
    QuantCrossSectionAssemblyByIdV11,
    QuantEvidenceAssemblyViolation,
    SeriesAssemblyByIdV11,
    SeriesRole,
    TickerAssignmentAuthorityV11,
    V22CompletedSessionAuthorityV11,
    V22SecurityAuthorityV11,
    assemble_quant_cross_section_from_v22_v11,
    security_authority_content_hash_v11,
)
from equity_analysis.quant_trading.research_decision_v11 import (
    QuantResearchDecisionV11,
    QuantResearchDecisionViolation,
    build_quant_research_decision_v11,
)
from equity_analysis.quant_trading.research_persistence_v11 import (
    QuantResearchDecisionRepositoryV11,
    QuantResearchPersistenceViolation,
    validate_quant_research_wire_v11,
)
from equity_analysis.quant_trading.routes_v11 import (
    INTERNAL_QUANT_COMMAND_VERSION,
    get_quant_decision_repository,
    get_quant_v22_repository,
)
from equity_analysis.quant_trading.successor_v11 import (
    MODEL_EVIDENCE_LABEL,
    REQUIRED_HISTORY,
    RankedState,
    rank_cross_section_v11,
)

ROOT = Path(__file__).resolve().parents[2]
ASSEMBLY_CONTRACT = (
    ROOT
    / "contracts"
    / "quant-trading-v1.1"
    / "evidence-assembly-contract.example.json"
)


def _uuid(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"quant-v22-assembly:{name}"))


def _hash(name: str) -> str:
    return "sha256:" + hashlib.sha256(name.encode("utf-8")).hexdigest()


def test_evidence_assembly_contract_is_canonical_and_preserves_safety_boundary() -> None:
    payload = json.loads(ASSEMBLY_CONTRACT.read_text(encoding="utf-8"))
    observed_hash = payload.pop("contentHash")
    expected_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()

    assert observed_hash == expected_hash
    assert payload["modelEvidenceLabel"] == "NOT_VALIDATED"
    assert payload["outputBoundary"]["providerFetchAllowed"] is False
    assert payload["outputBoundary"]["historicalOutcomeAccessAllowed"] is False
    assert (
        payload["outputBoundary"]["automaticBrokerageExecutionAuthorized"]
        is False
    )
    assert payload["outputBoundary"]["llmSignalOrWeightAuthority"] is False


def test_postgres_read_adapter_reconstructs_v22_identity_and_session_authority() -> None:
    authority = _authority(
        "adapter-security",
        ticker="ADP",
        mic="XNAS",
        instrument_type="COMMON_STOCK",
    )
    completed_session = CompletedSession(
        calendar_id="XNAS-US-EQUITIES",
        calendar_version="US-EQUITIES-CALENDAR-v1.0.0",
        mic="XNAS",
        session_date=date(2024, 12, 31),
        timezone="America/New_York",
        scheduled_open=datetime(2024, 12, 31, 14, 30, tzinfo=UTC),
        scheduled_close=datetime(2024, 12, 31, 21, 0, tzinfo=UTC),
        early_close=False,
        completed_at=datetime(2024, 12, 31, 21, 0, tzinfo=UTC),
    )
    recorded = datetime(2025, 1, 1, 0, 0, 0, 123456, tzinfo=UTC)
    identity_row = {
        "security_id": authority.security_id,
        "company_id": authority.company_id,
        "instrument_id": authority.instrument_id,
        "share_class_id": authority.share_class_id,
        "listing_id": authority.listing_id,
        "mic": authority.mic,
        "currency": authority.currency,
        "instrument_type": authority.instrument_type,
        "active": authority.active,
        "registry_version": authority.registry_version,
        "company_recorded_at": recorded,
        "instrument_recorded_at": recorded,
        "share_class_recorded_at": recorded,
        "listing_recorded_at": recorded,
        "ticker_assignment_id": authority.ticker_assignments[0].ticker_assignment_id,
        "ticker": authority.ticker_assignments[0].ticker,
        "valid_from": authority.ticker_assignments[0].valid_from,
        "valid_to": None,
        "ticker_recorded_at": recorded,
    }
    session_row = {
        "completed_session_id": _uuid("adapter-session"),
        "calendar_id": completed_session.calendar_id,
        "calendar_version": completed_session.calendar_version,
        "mic": completed_session.mic,
        "session_date": completed_session.session_date,
        "timezone": completed_session.timezone,
        "scheduled_open": completed_session.scheduled_open,
        "scheduled_close": completed_session.scheduled_close,
        "early_close": completed_session.early_close,
        "completed_at": completed_session.completed_at,
        "session_content_hash": _hash("adapter-session"),
        "session_recorded_at": recorded,
        "calendar_content_hash": _hash("adapter-calendar"),
        "calendar_recorded_at": recorded,
    }

    class Cursor:
        query = ""

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, query, _parameters):
            self.query = query

        def fetchall(self):
            return [identity_row]

        def fetchone(self):
            return session_row

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def cursor(self):
            return Cursor()

    repository = PostgresQuantV22RepositoryV11(
        "postgresql://unit-test",
        connect=lambda *_args, **_kwargs: Connection(),
    )

    loaded_authority = repository.load_security_authority(authority.security_id)
    loaded_session = repository.load_completed_session_authority(
        calendar_id=completed_session.calendar_id,
        calendar_version=completed_session.calendar_version,
        session_date=completed_session.session_date,
    )

    assert loaded_authority.recorded_at == recorded
    assert loaded_authority.ticker_assignments[0].ticker == "ADP"
    assert loaded_session.completed_session == completed_session
    assert loaded_session.recorded_at == recorded


def _authority(
    name: str,
    *,
    ticker: str,
    mic: str,
    instrument_type: str,
) -> V22SecurityAuthorityV11:
    recorded = datetime(2024, 1, 1, tzinfo=UTC)
    ticker_assignment = TickerAssignmentAuthorityV11(
        ticker_assignment_id=_uuid(f"{name}:ticker-assignment"),
        ticker=ticker,
        valid_from=date(2020, 1, 1),
        valid_to=None,
        recorded_at=recorded,
    )
    values = {
        "security_id": _uuid(f"{name}:security"),
        "company_id": _uuid(f"{name}:company"),
        "instrument_id": _uuid(f"{name}:instrument"),
        "share_class_id": _uuid(f"{name}:share-class"),
        "listing_id": _uuid(f"{name}:listing"),
        "mic": mic,
        "currency": "USD",
        "instrument_type": instrument_type,
        "active": True,
        "registry_version": IDENTITY_REGISTRY_VERSION,
        "recorded_at": recorded,
        "ticker_assignments": (ticker_assignment,),
    }
    draft = object.__new__(V22SecurityAuthorityV11)
    for field_name, value in values.items():
        object.__setattr__(draft, field_name, value)
    object.__setattr__(draft, "authority_content_hash", _hash("placeholder"))
    return V22SecurityAuthorityV11(
        **values,
        authority_content_hash=security_authority_content_hash_v11(draft),
    )


def _security(authority: V22SecurityAuthorityV11) -> SecurityIdentity:
    ticker = authority.ticker_assignments[0]
    return SecurityIdentity(
        security_id=authority.security_id,
        company_id=authority.company_id,
        instrument_id=authority.instrument_id,
        share_class_id=authority.share_class_id,
        listing_id=authority.listing_id,
        ticker_assignment_id=ticker.ticker_assignment_id,
        ticker=ticker.ticker,
        mic=authority.mic,
        currency=authority.currency,
    )


def _sessions() -> tuple[date, ...]:
    values: list[date] = []
    current = date(2024, 1, 2)
    while len(values) < REQUIRED_HISTORY:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return tuple(values)


class FakeRepository:
    def __init__(self) -> None:
        self.aggregates: dict[str, PersistedSelectorAggregate] = {}
        self.authorities: dict[str, V22SecurityAuthorityV11] = {}
        self.sessions: dict[tuple[str, str, date], V22CompletedSessionAuthorityV11] = {}

    def clone(self) -> FakeRepository:
        result = FakeRepository()
        result.aggregates = dict(self.aggregates)
        result.authorities = dict(self.authorities)
        result.sessions = dict(self.sessions)
        return result

    def load_selector_aggregate(self, request_id: str) -> PersistedSelectorAggregate:
        try:
            return self.aggregates[request_id]
        except KeyError as error:
            raise LookupError(request_id) from error

    def load_security_authority(self, security_id: str) -> V22SecurityAuthorityV11:
        try:
            return self.authorities[security_id]
        except KeyError as error:
            raise LookupError(security_id) from error

    def load_completed_session_authority(
        self, *, calendar_id: str, calendar_version: str, session_date: date
    ) -> V22CompletedSessionAuthorityV11:
        try:
            return self.sessions[(calendar_id, calendar_version, session_date)]
        except KeyError as error:
            raise LookupError(session_date) from error


def _add_series(
    repository: FakeRepository,
    authority: V22SecurityAuthorityV11,
    *,
    dates: tuple[date, ...],
    decision_cutoff: datetime,
    sealed_cutoff: datetime,
) -> SeriesAssemblyByIdV11:
    repository.authorities[authority.security_id] = authority
    security = _security(authority)
    calendar_id = f"{authority.mic}-US-EQUITIES"
    calendar_version = "US-EQUITIES-CALENDAR-v1.0.0"
    request_ids: list[str] = []
    close = Decimal("50")
    for index, session_date in enumerate(dates):
        close *= Decimal("1.001")
        opened = close * Decimal("0.999")
        high = close * Decimal("1.01")
        low = opened * Decimal("0.99")
        scheduled_open = datetime.combine(session_date, time(14, 30), tzinfo=UTC)
        scheduled_close = datetime.combine(session_date, time(21, 0), tzinfo=UTC)
        completed = scheduled_close
        completed_session = CompletedSession(
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            mic=authority.mic,
            session_date=session_date,
            timezone="America/New_York",
            scheduled_open=scheduled_open,
            scheduled_close=scheduled_close,
            early_close=False,
            completed_at=completed,
        )
        session_authority = V22CompletedSessionAuthorityV11(
            completed_session_id=_uuid(
                f"{authority.security_id}:{calendar_id}:{session_date}:session"
            ),
            completed_session=completed_session,
            session_content_hash=_hash(f"{calendar_id}:{session_date}:session"),
            calendar_content_hash=_hash(f"{calendar_id}:calendar"),
            recorded_at=completed,
        )
        repository.sessions[(calendar_id, calendar_version, session_date)] = (
            session_authority
        )
        source_hash = _hash(f"{authority.security_id}:{session_date}:source")
        candidate = EvidenceCandidate(
            evidence_id=_uuid(f"{authority.security_id}:{session_date}:evidence"),
            domain=EvidenceDomain.DAILY_PRICE.value,
            layer=EvidenceLayer.NORMALIZED_OBSERVATION,
            state=DataState.VALID,
            reason_code=None,
            security=security,
            provider_code="SYNTHETIC_TEST_ONLY",
            provider_schema_version="SYNTHETIC-DAILY-v1.0.0",
            adapter_version="SYNTHETIC-ADAPTER-v1.0.0",
            normalization_version=PRICE_NORMALIZATION_VERSION,
            source_record_id=f"{authority.security_id}:{session_date}",
            source_revision=1,
            source_content_hash=source_hash,
            normalized_record_hash=_hash(
                f"{authority.security_id}:{session_date}:normalized"
            ),
            effective_at=completed,
            available_at=completed,
            retrieved_at=completed,
            ingested_at=completed,
            freshness_policy_version=PRICE_FRESHNESS_VERSION,
            stale_after=None,
            strictness_class=EvidenceStrictness.STRICT_IDENTITY_AND_CHRONOLOGY,
            claim_class=EvidenceClaimClass.CURRENT_ONLY,
            conflict_status=ConflictStatus.NONE,
            conflict_criticality=ConflictCriticality.NONE,
            affected_factors=(),
            observation_reference=f"synthetic:{authority.security_id}:{session_date}",
            derivation_version=None,
            input_evidence_references=(),
            canonical_data={
                "sessionDate": session_date.isoformat(),
                "adjustmentMode": PRICE_ADJUSTMENT_MODE,
                "currency": "USD",
                "open": str(opened),
                "high": str(high),
                "low": str(low),
                "close": str(close),
                "adjustedClose": str(close),
                "volume": 1_000_000 + index,
            },
            tolerance_policy_version=None,
            tolerance_field_code=None,
            supersedes_evidence_id=None,
        )
        policy = SelectorPolicy(
            selector_version=SELECTOR_VERSION,
            policy_version=PRICE_POLICY_VERSION,
            domain=EvidenceDomain.DAILY_PRICE,
            field_code="CLOSE_PRICE",
            required_layer=EvidenceLayer.NORMALIZED_OBSERVATION,
            domain_constraints={
                "sessionDate": session_date.isoformat(),
                "adjustmentMode": PRICE_ADJUSTMENT_MODE,
                "currency": "USD",
                "mic": authority.mic,
                "listingId": authority.listing_id,
            },
            provider_fallback_priority=("SYNTHETIC_TEST_ONLY",),
            required_strictness_class=(
                EvidenceStrictness.STRICT_IDENTITY_AND_CHRONOLOGY
            ),
            required_claim_class=EvidenceClaimClass.CURRENT_ONLY,
            required_normalization_version=PRICE_NORMALIZATION_VERSION,
        )
        request = EvidenceSelectionRequest(
            contract_version=EVIDENCE_CONTRACT_VERSION,
            decision_cutoff=decision_cutoff,
            sealed_ingestion_cutoff=sealed_cutoff,
            security=security,
            completed_session=completed_session,
            policy=policy,
            candidates=(candidate,),
        )
        result = select_evidence(request)
        request_id = str(_request_id(request))
        repository.aggregates[request_id] = PersistedSelectorAggregate(
            request_id=request_id,
            request=request,
            result=result,
        )
        request_ids.append(request_id)
    return SeriesAssemblyByIdV11(
        security_id=authority.security_id,
        role=(
            SeriesRole.MARKET_BENCHMARK_SPY
            if authority.instrument_type == "ETF"
            else SeriesRole.SECURITY
        ),
        price_request_ids=tuple(request_ids),
    )


@pytest.fixture(scope="module")
def controlled_boundary():
    repository = FakeRepository()
    dates = _sessions()
    decision_cutoff = datetime(2025, 1, 1, tzinfo=UTC)
    sealed_cutoff = decision_cutoff
    market = _add_series(
        repository,
        _authority("spy", ticker="SPY", mic="ARCX", instrument_type="ETF"),
        dates=dates,
        decision_cutoff=decision_cutoff,
        sealed_cutoff=sealed_cutoff,
    )
    member_authorities = tuple(
        _authority(
            f"member-{index:02d}",
            ticker=f"Q{index:02d}",
            mic="XNAS",
            instrument_type="COMMON_STOCK",
        )
        for index in range(20)
    )
    ordered = tuple(sorted(member_authorities, key=lambda item: item.security_id))
    members = tuple(
        _add_series(
            repository,
            authority,
            dates=dates,
            decision_cutoff=decision_cutoff,
            sealed_cutoff=sealed_cutoff,
        )
        for authority in ordered
    )
    request = QuantCrossSectionAssemblyByIdV11(
        rebalance_ordinal=0,
        expected_security_ids=tuple(item.security_id for item in ordered),
        market=market,
        members=members,
        decision_cutoff=decision_cutoff,
        sealed_ingestion_cutoff=sealed_cutoff,
    )
    return repository, request


def test_v22_cross_section_assembly_is_provider_neutral_and_executable(
    controlled_boundary,
) -> None:
    repository, request = controlled_boundary
    result = assemble_quant_cross_section_from_v22_v11(repository, request)

    assert result.state is DataState.VALID
    assert result.core_invocation_authorized is True
    assert result.model_evidence_label == MODEL_EVIDENCE_LABEL == "NOT_VALIDATED"
    assert result.engine_input is not None
    assert len(result.market.evidence) == REQUIRED_HISTORY
    assert len(result.members) == 20
    assert all(len(item.evidence) == REQUIRED_HISTORY for item in result.members)
    ranked = rank_cross_section_v11(result.engine_input)
    assert len(ranked) == 20
    assert all(item.state is not RankedState.NOT_RANKED for item in ranked)

    manifest = result.manifest_payload()
    manifest_text = json.dumps(manifest, sort_keys=True)
    assert "open_price" not in manifest_text
    assert '"open"' not in manifest_text
    assert '"close"' not in manifest_text
    assert "automaticBrokerageExecutionAuthorized\": false" in manifest_text
    assert result.manifest_content_hash.startswith("sha256:")

    decision = build_quant_research_decision_v11(result)
    wire = decision.to_wire()
    assert wire["modelEvidenceLabel"] == "NOT_VALIDATED"
    assert len(wire["signals"]) == 20
    assert wire["authority"] == {
        "deterministicResearchSignal": True,
        "deterministicFinalPortfolioWeight": False,
        "automaticBrokerageExecution": False,
        "llmSignalOrWeightAuthority": False,
        "futureReturnGuaranteed": False,
    }
    assert all("finalWeight" not in item for item in wire["signals"])
    assert all("order" not in item for item in wire["signals"])
    assert decision == QuantResearchDecisionV11(**decision.__dict__)


def test_research_decision_tamper_fails_closed(controlled_boundary) -> None:
    repository, request = controlled_boundary
    assembly = assemble_quant_cross_section_from_v22_v11(repository, request)
    decision = build_quant_research_decision_v11(assembly)
    with pytest.raises(
        QuantResearchDecisionViolation,
        match="RESEARCH_DECISION_CONTENT_HASH_DRIFT",
    ):
        replace(decision, rebalance_ordinal=5)


def test_quant_research_projection_persists_and_reads_exactly(controlled_boundary) -> None:
    repository, request = controlled_boundary
    assembly = assemble_quant_cross_section_from_v22_v11(repository, request)
    decision = build_quant_research_decision_v11(assembly)
    durable: dict[str, object] = {}

    class Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, query, parameters=None):
            if "INSERT INTO analytics.quant_research_decision_v1" in query:
                assert parameters is not None
                durable.update(parameters)
                durable["recorded_at"] = datetime(2025, 1, 1, tzinfo=UTC)

        def fetchone(self):
            if not durable:
                return None
            return {
                "decision_id": durable["decision_id"],
                "decision_content_hash": durable["decision_content_hash"],
                "canonical_body_text": durable["canonical_body_text"],
                "payload_sha256": durable["payload_sha256"],
                "canonical_payload_text": durable["canonical_payload_text"],
                "canonical_payload": json.loads(durable["canonical_payload"]),
                "recorded_at": durable["recorded_at"],
            }

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def transaction(self):
            return Transaction()

        def cursor(self):
            return Cursor()

    persistence = QuantResearchDecisionRepositoryV11(
        "postgresql://unit-test",
        connect=lambda *_args, **_kwargs: Connection(),
    )
    persisted = persistence.persist(decision)
    loaded = persistence.load(decision.decision_id)

    assert persisted == loaded
    assert loaded.payload == decision.to_wire()
    assert loaded.payload["authority"]["automaticBrokerageExecution"] is False


def test_public_projection_rejects_authority_and_numeric_tamper(
    controlled_boundary,
) -> None:
    repository, request = controlled_boundary
    decision = build_quant_research_decision_v11(
        assemble_quant_cross_section_from_v22_v11(repository, request)
    )
    payload = decision.to_wire()
    payload["authority"]["automaticBrokerageExecution"] = True
    with pytest.raises(QuantResearchPersistenceViolation, match="QUANT_AUTHORITY_INVALID"):
        validate_quant_research_wire_v11(payload)

    payload = decision.to_wire()
    eligible = next(
        item for item in payload["signals"] if item["rawSignal"]["features"] is not None
    )
    eligible["rawSignal"]["features"]["atr14"] = "1.0"
    with pytest.raises(
        QuantResearchPersistenceViolation,
        match="QUANT_FEATURE_DECIMAL_INVALID",
    ):
        validate_quant_research_wire_v11(payload)


def test_internal_quant_research_routes_create_read_and_fail_closed(
    controlled_boundary,
) -> None:
    from equity_analysis.main import app

    evidence_repository, request = controlled_boundary
    durable: dict[str, object] = {}

    class DecisionRepository:
        def persist(self, decision):
            persisted = type(
                "Persisted",
                (),
                {
                    "decision_id": decision.decision_id,
                    "payload": decision.to_wire(),
                },
            )()
            durable[decision.decision_id] = persisted
            return persisted

        def load(self, decision_id):
            if decision_id not in durable:
                raise LookupError(decision_id)
            return durable[decision_id]

    decision_repository = DecisionRepository()
    command = {
        "contractVersion": INTERNAL_QUANT_COMMAND_VERSION,
        "rebalanceOrdinal": request.rebalance_ordinal,
        "expectedSecurityIds": list(request.expected_security_ids),
        "market": {
            "securityId": request.market.security_id,
            "role": request.market.role.value,
            "priceRequestIds": list(request.market.price_request_ids),
        },
        "members": [
            {
                "securityId": item.security_id,
                "role": item.role.value,
                "priceRequestIds": list(item.price_request_ids),
            }
            for item in request.members
        ],
        "decisionCutoff": request.decision_cutoff.isoformat().replace("+00:00", "Z"),
        "sealedIngestionCutoff": request.sealed_ingestion_cutoff.isoformat().replace(
            "+00:00", "Z"
        ),
    }
    app.dependency_overrides[get_quant_v22_repository] = lambda: evidence_repository
    app.dependency_overrides[get_quant_decision_repository] = lambda: decision_repository
    client = TestClient(app)
    try:
        created = client.post(
            "/internal/v1/quant-trading/research-decisions",
            json=command,
        )
        assert created.status_code == 201
        decision_id = created.json()["decisionId"]
        loaded = client.get(
            f"/internal/v1/quant-trading/research-decisions/{decision_id}"
        )
        assert loaded.status_code == 200
        assert loaded.json() == created.json()
        assert loaded.json()["authority"]["automaticBrokerageExecution"] is False

        malformed = client.get(
            "/internal/v1/quant-trading/research-decisions/NOT-A-UUID"
        )
        assert malformed.status_code == 422
        assert malformed.json() == {
            "detail": {"code": "INVALID_QUANT_RESEARCH_CONTRACT"}
        }
        missing = client.get(
            "/internal/v1/quant-trading/research-decisions/"
            "27000000-0000-4000-8000-999999999999"
        )
        assert missing.status_code == 404
        assert missing.json() == {
            "detail": {"code": "QUANT_RESEARCH_REFERENCE_NOT_FOUND"}
        }
    finally:
        app.dependency_overrides.clear()

def test_missing_member_price_is_explicit_and_preserves_denominator(
    controlled_boundary,
) -> None:
    source_repository, request = controlled_boundary
    repository = source_repository.clone()
    missing_member = request.members[0]
    repository.aggregates.pop(missing_member.price_request_ids[-1])

    result = assemble_quant_cross_section_from_v22_v11(repository, request)

    assert result.state is DataState.VALID
    assert result.engine_input is not None
    assert result.members[0].state is DataState.MISSING
    assert result.members[0].reason_codes == ("V22_PRICE_SELECTOR_NOT_FOUND",)
    assert result.engine_input.expected_security_ids == request.expected_security_ids
    assert result.engine_input.members[0].security == ()
    assert len(result.engine_input.members) == 20
    assert all(
        item.state is RankedState.NOT_RANKED
        for item in rank_cross_section_v11(result.engine_input)
    )


def test_non_common_stock_is_not_applicable_without_numeric_fallback(
    controlled_boundary,
) -> None:
    source_repository, request = controlled_boundary
    repository = source_repository.clone()
    security_id = request.members[0].security_id
    authority = repository.authorities[security_id]
    values = {
        field_name: getattr(authority, field_name)
        for field_name in authority.__dataclass_fields__
        if field_name != "authority_content_hash"
    }
    values["instrument_type"] = "ETF"
    draft = object.__new__(V22SecurityAuthorityV11)
    for field_name, value in values.items():
        object.__setattr__(draft, field_name, value)
    object.__setattr__(draft, "authority_content_hash", _hash("placeholder-2"))
    repository.authorities[security_id] = V22SecurityAuthorityV11(
        **values,
        authority_content_hash=security_authority_content_hash_v11(draft),
    )

    result = assemble_quant_cross_section_from_v22_v11(repository, request)

    assert result.state is DataState.VALID
    assert result.members[0].state is DataState.NOT_APPLICABLE
    assert result.members[0].applicability is QuantApplicability.NOT_APPLICABLE
    assert result.members[0].bars == ()


def test_tampered_selector_result_and_late_authority_fail_closed(
    controlled_boundary,
) -> None:
    source_repository, request = controlled_boundary
    repository = source_repository.clone()
    request_id = request.members[0].price_request_ids[0]
    aggregate = repository.aggregates[request_id]
    repository.aggregates[request_id] = replace(
        aggregate,
        result=replace(aggregate.result, reason_code="TAMPERED"),
    )
    with pytest.raises(
        QuantEvidenceAssemblyViolation, match="SELECTOR_RESULT_REPLAY_DRIFT"
    ):
        assemble_quant_cross_section_from_v22_v11(repository, request)

    repository = source_repository.clone()
    security_id = request.members[0].security_id
    authority = repository.authorities[security_id]
    late = request.sealed_ingestion_cutoff + timedelta(seconds=1)
    values = {
        field_name: getattr(authority, field_name)
        for field_name in authority.__dataclass_fields__
        if field_name not in {"recorded_at", "authority_content_hash"}
    }
    values["recorded_at"] = late
    draft = object.__new__(V22SecurityAuthorityV11)
    for field_name, value in values.items():
        object.__setattr__(draft, field_name, value)
    object.__setattr__(draft, "authority_content_hash", _hash("placeholder-3"))
    repository.authorities[security_id] = V22SecurityAuthorityV11(
        **values,
        authority_content_hash=security_authority_content_hash_v11(draft),
    )
    result = assemble_quant_cross_section_from_v22_v11(repository, request)
    assert result.state is DataState.VALID
    assert result.core_invocation_authorized is True
    assert result.members[0].state is DataState.EXCLUDED
    assert result.engine_input is not None
    assert result.engine_input.members[0].security == ()


def test_mutable_wire_collections_and_duplicate_request_ids_are_rejected(
    controlled_boundary,
) -> None:
    _, request = controlled_boundary
    with pytest.raises(
        QuantEvidenceAssemblyViolation, match="PRICE_REQUEST_IDS_MUST_BE_TUPLE"
    ):
        SeriesAssemblyByIdV11(
            security_id=request.members[0].security_id,
            role=SeriesRole.SECURITY,
            price_request_ids=list(request.members[0].price_request_ids),  # type: ignore[arg-type]
        )
    with pytest.raises(
        QuantEvidenceAssemblyViolation, match="EXPECTED_SECURITY_IDS_MUST_BE_TUPLE"
    ):
        replace(request, expected_security_ids=list(request.expected_security_ids))
    with pytest.raises(
        QuantEvidenceAssemblyViolation, match="CROSS_SERIES_REQUEST_ID_REUSE"
    ):
        replace(
            request,
            members=(
                replace(
                    request.members[0],
                    price_request_ids=request.market.price_request_ids,
                ),
                *request.members[1:],
            ),
        )
