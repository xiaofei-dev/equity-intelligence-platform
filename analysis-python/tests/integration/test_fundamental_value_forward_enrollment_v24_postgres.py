from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from equity_analysis.fundamental_value.prospective_company_quality_v1 import (
    C5_POPULATION_HASH,
    C5_PREDICTOR_CONTRACT_HASH,
    MAX_ABS_PARENT_VALUE,
    MAX_PARENT_FRACTIONAL_DIGITS,
    PARENT_EVIDENCE_COUNT,
    PARENT_ROLE_CONTRACT,
    STAGE7_ACCEPTANCE_HASH,
    CompanyQualityForwardRepositoryV1,
    DecisionSession,
    Enrollment,
    EvidenceBinding,
    Member,
    PlannedEntry,
    TerminalState,
    canonical_decimal_text,
    company_quality_score_from_parents,
    evidence_aggregate_hashes,
    producer_output_hash,
    seal_enrollment,
    seal_member,
)

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL integration acceptance",
)

HASH = "sha256:" + "a" * 64
PROVIDER = "V24_TEST_ONLY_PROVIDER"
SCHEMA_VERSION = "v24-test-provider-schema-v1"
PERIODS = (
    date(2026, 6, 30),
    date(2026, 3, 31),
    date(2025, 12, 31),
    date(2025, 9, 30),
    date(2025, 6, 30),
    date(2025, 3, 31),
    date(2024, 12, 31),
    date(2024, 9, 30),
)


def _uuid(namespace: int, *parts: object) -> UUID:
    digest = hashlib.sha256(
        f"fv-v24-integration:{namespace}:".encode()
        + ":".join(map(str, parts)).encode()
    ).digest()
    return UUID(bytes=digest[:16], version=4)


def _hash(*parts: object) -> str:
    return "sha256:" + hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()


def _value(role: str, member_ordinal: int) -> Decimal:
    return {
        "REVENUE": Decimal("100"),
        "OPERATING_INCOME": Decimal("12") - Decimal(member_ordinal) / 100,
        "NET_INCOME": Decimal("6"),
        "OPERATING_CASH_FLOW": Decimal("8"),
        "CAPITAL_EXPENDITURE": Decimal("2"),
        "INCOME_TAX": Decimal("2"),
        "PRETAX_INCOME": Decimal("10"),
        "STOCKHOLDERS_EQUITY": Decimal("100"),
        "TOTAL_DEBT": Decimal("20"),
        "CASH_AND_EQUIVALENTS": Decimal("10"),
    }[role]


def _seed_identity(
    cursor: psycopg.Cursor[dict[str, object]], ordinal: int, mic: str
) -> dict[str, UUID | str]:
    security_id = _uuid(1, ordinal)
    ids = {
        "security_id": security_id,
        "company_id": _uuid(2, ordinal),
        "instrument_id": _uuid(3, ordinal),
        "share_class_id": _uuid(4, ordinal),
        "listing_id": _uuid(5, ordinal),
        "ticker_assignment_id": _uuid(6, ordinal),
    }
    cursor.execute(
        """INSERT INTO analytics.security
        (public_id,symbol,exchange,name,instrument_type,currency)
        VALUES (%s,%s,'INTEGRATION',%s,'COMMON_STOCK','USD')""",
        (security_id, f"V{ordinal:03d}", f"V24 test security {ordinal}"),
    )
    cursor.execute(
        "INSERT INTO analytics.evidence_company_identity_v1 VALUES (%s,%s,DEFAULT)",
        (ids["company_id"], "security-identity-registry-v1.0.0"),
    )
    cursor.execute(
        "INSERT INTO analytics.evidence_instrument_identity_v1 VALUES (%s,%s,%s,DEFAULT)",
        (ids["instrument_id"], ids["company_id"], "security-identity-registry-v1.0.0"),
    )
    cursor.execute(
        "INSERT INTO analytics.evidence_share_class_identity_v1 VALUES (%s,%s,%s,DEFAULT)",
        (ids["share_class_id"], ids["instrument_id"], "security-identity-registry-v1.0.0"),
    )
    cursor.execute(
        """INSERT INTO analytics.evidence_listing_identity_v1
        VALUES (%s,%s,%s,%s,'USD',%s,DEFAULT)""",
        (ids["listing_id"], ids["share_class_id"], security_id, mic,
         "security-identity-registry-v1.0.0"),
    )
    cursor.execute(
        """INSERT INTO analytics.evidence_ticker_assignment_v1
        (ticker_assignment_id,listing_id,ticker,valid_from,valid_to,registry_version)
        VALUES (%s,%s,%s,DATE '2026-01-01',NULL,%s)""",
        (ids["ticker_assignment_id"], ids["listing_id"], f"V{ordinal:03d}",
         "security-identity-registry-v1.0.0"),
    )
    return {**ids, "listing_mic": mic}


def _seed_prerequisites() -> tuple[Enrollment, str]:
    assert DATABASE_URL is not None
    calendar_version = "v24-test-calendar-v1"
    session_ids = {mic: _uuid(7, "session", mic) for mic in ("XNYS", "XNAS")}
    calendar_ids = {mic: f"v24-test-{mic.lower()}" for mic in session_ids}
    calendar_hashes = {mic: _hash("calendar", mic) for mic in session_ids}
    session_hashes = {mic: _hash("session", mic) for mic in session_ids}
    identities: list[dict[str, UUID | str]] = []
    bindings_by_member: dict[int, list[EvidenceBinding]] = {
        ordinal: [] for ordinal in range(1, 111)
    }
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO analytics.evidence_provider_contract_v1 VALUES (%s,%s,%s,%s,DEFAULT)",
                (PROVIDER, "v24-test-provider-contract-v1", "PRIVATE_LICENSED", "ACTIVE"),
            )
            for mic in ("XNYS", "XNAS"):
                cursor.execute(
                    "INSERT INTO analytics.evidence_trading_calendar_v1 "
                    "VALUES (%s,%s,%s,%s,%s,DEFAULT)",
                    (
                        calendar_ids[mic],
                        calendar_version,
                        mic,
                        "America/New_York",
                        calendar_hashes[mic],
                    ),
                )
                cursor.execute(
                    """INSERT INTO analytics.evidence_completed_session_v1
                    VALUES (%s,%s,%s,%s,DATE '2026-07-29','America/New_York',
                    TIMESTAMPTZ '2026-07-29 13:30:00+00',
                    TIMESTAMPTZ '2026-07-29 20:00:00+00',FALSE,'COMPLETED',
                    TIMESTAMPTZ '2026-07-29 20:00:01+00',%s,
                    TIMESTAMPTZ '2026-07-29 20:00:01+00')""",
                    (
                        session_ids[mic],
                        calendar_ids[mic],
                        calendar_version,
                        mic,
                        session_hashes[mic],
                    ),
                )
            identities.extend(
                _seed_identity(cursor, ordinal, "XNYS" if ordinal <= 122 else "XNAS")
                for ordinal in range(1, 192)
            )
            selected_field_periods = sorted(
                (canonical, period)
                for _, canonical, provenance, count in PARENT_ROLE_CONTRACT
                if provenance == "V22_SELECTED_EVIDENCE"
                for period in PERIODS[:count]
            )
            policies: dict[tuple[str, date], UUID] = {}
            for field, period in selected_field_periods:
                policy_id = _uuid(8, field, period)
                policies[(field, period)] = policy_id
                cursor.execute(
                    """INSERT INTO analytics.evidence_selector_policy_v1
                    VALUES (%s,'deterministic-evidence-selector-v1.0.0',%s,
                    'FUNDAMENTAL',%s,'NORMALIZED_OBSERVATION',%s,
                    'STRICT_IDENTITY_AND_CHRONOLOGY','CURRENT_ONLY',%s,%s,DEFAULT)""",
                    (policy_id, f"v24-test-{field.lower()}-{period}-v1", field,
                     Jsonb({"metricCode": field, "periodEnd": str(period),
                            "unit": "USD", "currency": "USD"}),
                     "v24-test-normalization-v1", _hash("policy", field, period)),
                )
                cursor.execute(
                    "INSERT INTO analytics.evidence_selector_provider_priority_v1 "
                    "VALUES (%s,1,%s,DEFAULT)",
                    (policy_id, PROVIDER),
                )
                cursor.execute(
                    "INSERT INTO analytics.evidence_selector_policy_seal_v1 VALUES (%s,1,DEFAULT)",
                    (policy_id,),
                )
            cursor.execute("SET LOCAL session_replication_role=replica")
            for member_ordinal in range(1, 111):
                identity = identities[member_ordinal - 1]
                evidence_ordinal = 0
                for role, canonical_field, provenance, count in PARENT_ROLE_CONTRACT:
                    for period in PERIODS[:count]:
                        evidence_ordinal += 1
                        raw_id = _uuid(9, member_ordinal, evidence_ordinal)
                        source_hash = _hash("source", member_ordinal, evidence_ordinal)
                        normalized_hash = _hash("normalized", member_ordinal, evidence_ordinal)
                        source_record_id = f"v24-{member_ordinal}-{evidence_ordinal}"
                        effective_at = datetime.combine(period, datetime.min.time(), UTC)
                        available_at = datetime(2026, 7, 2, 12, tzinfo=UTC)
                        ingested_at = datetime(2026, 7, 2, 13, tzinfo=UTC)
                        period_start = (
                            None
                            if role in {
                                "STOCKHOLDERS_EQUITY",
                                "TOTAL_DEBT",
                                "CASH_AND_EQUIVALENTS",
                            }
                            else period - timedelta(days=89)
                        )
                        cursor.execute(
                            """INSERT INTO analytics.evidence_raw_manifest_v1
                            (id,provider_code,provider_schema_version,source_record_id,
                            source_revision,source_content_hash,storage_class,payload_stored_in_git,
                            storage_reference,effective_at,available_at,retrieved_at,ingested_at)
                            VALUES (%s,%s,%s,%s,1,%s,'PRIVATE_GIT_IGNORED',FALSE,
                            %s,%s,%s,NULL,%s)""",
                            (raw_id, PROVIDER, SCHEMA_VERSION, source_record_id, source_hash,
                             f"test-only://{source_record_id}", effective_at, available_at,
                             ingested_at),
                        )
                        request_id: UUID | None = None
                        result_hash: str | None = None
                        evidence_id: UUID | None = None
                        normalized_parent_id: UUID | None = None
                        if provenance == "V22_SELECTED_EVIDENCE":
                            evidence_id = _uuid(10, member_ordinal, evidence_ordinal)
                            request_id = _uuid(11, member_ordinal, evidence_ordinal)
                            result_hash = _hash("result", member_ordinal, evidence_ordinal)
                            cursor.execute(
                                """INSERT INTO analytics.canonical_evidence_v1
                                (evidence_id,contract_version,domain,layer,state,reason_code,
                                security_id,company_id,instrument_id,share_class_id,listing_id,
                                ticker_assignment_id,ticker,mic,currency,provider_code,
                                provider_schema_version,adapter_version,normalization_version,
                                source_record_id,source_revision,source_content_hash,
                                normalized_record_hash,effective_at,available_at,retrieved_at,
                                ingested_at,freshness_policy_version,stale_after,strictness_class,
                                claim_class,conflict_status,conflict_criticality,affected_factors,
                                tolerance_policy_version,tolerance_field_code,tolerance_alignment,
                                observation_reference,raw_manifest_id,derivation_version,
                                derivation_output_hash,canonical_data,supersedes_evidence_id)
                                VALUES (%s,'unified-market-data-evidence-foundation-v1.0.0',
                                'FUNDAMENTAL','NORMALIZED_OBSERVATION','VALID',NULL,
                                %s,%s,%s,%s,%s,%s,%s,%s,'USD',%s,%s,%s,%s,%s,1,%s,%s,
                                %s,%s,NULL,%s,%s,NULL,'STRICT_IDENTITY_AND_CHRONOLOGY',
                                'CURRENT_ONLY','NONE','NONE','[]',NULL,NULL,NULL,%s,%s,NULL,NULL,%s,NULL)""",
                                (evidence_id, identity["security_id"], identity["company_id"],
                                 identity["instrument_id"], identity["share_class_id"],
                                 identity["listing_id"], identity["ticker_assignment_id"],
                                 f"V{member_ordinal:03d}", identity["listing_mic"], PROVIDER,
                                 SCHEMA_VERSION,
                                 "v24-test-adapter-v1", "v24-test-normalization-v1",
                                 source_record_id, source_hash, normalized_hash, effective_at,
                                 available_at, ingested_at, "v24-test-freshness-v1",
                                 f"test-only://{source_record_id}", raw_id,
                                 Jsonb({"metricCode": canonical_field,
                                     "numericValue": str(_value(role, member_ordinal)),
                                     "unit": "USD", "currency": "USD",
                                     "periodStart": (
                                         None if period_start is None else str(period_start)
                                     ),
                                     "periodEnd": str(period), "fiscalPeriod": "Q",
                                     "formType": "TEST_ONLY", "accessionNumber": source_record_id,
                                     "filedAt": "2026-07-01T12:00:00Z",
                                     "mappingVersion": "v24-test-mapping-v1"})),
                            )
                            cursor.execute(
                                """INSERT INTO analytics.evidence_selection_request_v1
                                VALUES (%s,'unified-market-data-evidence-foundation-v1.0.0',
                                %s,%s,%s,%s,%s,%s,%s,%s,TIMESTAMPTZ '2026-07-30 21:00:00+00',
                                TIMESTAMPTZ '2026-07-30 21:00:00+00',%s,DEFAULT)""",
                                (request_id, policies[(canonical_field, period)],
                                 identity["security_id"],
                                 identity["company_id"], identity["instrument_id"],
                                 identity["share_class_id"], identity["listing_id"],
                                 identity["ticker_assignment_id"],
                                 session_ids[str(identity["listing_mic"])],
                                 _hash("request", member_ordinal, evidence_ordinal)),
                            )
                            cursor.execute(
                                "INSERT INTO analytics.evidence_selection_candidate_v1 "
                                "VALUES (%s,1,%s,DEFAULT)",
                                (request_id, evidence_id),
                            )
                            cursor.execute(
                                """INSERT INTO analytics.evidence_selection_result_v1
                                VALUES (%s,'deterministic-evidence-selector-v1.0.0','VALID',
                                'SELECTED_VALID_EVIDENCE',%s,%s,DEFAULT)""",
                                (request_id, evidence_id, result_hash),
                            )
                            cursor.execute(
                                "INSERT INTO analytics.evidence_selection_seal_v1 "
                                "VALUES (%s,1,0,DEFAULT)",
                                (request_id,),
                            )
                        else:
                            normalized_parent_id = UUID(
                                int=800_000 + member_ordinal * 100 + evidence_ordinal
                            )
                            cursor.execute(
                                """INSERT INTO analytics.fv_cq_forward_normalized_parent_v1
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                %s,%s,%s,%s,%s,%s,%s,%s)""",
                                (
                                    normalized_parent_id,
                                    identity["security_id"], identity["company_id"],
                                    identity["instrument_id"], identity["share_class_id"],
                                    identity["listing_id"], identity["ticker_assignment_id"],
                                    raw_id, canonical_field, _value(role, member_ordinal),
                                    period_start, period, source_hash, normalized_hash,
                                    PROVIDER, SCHEMA_VERSION, source_record_id, 1,
                                    effective_at, available_at, ingested_at, "USD", "USD",
                                ),
                            )
                        bindings_by_member[member_ordinal].append(
                            EvidenceBinding(
                                evidence_ordinal=evidence_ordinal,
                                operand_code=role,
                                canonical_field_code=canonical_field,
                                provenance_kind=provenance,
                                numeric_value=_value(role, member_ordinal),
                                selection_request_id=request_id,
                                selection_result_hash=result_hash,
                                canonical_evidence_id=evidence_id,
                                normalized_parent_id=normalized_parent_id,
                                raw_manifest_id=raw_id,
                                provider_code=PROVIDER,
                                provider_schema_version=SCHEMA_VERSION,
                                source_record_id=source_record_id,
                                source_revision=1,
                                parent_period_start=period_start,
                                parent_period_end=period,
                                parent_source_content_hash=source_hash,
                                parent_normalized_record_hash=normalized_hash,
                                parent_effective_at=effective_at,
                                parent_available_at=available_at,
                                parent_ingested_at=ingested_at,
                                currency="USD",
                                unit="USD",
                            )
                        )
            cursor.execute("SET LOCAL session_replication_role=origin")
    usable_unranked: list[Member] = []
    for ordinal in range(1, 111):
        identity = identities[ordinal - 1]
        evidence = tuple(bindings_by_member[ordinal])
        evidence_hash, source_hash = evidence_aggregate_hashes(evidence)
        score = company_quality_score_from_parents(evidence)
        usable_unranked.append(
            Member(
                member_ordinal=ordinal,
                **identity,
                terminal_state=TerminalState.USABLE_VALID,
                reasons=(),
                predictor_score=score,
                evidence_available_at=datetime(2026, 7, 2, 12, tzinfo=UTC),
                evidence_ingested_at=datetime(2026, 7, 2, 13, tzinfo=UTC),
                evidence_content_hash=evidence_hash,
                source_content_hash=source_hash,
                producer_contract_content_hash=C5_PREDICTOR_CONTRACT_HASH,
                producer_output_content_hash=producer_output_hash(
                    score, evidence_hash, source_hash
                ),
                evidence=evidence,
            )
        )
    ranked_ids = {
        row.security_id: rank
        for rank, row in enumerate(
            sorted(usable_unranked, key=lambda row: (-row.predictor_score, str(row.security_id))),
            1,
        )
    }
    members: list[Member] = []
    for row in usable_unranked:
        rank = ranked_ids[row.security_id]
        members.append(
            seal_member(
                replace(
                    row,
                    predictor_rank=rank,
                    predictor_group="HIGH" if rank <= 22 else "LOW" if rank > 88 else "MIDDLE",
                )
            )
        )
    for ordinal in range(111, 192):
        members.append(
            seal_member(
                Member(
                    member_ordinal=ordinal,
                    **identities[ordinal - 1],
                    terminal_state=TerminalState.MISSING,
                    reasons=("TEST_ONLY_CURRENT_PARENT_MISSING",),
                )
            )
        )
    enrollment = seal_enrollment(
        Enrollment(
            enrollment_id=_uuid(12, "enrollment"),
            decision_sessions=tuple(
                DecisionSession(
                    mic=mic,
                    completed_session_id=session_ids[mic],
                    calendar_id=calendar_ids[mic],
                    calendar_version=calendar_version,
                    session_date=date(2026, 7, 29),
                    scheduled_open=datetime(2026, 7, 29, 13, 30, tzinfo=UTC),
                    scheduled_close=datetime(2026, 7, 29, 20, tzinfo=UTC),
                    early_close=False,
                    completed_at=datetime(2026, 7, 29, 20, 0, 1, tzinfo=UTC),
                    recorded_at=datetime(2026, 7, 29, 20, 0, 1, tzinfo=UTC),
                    session_content_hash=session_hashes[mic],
                    calendar_content_hash=calendar_hashes[mic],
                )
                for mic in ("XNAS", "XNYS")
            ),
            planned_entries=tuple(
                PlannedEntry(
                    mic=mic,
                    schedule_source_id=f"v24-test-schedule-{mic.lower()}",
                    schedule_source_version="v24-test-schedule-v1",
                    schedule_source_content_hash=_hash("schedule-source", mic),
                    entry_date=date(2026, 7, 31),
                    scheduled_open=datetime(2026, 7, 31, 13, 30, tzinfo=UTC),
                    scheduled_close=datetime(2026, 7, 31, 20, tzinfo=UTC),
                    early_close=False,
                    schedule_content_hash=_hash("schedule", mic),
                )
                for mic in ("XNAS", "XNYS")
            ),
            decision_cutoff=datetime(2026, 7, 30, 21, tzinfo=UTC),
            evidence_cutoff=datetime(2026, 7, 30, 21, tzinfo=UTC),
            sealed_at=datetime(2026, 7, 30, 22, tzinfo=UTC),
            population_content_hash=C5_POPULATION_HASH,
            evidence_manifest_content_hash=_hash("evidence-manifest"),
            predictor_contract_content_hash=C5_PREDICTOR_CONTRACT_HASH,
            producer_version="FV-STAGE7C5-EODHD-PROVIDER-NATIVE-COMPANY-QUALITY-v1.0.0",
            arithmetic_version="FV-STAGE7C9-DECIMAL-ARITHMETIC-v1.0.0",
            cost_policy_version="LIQUIDITY-SENSITIVE-COST-v1.0.0",
            outcome_policy_version="FV-STAGE8A-READINESS-PREREGISTRATION-v1.0.0",
            outcome_protocol_content_hash=_hash("outcome-protocol"),
            stage7_acceptance_content_hash=STAGE7_ACCEPTANCE_HASH,
            idempotency_key="fv-v24-postgres-integration",
            members=tuple(members),
            content_hash="",
        )
    )
    return enrollment, DATABASE_URL


@pytest.fixture(scope="module")
def v24_postgres_enrollment() -> tuple[Enrollment, str]:
    return _seed_prerequisites()


def test_v24_typed_repository_round_trip_and_idempotency(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    assert sum(count for *_, count in PARENT_ROLE_CONTRACT) == PARENT_EVIDENCE_COUNT == 63
    assert sum(
        member.terminal_state is TerminalState.USABLE_VALID
        for member in enrollment.members
    ) == 110
    assert sum(
        member.terminal_state is TerminalState.MISSING for member in enrollment.members
    ) == 81
    assert sum(len(member.evidence) for member in enrollment.members) == 6_930
    repository = CompanyQualityForwardRepositoryV1(database_url)
    assert repository.enroll(enrollment) == enrollment.enrollment_id
    assert repository.get(enrollment.enrollment_id) == enrollment
    assert repository.enroll(enrollment) == enrollment.enrollment_id
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        roles = connection.execute(
            "SELECT operand_code,canonical_field_code,provenance_kind,required_count "
            "FROM analytics.fv_cq_forward_parent_role_v1 ORDER BY operand_code"
        ).fetchall()
        assert sum(row["required_count"] for row in roles) == PARENT_EVIDENCE_COUNT
        assert len(roles) == len(PARENT_ROLE_CONTRACT)
        maturity = connection.execute(
            "SELECT horizon_sessions,maturity_state,outcome_row_count "
            "FROM analytics.fv_cq_forward_maturity_v1 WHERE enrollment_id=%s "
            "ORDER BY horizon_sessions",
            (enrollment.enrollment_id,),
        ).fetchall()
        assert [(row["horizon_sessions"], row["outcome_row_count"]) for row in maturity] == [
            (252, 0), (504, 0), (756, 0)
        ]
        assert {row["maturity_state"] for row in maturity} == {"AWAITING_NATURAL_MATURITY"}
        assert connection.execute(
            "SELECT listing_mic,count(*) FROM analytics.fv_cq_forward_member_v1 "
            "WHERE enrollment_id=%s GROUP BY listing_mic ORDER BY listing_mic",
            (enrollment.enrollment_id,),
        ).fetchall() == [
            {"listing_mic": "XNAS", "count": 69},
            {"listing_mic": "XNYS", "count": 122},
        ]
        assert connection.execute(
            "SELECT count(*) FROM analytics.fv_cq_forward_decision_session_v1 "
            "WHERE enrollment_id=%s",
            (enrollment.enrollment_id,),
        ).fetchone()["count"] == 2
        assert connection.execute(
            "SELECT count(*) FROM analytics.fv_cq_forward_planned_entry_v1 "
            "WHERE enrollment_id=%s AND state='SCHEDULED_NOT_COMPLETED'",
            (enrollment.enrollment_id,),
        ).fetchone()["count"] == 2


def test_v24_python_and_postgres_decimal_canonical_vectors(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    _, database_url = v24_postgres_enrollment
    vectors = (
        Decimal("1.2300"),
        Decimal("1.23E+2"),
        Decimal("-0.000"),
        Decimal("0.0000000000000000000000000001"),
        Decimal("1234567890123456789012345678"),
    )
    with psycopg.connect(database_url) as connection:
        observed = [
            connection.execute(
                "SELECT analytics.fv_cq_forward_decimal_text_v1(%s::NUMERIC)",
                (value,),
            ).fetchone()[0]
            for value in vectors
        ]
    assert observed == [canonical_decimal_text(value) for value in vectors]


def test_v24_python_and_postgres_decimal28_score_boundary(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    role_values = {
        "REVENUE": Decimal("25000000000000000000000"),
        "OPERATING_INCOME": Decimal("12501750000000000000001") / 4,
        "INCOME_TAX": Decimal(0),
        "PRETAX_INCOME": Decimal(1),
        "STOCKHOLDERS_EQUITY": Decimal("124942534479312412552478.5129"),
        "TOTAL_DEBT": Decimal(0),
        "CASH_AND_EQUIVALENTS": Decimal(0),
        "NET_INCOME": Decimal(1),
        "OPERATING_CASH_FLOW": Decimal(1),
        "CAPITAL_EXPENDITURE": Decimal("2500000000000000000001"),
    }
    original = enrollment.members[0].evidence
    boundary = tuple(
        replace(item, numeric_value=role_values[item.operand_code]) for item in original
    )
    python_score = company_quality_score_from_parents(boundary)
    assert python_score == Decimal("60.01")
    context_vectors = (
        Decimal("12501750000000000000001") / Decimal("100000000000000000000000"),
        Decimal("-12501750000000000000001") / Decimal("100000000000000000000000"),
        Decimal("0.000000000000000000000000000123456789"),
    )
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        expected_context = [+value for value in context_vectors]
    with psycopg.connect(database_url) as connection:
        assert [
            connection.execute(
                "SELECT analytics.fv_cq_context28_v1(%s::NUMERIC)", (value,)
            ).fetchone()[0]
            for value in context_vectors
        ] == expected_context
        with connection.transaction():
            connection.execute("SET LOCAL session_replication_role=replica")
            for item in boundary:
                connection.execute(
                    "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                    "SET numeric_value=%s WHERE enrollment_id=%s "
                    "AND member_ordinal=1 AND evidence_ordinal=%s",
                    (item.numeric_value, enrollment.enrollment_id, item.evidence_ordinal),
                )
            assert connection.execute(
                "SELECT analytics.fv_cq_forward_expected_score_v1(%s,1)",
                (enrollment.enrollment_id,),
            ).fetchone()[0] == python_score
            for item in original:
                connection.execute(
                    "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                    "SET numeric_value=%s WHERE enrollment_id=%s "
                    "AND member_ordinal=1 AND evidence_ordinal=%s",
                    (item.numeric_value, enrollment.enrollment_id, item.evidence_ordinal),
                )


def test_v24_conflict_race_and_append_only_controls(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    repository = CompanyQualityForwardRepositoryV1(database_url)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: repository.enroll(enrollment), range(2)))
    assert results == [enrollment.enrollment_id, enrollment.enrollment_id]
    conflicting = seal_enrollment(
        replace(
            enrollment,
            planned_entries=(
                replace(
                    enrollment.planned_entries[0],
                    schedule_content_hash=_hash("conflicting-entry"),
                ),
                enrollment.planned_entries[1],
            ),
        )
    )
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        repository.enroll(conflicting)
    with psycopg.connect(database_url) as connection:
        for statement in (
            "UPDATE analytics.fv_cq_forward_member_v1 SET predictor_score=0 WHERE enrollment_id=%s",
            "UPDATE analytics.fv_cq_forward_member_v1 SET row_content_hash='sha256:" + "0" * 64
            + "' WHERE enrollment_id=%s",
            "UPDATE analytics.fv_cq_forward_enrollment_v1 SET enrollment_content_hash='sha256:"
            + "0" * 64 + "' WHERE enrollment_id=%s",
            "UPDATE analytics.fv_cq_forward_enrollment_seal_v1 SET seal_content_hash='sha256:"
            + "0" * 64 + "' WHERE enrollment_id=%s",
            "DELETE FROM analytics.fv_cq_forward_member_v1 WHERE enrollment_id=%s",
            "TRUNCATE analytics.fv_cq_forward_maturity_v1",
            "UPDATE analytics.fv_cq_forward_maturity_v1 SET outcome_row_count=1 "
            "WHERE enrollment_id=%s",
            "UPDATE analytics.fv_cq_forward_parent_role_v1 SET required_count=1 "
            "WHERE operand_code='REVENUE'",
            "DELETE FROM analytics.fv_cq_forward_parent_role_v1 "
            "WHERE operand_code='REVENUE'",
            "TRUNCATE analytics.fv_cq_forward_parent_role_v1",
            "UPDATE analytics.fv_cq_forward_normalized_parent_v1 SET numeric_value=0",
        ):
            with pytest.raises(psycopg.Error):
                with connection.transaction():
                    connection.execute(statement, (enrollment.enrollment_id,))
        with pytest.raises(psycopg.Error, match="FV_CQ_FORWARD_ALREADY_SEALED"):
            with connection.transaction():
                connection.execute(
                    """INSERT INTO analytics.fv_cq_forward_member_reason_v1
                    VALUES (%s,101,2,'LATE_REASON')""",
                    (enrollment.enrollment_id,),
                )
        with connection.transaction():
            connection.execute("SET LOCAL ROLE analytics_writer")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "INSERT INTO analytics.fv_cq_forward_enrollment_v1 "
                    "SELECT * FROM analytics.fv_cq_forward_enrollment_v1 WHERE false"
                )
        with connection.transaction():
            connection.execute("SET LOCAL ROLE analytics_fv_cq_forward_writer_v1")
            assert connection.execute(
                "SELECT count(*) FROM analytics.fv_cq_forward_parent_role_v1"
            ).fetchone()[0] == len(PARENT_ROLE_CONTRACT)
            assert connection.execute(
                "SELECT count(*) FROM analytics.evidence_raw_manifest_v1"
            ).fetchone()[0] > 0
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "INSERT INTO analytics.fv_cq_forward_normalized_parent_v1 "
                    "SELECT * FROM analytics.fv_cq_forward_normalized_parent_v1 WHERE false"
                )
        for statement in (
            "UPDATE analytics.evidence_raw_manifest_v1 SET source_revision=source_revision",
            "DELETE FROM analytics.evidence_raw_manifest_v1 WHERE false",
            "TRUNCATE analytics.evidence_raw_manifest_v1",
            "UPDATE analytics.fv_cq_forward_parent_role_v1 SET required_count=required_count",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE analytics_fv_cq_forward_writer_v1")
                    connection.execute(statement)
        with connection.transaction():
            connection.execute("SET LOCAL ROLE analytics_fv_cq_forward_writer_v1")
            with pytest.raises(psycopg.Error, match="FV_CQ_FORWARD_ALREADY_SEALED"):
                connection.execute(
                    "INSERT INTO analytics.fv_cq_forward_member_reason_v1 "
                    "VALUES (%s,101,2,'SEMANTIC_WRITER_LATE_REASON')",
                    (enrollment.enrollment_id,),
                )
        with connection.transaction():
            connection.execute(
                "SET LOCAL ROLE analytics_fv_cq_normalized_parent_writer_v1"
            )
            connection.execute(
                "INSERT INTO analytics.fv_cq_forward_normalized_parent_v1 "
                "SELECT * FROM analytics.fv_cq_forward_normalized_parent_v1 WHERE false"
            )
        for statement in (
            "UPDATE analytics.fv_cq_forward_normalized_parent_v1 SET numeric_value=0",
            "DELETE FROM analytics.fv_cq_forward_normalized_parent_v1",
            "TRUNCATE analytics.fv_cq_forward_normalized_parent_v1",
        ):
            with pytest.raises(psycopg.Error):
                with connection.transaction():
                    connection.execute(
                        "SET LOCAL ROLE analytics_fv_cq_normalized_parent_writer_v1"
                    )
                    connection.execute(statement)


def _wait_for_database_wait(
    database_url: str, application_name: str, future: object | None = None
) -> None:
    with psycopg.connect(database_url, autocommit=True) as observer:
        for _ in range(2400):
            row = observer.execute(
                "SELECT wait_event_type FROM pg_stat_activity "
                "WHERE application_name=%s",
                (application_name,),
            ).fetchone()
            if row is not None and row[0] == "Lock":
                return
            if future is not None and future.done():  # type: ignore[union-attr]
                future.result()  # type: ignore[union-attr]
            time.sleep(0.05)
    raise AssertionError(f"{application_name} did not reach the required lock wait")


@pytest.mark.parametrize("extra_kind", ("reason", "evidence"))
def test_v24_concurrent_post_seal_child_insert_revalidates_aggregate(
    v24_postgres_enrollment: tuple[Enrollment, str],
    extra_kind: str,
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    candidate = _clone(enrollment, f"aggregate-toctou-{extra_kind}")
    seal_lock_key = 8_240_000 + (1 if extra_kind == "reason" else 2)
    child_lock_key = seal_lock_key + 100
    trigger_name = f"fv_cq_test_pause_seal_{extra_kind}"
    function_name = f"analytics.fv_cq_test_pause_seal_{extra_kind}"
    child_trigger_name = f"zz_fv_cq_test_pause_child_{extra_kind}"
    child_function_name = f"analytics.fv_cq_test_pause_child_{extra_kind}"
    child_table = (
        "fv_cq_forward_member_reason_v1"
        if extra_kind == "reason"
        else "fv_cq_forward_member_evidence_v1"
    )
    t1_url = database_url + f"?application_name=fv_cq_toctou_t1_{extra_kind}"
    t2_url = database_url + f"?application_name=fv_cq_toctou_t2_{extra_kind}"
    extra_normalized_id: UUID | None = None

    with psycopg.connect(database_url) as setup:
        setup.execute(
            f"""CREATE FUNCTION {function_name}() RETURNS TRIGGER
            LANGUAGE plpgsql AS $$ BEGIN
              PERFORM pg_advisory_lock({seal_lock_key});
              PERFORM pg_advisory_unlock({seal_lock_key});
              RETURN NEW;
            END $$"""
        )
        setup.execute(
            f"CREATE TRIGGER {trigger_name} AFTER INSERT ON "
            "analytics.fv_cq_forward_enrollment_seal_v1 FOR EACH ROW "
            f"EXECUTE FUNCTION {function_name}()"
        )
        setup.execute(
            f"""CREATE FUNCTION {child_function_name}() RETURNS TRIGGER
            LANGUAGE plpgsql AS $$ BEGIN
              IF current_setting('application_name')=
                 'fv_cq_toctou_t2_{extra_kind}' THEN
                PERFORM pg_advisory_lock({child_lock_key});
                PERFORM pg_advisory_unlock({child_lock_key});
              END IF;
              RETURN NEW;
            END $$"""
        )
        setup.execute(
            f"CREATE TRIGGER {child_trigger_name} BEFORE INSERT ON "
            f"analytics.{child_table} FOR EACH ROW "
            f"EXECUTE FUNCTION {child_function_name}()"
        )
        if extra_kind == "evidence":
            source = next(
                item
                for item in candidate.members[0].evidence
                if item.provenance_kind == "V24_PROVIDER_NORMALIZED_PARENT"
            )
            assert source.normalized_parent_id is not None
            extra_normalized_id = uuid4()
            setup.execute(
                """INSERT INTO analytics.fv_cq_forward_normalized_parent_v1
                SELECT %s,security_id,company_id,instrument_id,share_class_id,
                  listing_id,ticker_assignment_id,raw_manifest_id,canonical_field_code,
                  numeric_value,NULL,DATE '2000-01-01',source_content_hash,%s,
                  provider_code,provider_schema_version,source_record_id,source_revision,
                  effective_at,available_at,ingested_at,currency,unit
                FROM analytics.fv_cq_forward_normalized_parent_v1
                WHERE normalized_parent_id=%s""",
                (
                    extra_normalized_id,
                    _hash("toctou-extra-normalized"),
                    source.normalized_parent_id,
                ),
            )

    def insert_extra_child() -> None:
        with psycopg.connect(t2_url) as connection:
            if extra_kind == "reason":
                connection.execute(
                    "INSERT INTO analytics.fv_cq_forward_member_reason_v1 "
                    "VALUES (%s,111,2,'TOCTOU_EXTRA_REASON')",
                    (candidate.enrollment_id,),
                )
            else:
                assert extra_normalized_id is not None
                connection.execute(
                    """INSERT INTO analytics.fv_cq_forward_member_evidence_v1
                    (enrollment_id,member_ordinal,evidence_ordinal,operand_code,
                    canonical_field_code,provenance_kind,numeric_value,
                    selection_request_id,selection_result_hash,canonical_evidence_id,
                    normalized_parent_id,raw_manifest_id,provider_code,
                    provider_schema_version,source_record_id,source_revision,
                    parent_period_start,parent_period_end,parent_source_content_hash,
                    parent_normalized_record_hash,parent_effective_at,parent_available_at,
                    parent_ingested_at,currency,unit)
                    SELECT %s,1,64,'INCOME_TAX',canonical_field_code,
                    'V24_PROVIDER_NORMALIZED_PARENT',numeric_value,NULL,NULL,NULL,
                    normalized_parent_id,raw_manifest_id,provider_code,
                    provider_schema_version,source_record_id,source_revision,
                    period_start,period_end,source_content_hash,normalized_record_hash,
                    effective_at,available_at,ingested_at,currency,unit
                    FROM analytics.fv_cq_forward_normalized_parent_v1
                    WHERE normalized_parent_id=%s""",
                    (candidate.enrollment_id, extra_normalized_id),
                )

    repository = CompanyQualityForwardRepositoryV1(t1_url)
    with psycopg.connect(database_url, autocommit=True) as lock_connection:
        lock_connection.execute("SELECT pg_advisory_lock(%s)", (seal_lock_key,))
        lock_connection.execute("SELECT pg_advisory_lock(%s)", (child_lock_key,))
        executor = ThreadPoolExecutor(max_workers=2)
        try:
            first = executor.submit(repository.enroll, candidate)
            _wait_for_database_wait(
                database_url, f"fv_cq_toctou_t1_{extra_kind}", first
            )
            second = executor.submit(insert_extra_child)
            _wait_for_database_wait(
                database_url, f"fv_cq_toctou_t2_{extra_kind}", second
            )
            lock_connection.execute(
                "SELECT pg_advisory_unlock(%s)", (seal_lock_key,)
            )
            assert first.result(timeout=120) == candidate.enrollment_id
            lock_connection.execute(
                "SELECT pg_advisory_unlock(%s)", (child_lock_key,)
            )
            with pytest.raises(
                psycopg.Error,
                match="FV_CQ_FORWARD_ENROLLMENT_INCOMPLETE_OR_INVALID",
            ):
                second.result(timeout=120)
        finally:
            lock_connection.execute(
                "SELECT pg_advisory_unlock(%s)", (seal_lock_key,)
            )
            lock_connection.execute(
                "SELECT pg_advisory_unlock(%s)", (child_lock_key,)
            )
            executor.shutdown(wait=True, cancel_futures=True)
    with psycopg.connect(database_url) as cleanup:
        cleanup.execute(
            f"DROP TRIGGER {child_trigger_name} ON analytics.{child_table}"
        )
        cleanup.execute(f"DROP FUNCTION {child_function_name}()")
        cleanup.execute(
            f"DROP TRIGGER {trigger_name} ON "
            "analytics.fv_cq_forward_enrollment_seal_v1"
        )
        cleanup.execute(f"DROP FUNCTION {function_name}()")
        assert cleanup.execute(
            "SELECT count(*) FROM analytics.fv_cq_forward_member_reason_v1 "
            "WHERE enrollment_id=%s",
            (candidate.enrollment_id,),
        ).fetchone()[0] == sum(len(row.reasons) for row in candidate.members)
        assert cleanup.execute(
            "SELECT count(*) FROM analytics.fv_cq_forward_member_evidence_v1 "
            "WHERE enrollment_id=%s",
            (candidate.enrollment_id,),
        ).fetchone()[0] == sum(len(row.evidence) for row in candidate.members)
    assert CompanyQualityForwardRepositoryV1(database_url).get(
        candidate.enrollment_id
    ) == candidate


def test_v24_semantic_writer_cannot_forge_deferred_validation_marker(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    forged_id = uuid4()
    forged_hash = _hash("forged-guc-enrollment")
    writer_url = database_url + "?options=-c%20role%3Danalytics_fv_cq_forward_writer_v1"
    stored = _clone(enrollment, "xid8-overwrite-source")
    CompanyQualityForwardRepositoryV1(database_url).enroll(stored)
    overwrite_id = uuid4()
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """INSERT INTO analytics.fv_cq_forward_enrollment_v1
            SELECT (jsonb_populate_record(
              NULL::analytics.fv_cq_forward_enrollment_v1,
                to_jsonb(source_row)||jsonb_build_object(
                'enrollment_id',%s::TEXT,'idempotency_key',%s::TEXT,
                'enrollment_content_hash',%s::TEXT))).*
            FROM analytics.fv_cq_forward_enrollment_v1 source_row
            WHERE source_row.enrollment_id=%s""",
            (
                overwrite_id,
                f"xid8-overwrite-{overwrite_id}",
                _hash("xid8-overwrite-enrollment"),
                stored.enrollment_id,
            ),
        )
        connection.execute(
            """INSERT INTO analytics.fv_cq_forward_enrollment_seal_v1
            (enrollment_id,decision_session_set_hash,entry_session_set_hash,
            member_set_hash,ranked_group_set_hash,reason_set_hash,evidence_set_hash,
            maturity_set_hash,seal_content_hash,sealed_at,creator_xid8)
            SELECT %s,decision_session_set_hash,entry_session_set_hash,member_set_hash,
            ranked_group_set_hash,reason_set_hash,evidence_set_hash,maturity_set_hash,
            %s,sealed_at,'1'::xid8
            FROM analytics.fv_cq_forward_enrollment_seal_v1 WHERE enrollment_id=%s""",
            (overwrite_id, _hash("xid8-overwrite-seal"), stored.enrollment_id),
        )
        assert connection.execute(
            "SELECT creator_xid8=pg_current_xact_id() "
            "FROM analytics.fv_cq_forward_enrollment_seal_v1 WHERE enrollment_id=%s",
            (overwrite_id,),
        ).fetchone()[0] is True
        connection.rollback()
    with psycopg.connect(writer_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.transaction():
                connection.execute(
                    "UPDATE analytics.fv_cq_forward_enrollment_seal_v1 "
                    "SET creator_xid8=pg_current_xact_id() WHERE enrollment_id=%s",
                    (stored.enrollment_id,),
                )
    with pytest.raises(
        psycopg.Error,
        match="FV_CQ_FORWARD_ENROLLMENT_INCOMPLETE_OR_INVALID",
    ):
        with psycopg.connect(writer_url) as connection:
            connection.execute(
                "SELECT set_config("
                "'analytics.fv_cq_forward_validated_enrollment_ids',%s,true)",
                (f"|{forged_id}|",),
            )
            connection.execute(
                """INSERT INTO analytics.fv_cq_forward_enrollment_v1
                SELECT (jsonb_populate_record(
                  NULL::analytics.fv_cq_forward_enrollment_v1,
                  to_jsonb(source_row)||jsonb_build_object(
                    'enrollment_id',%s::TEXT,
                    'idempotency_key',%s::TEXT,
                    'enrollment_content_hash',%s::TEXT))).*
                FROM analytics.fv_cq_forward_enrollment_v1 source_row
                WHERE source_row.enrollment_id=%s""",
                (forged_id, f"forged-guc-{forged_id}", forged_hash, stored.enrollment_id),
            )


def test_v24_semantic_writer_can_commit_complete_enrollment(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    candidate = _clone(enrollment, "semantic-writer-positive")
    writer_url = (
        database_url
        + "?options=-c%20role%3Danalytics_fv_cq_forward_writer_v1"
    )
    repository = CompanyQualityForwardRepositoryV1(writer_url)
    assert repository.enroll(candidate) == candidate.enrollment_id
    assert repository.get(candidate.enrollment_id) == candidate


def test_v24_normalized_parent_has_no_redundant_mic_claim(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    _, database_url = v24_postgres_enrollment
    with psycopg.connect(database_url) as connection:
        with pytest.raises(psycopg.DataError):
            with connection.transaction():
                connection.execute("SELECT %s::TEXT", ("A\x00B",))
        assert connection.execute("SELECT %s::INTEGER", (2_147_483_647,)).fetchone()[0] == (
            2_147_483_647
        )
        with pytest.raises(psycopg.errors.NumericValueOutOfRange):
            with connection.transaction():
                connection.execute("SELECT %s::INTEGER", (2_147_483_648,))
        assert connection.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema='analytics' "
            "AND table_name='fv_cq_forward_normalized_parent_v1' "
            "AND column_name='listing_mic'"
        ).fetchone()[0] == 0
        with pytest.raises(psycopg.errors.UndefinedColumn):
            with connection.transaction():
                connection.execute(
                    "SET LOCAL ROLE analytics_fv_cq_normalized_parent_writer_v1"
                )
                connection.execute(
                    "INSERT INTO analytics.fv_cq_forward_normalized_parent_v1 "
                    "(normalized_parent_id,listing_mic) VALUES (%s,'XNAS')",
                    (uuid4(),),
                )


def test_v24_database_rejects_infinite_hash_bound_dates_and_timestamps(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    _, database_url = v24_postgres_enrollment
    hash_value = _hash("infinity-negative")
    planned_fields = ("entry_date", "scheduled_open", "scheduled_close")
    decision_fields = (
        "session_date",
        "scheduled_open",
        "scheduled_close",
        "completed_at",
        "recorded_at",
    )
    with psycopg.connect(database_url) as connection:
        for sign in ("infinity", "-infinity"):
            with pytest.raises(psycopg.Error, match="TIMESTAMP_NOT_FINITE"):
                with connection.transaction():
                    connection.execute(
                        "SELECT analytics.fv_cq_forward_utc_text_v1(%s::TIMESTAMPTZ)",
                        (sign,),
                    )
            for field in planned_fields:
                values = {
                    "entry_date": "DATE '2026-07-31'",
                    "scheduled_open": "TIMESTAMPTZ '2026-07-31 13:30:00+00'",
                    "scheduled_close": "TIMESTAMPTZ '2026-07-31 20:00:00+00'",
                }
                cast = "DATE" if field == "entry_date" else "TIMESTAMPTZ"
                values[field] = f"{cast} '{sign}'"
                with pytest.raises(psycopg.Error):
                    with connection.transaction():
                        connection.execute("SET LOCAL session_replication_role=replica")
                        connection.execute(
                            "INSERT INTO analytics.fv_cq_forward_planned_entry_v1 "
                            "VALUES (%s,'XNAS','TEST','v1',%s,"
                            f"{values['entry_date']},{values['scheduled_open']},"
                            f"{values['scheduled_close']},false,%s,"
                            "'SCHEDULED_NOT_COMPLETED',%s)",
                            (uuid4(), hash_value, hash_value, hash_value),
                        )
            for field in decision_fields:
                values = {
                    "session_date": "DATE '2026-07-29'",
                    "scheduled_open": "TIMESTAMPTZ '2026-07-29 13:30:00+00'",
                    "scheduled_close": "TIMESTAMPTZ '2026-07-29 20:00:00+00'",
                    "completed_at": "TIMESTAMPTZ '2026-07-29 20:00:01+00'",
                    "recorded_at": "TIMESTAMPTZ '2026-07-29 20:00:01+00'",
                }
                cast = "DATE" if field == "session_date" else "TIMESTAMPTZ"
                values[field] = f"{cast} '{sign}'"
                with pytest.raises(psycopg.Error):
                    with connection.transaction():
                        connection.execute("SET LOCAL session_replication_role=replica")
                        connection.execute(
                            "INSERT INTO analytics.fv_cq_forward_decision_session_v1 "
                            "VALUES (%s,'XNAS',%s,'TEST','v1',"
                            f"{values['session_date']},{values['scheduled_open']},"
                            f"{values['scheduled_close']},false,{values['completed_at']},"
                            f"{values['recorded_at']},%s,%s,%s)",
                            (uuid4(), uuid4(), hash_value, hash_value, hash_value),
                        )


def test_v24_database_temporal_range_rejects_bc_and_year_10000(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    _, database_url = v24_postgres_enrollment
    invalid_dates = ("0001-01-01 BC", "10000-01-01")
    invalid_timestamps = (
        "0001-01-01 00:00:00 BC UTC",
        "10000-01-01 00:00:00+00",
    )
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT analytics.fv_cq_forward_date_text_v1(DATE '0001-01-01'),"
            "analytics.fv_cq_forward_date_text_v1(DATE '9999-12-31'),"
            "analytics.fv_cq_forward_utc_text_v1("
            "TIMESTAMPTZ '0001-01-01 00:00:00+00'),"
            "analytics.fv_cq_forward_utc_text_v1("
            "TIMESTAMPTZ '9999-12-31 23:59:59+00')"
        ).fetchone() == (
            "0001-01-01",
            "9999-12-31",
            "0001-01-01 00:00:00+00",
            "9999-12-31 23:59:59+00",
        )
        for value in invalid_dates:
            with pytest.raises(psycopg.Error, match="DATE_OUTSIDE_TYPED_RANGE"):
                with connection.transaction():
                    connection.execute(
                        "SELECT analytics.fv_cq_forward_date_text_v1(%s::DATE)",
                        (value,),
                    )
        for value in invalid_timestamps:
            with pytest.raises(psycopg.Error, match="TIMESTAMP_OUTSIDE_TYPED_RANGE"):
                with connection.transaction():
                    connection.execute(
                        "SELECT analytics.fv_cq_forward_utc_text_v1(%s::TIMESTAMPTZ)",
                        (value,),
                    )
        for invalid_date in invalid_dates:
            with pytest.raises(psycopg.Error, match="DATE_OUTSIDE_TYPED_RANGE"):
                with connection.transaction():
                    connection.execute("SET LOCAL session_replication_role=replica")
                    connection.execute(
                        "INSERT INTO analytics.fv_cq_forward_planned_entry_v1 VALUES "
                        f"(%s,'XNAS','TEST','v1',%s,DATE '{invalid_date}',"
                        "TIMESTAMPTZ '9999-12-31 20:00:00+00',"
                        "TIMESTAMPTZ '9999-12-31 21:00:00+00',false,%s,"
                        "'SCHEDULED_NOT_COMPLETED',%s)",
                        (uuid4(), HASH, HASH, HASH),
                    )


def test_v24_non_utc_session_replays_identical_hashes(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    non_utc_url = database_url + "?options=-c%20timezone%3DAmerica%2FNew_York"
    repository = CompanyQualityForwardRepositoryV1(non_utc_url)
    assert repository.get(enrollment.enrollment_id) == enrollment
    assert repository.enroll(enrollment) == enrollment.enrollment_id
    for zone in ("Pacific/Kiritimati", "America/Adak"):
        zone_url = database_url + f"?options=-c%20timezone%3D{zone.replace('/', '%2F')}"
        zone_repository = CompanyQualityForwardRepositoryV1(zone_url)
        assert zone_repository.get(enrollment.enrollment_id) == enrollment
        assert zone_repository.enroll(enrollment) == enrollment.enrollment_id
    utc_cutoff = enrollment.decision_cutoff
    offset_cutoff = utc_cutoff.astimezone(timezone(timedelta(hours=2)))
    for tag, cutoff, zone in (
        ("utc-date-east", utc_cutoff, "Pacific/Kiritimati"),
        ("utc-date-west", offset_cutoff, "America/Adak"),
    ):
        candidate = _clone(
            enrollment,
            tag,
            decision_cutoff=cutoff,
            evidence_cutoff=cutoff,
        )
        zone_url = database_url + f"?options=-c%20timezone%3D{zone.replace('/', '%2F')}"
        zone_repository = CompanyQualityForwardRepositoryV1(zone_url)
        assert zone_repository.enroll(candidate) == candidate.enrollment_id
        assert zone_repository.get(candidate.enrollment_id) == candidate
    with psycopg.connect(non_utc_url) as connection:
        assert connection.execute("SHOW TIME ZONE").fetchone()[0] == "America/New_York"
        with pytest.raises(psycopg.Error, match="TIMESTAMP_NOT_WHOLE_SECOND"):
            connection.execute(
                "SELECT analytics.fv_cq_forward_utc_text_v1(%s)",
                (datetime(2026, 7, 30, 20, 0, 0, 1, tzinfo=UTC),),
            )

    non_iso_url = database_url + "?options=-c%20DateStyle%3DSQL%2CDMY"
    non_iso_repository = CompanyQualityForwardRepositoryV1(non_iso_url)
    non_iso_candidate = _clone(enrollment, "non-iso-datestyle")
    assert non_iso_repository.enroll(non_iso_candidate) == non_iso_candidate.enrollment_id
    iso_repository = CompanyQualityForwardRepositoryV1(database_url)
    assert iso_repository.get(non_iso_candidate.enrollment_id) == non_iso_candidate
    assert iso_repository.enroll(non_iso_candidate) == non_iso_candidate.enrollment_id
    with psycopg.connect(non_iso_url) as connection:
        assert connection.execute("SHOW DateStyle").fetchone()[0] == "SQL, DMY"
        assert connection.execute(
            "SELECT analytics.fv_cq_forward_date_text_v1(%s::DATE)",
            ("2026-07-30",),
        ).fetchone()[0] == "2026-07-30"


def test_v24_sql_producer_domain_gates_match_python(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    cases = (
        (
            {
                "OPERATING_INCOME": Decimal("-100"),
                "STOCKHOLDERS_EQUITY": Decimal("1"),
                "TOTAL_DEBT": Decimal("0"),
                "CASH_AND_EQUIVALENTS": Decimal("0"),
            },
            "ROIC is outside",
        ),
        (
            {
                "OPERATING_INCOME": Decimal("100"),
                "STOCKHOLDERS_EQUITY": Decimal("1"),
                "TOTAL_DEBT": Decimal("0"),
                "CASH_AND_EQUIVALENTS": Decimal("0"),
            },
            "ROIC is outside",
        ),
        (
            {"REVENUE": Decimal("1"), "OPERATING_INCOME": Decimal("-2")},
            "operating margin is outside",
        ),
        (
            {"REVENUE": Decimal("1"), "OPERATING_INCOME": Decimal("2")},
            "operating margin is outside",
        ),
        ({"OPERATING_CASH_FLOW": Decimal("-300")}, "FCF margin is outside"),
        ({"OPERATING_CASH_FLOW": Decimal("300")}, "FCF margin is outside"),
    )
    first_evidence = enrollment.members[0].evidence
    with psycopg.connect(database_url) as connection:
        for replacements, reason in cases:
            changed = tuple(
                replace(item, numeric_value=replacements.get(item.operand_code, item.numeric_value))
                for item in first_evidence
            )
            with pytest.raises(ValueError, match=reason):
                company_quality_score_from_parents(changed)
            originals = {
                operand: connection.execute(
                    "SELECT numeric_value FROM analytics.fv_cq_forward_member_evidence_v1 "
                    "WHERE enrollment_id=%s AND member_ordinal=1 AND operand_code=%s "
                    "ORDER BY evidence_ordinal LIMIT 1",
                    (enrollment.enrollment_id, operand),
                ).fetchone()[0]
                for operand in replacements
            }
            with connection.transaction():
                connection.execute("SET LOCAL session_replication_role=replica")
                for operand, invalid_value in replacements.items():
                    connection.execute(
                        "UPDATE analytics.fv_cq_forward_member_evidence_v1 SET numeric_value=%s "
                        "WHERE enrollment_id=%s AND member_ordinal=1 AND operand_code=%s",
                        (invalid_value, enrollment.enrollment_id, operand),
                    )
                assert connection.execute(
                    "SELECT analytics.fv_cq_forward_expected_score_v1(%s,1)",
                    (enrollment.enrollment_id,),
                ).fetchone()[0] is None
                for operand, original in originals.items():
                    connection.execute(
                        "UPDATE analytics.fv_cq_forward_member_evidence_v1 SET numeric_value=%s "
                        "WHERE enrollment_id=%s AND member_ordinal=1 AND operand_code=%s",
                        (original, enrollment.enrollment_id, operand),
                    )


def test_v24_parent_magnitude_envelope_prevents_sql_sum_overflow(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    periods = (date(2026, 6, 30), date(2026, 3, 31))
    changed = tuple(
        replace(item, numeric_value=MAX_ABS_PARENT_VALUE)
        if item.operand_code == "REVENUE" and item.parent_period_end in periods
        else item
        for item in enrollment.members[0].evidence
    )
    assert company_quality_score_from_parents(changed).is_finite()

    with psycopg.connect(database_url) as connection:
        originals = connection.execute(
            "SELECT parent_period_end,numeric_value "
            "FROM analytics.fv_cq_forward_member_evidence_v1 "
            "WHERE enrollment_id=%s AND member_ordinal=1 "
            "AND operand_code='REVENUE' AND parent_period_end=ANY(%s)",
            (enrollment.enrollment_id, list(periods)),
        ).fetchall()
        with connection.transaction():
            connection.execute("SET LOCAL session_replication_role=replica")
            connection.execute(
                "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                "SET numeric_value=%s WHERE enrollment_id=%s AND member_ordinal=1 "
                "AND operand_code='REVENUE' AND parent_period_end=ANY(%s)",
                (MAX_ABS_PARENT_VALUE, enrollment.enrollment_id, list(periods)),
            )
            assert connection.execute(
                "SELECT analytics.fv_cq_forward_expected_score_v1(%s,1)",
                (enrollment.enrollment_id,),
            ).fetchone()[0] is not None
            for period_end, numeric_value in originals:
                connection.execute(
                    "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                    "SET numeric_value=%s WHERE enrollment_id=%s AND member_ordinal=1 "
                    "AND operand_code='REVENUE' AND parent_period_end=%s",
                    (numeric_value, enrollment.enrollment_id, period_end),
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute("SET LOCAL session_replication_role=replica")
                connection.execute(
                    "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                    "SET numeric_value=1e101 WHERE enrollment_id=%s "
                    "AND member_ordinal=1 AND evidence_ordinal=1",
                    (enrollment.enrollment_id,),
                )


def test_v24_parent_fractional_scale_envelope_prevents_context_quantum_overflow(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    assert MAX_PARENT_FRACTIONAL_DIGITS == 100
    with psycopg.connect(database_url) as connection:
        originals = connection.execute(
            "SELECT evidence_ordinal,numeric_value "
            "FROM analytics.fv_cq_forward_member_evidence_v1 "
            "WHERE enrollment_id=%s AND member_ordinal=1 "
            "AND operand_code='NET_INCOME' ORDER BY evidence_ordinal",
            (enrollment.enrollment_id,),
        ).fetchall()
        for accepted in (Decimal(0), Decimal("1e-100"), Decimal("-1e-100")):
            with connection.transaction():
                connection.execute("SET LOCAL session_replication_role=replica")
                connection.execute(
                    "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                    "SET numeric_value=%s WHERE enrollment_id=%s AND member_ordinal=1 "
                    "AND operand_code='NET_INCOME'",
                    (accepted, enrollment.enrollment_id),
                )
                connection.execute(
                    "SELECT analytics.fv_cq_forward_expected_score_v1(%s,1)",
                    (enrollment.enrollment_id,),
                ).fetchone()
                for ordinal, numeric_value in originals:
                    connection.execute(
                        "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                        "SET numeric_value=%s WHERE enrollment_id=%s "
                        "AND member_ordinal=1 AND evidence_ordinal=%s",
                        (numeric_value, enrollment.enrollment_id, ordinal),
                    )
        for rejected in (Decimal("1e-101"), Decimal("1e-16383")):
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute("SET LOCAL session_replication_role=replica")
                    connection.execute(
                        "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                        "SET numeric_value=%s WHERE enrollment_id=%s "
                        "AND member_ordinal=1 AND operand_code='NET_INCOME'",
                        (rejected, enrollment.enrollment_id),
                    )


def test_v24_sql_replay_rejects_period_boundary_and_per_row_capex_drift(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    cases = (
        ("REVENUE", date(2026, 6, 30), date(2026, 6, 29), None),
        ("STOCKHOLDERS_EQUITY", date(2026, 6, 30), date(2026, 7, 1), None),
        ("CAPITAL_EXPENDITURE", date(2026, 6, 30), None, Decimal("-1")),
        ("CAPITAL_EXPENDITURE", date(2025, 3, 31), None, Decimal("-1")),
    )
    with psycopg.connect(database_url) as connection:
        for role, old_period, new_period, new_value in cases:
            if role == "CAPITAL_EXPENDITURE":
                with pytest.raises(psycopg.errors.CheckViolation):
                    with connection.transaction():
                        connection.execute("SET LOCAL session_replication_role=replica")
                        connection.execute(
                            "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                            "SET numeric_value=%s WHERE enrollment_id=%s "
                            "AND member_ordinal=1 AND operand_code=%s "
                            "AND parent_period_end=%s",
                            (new_value, enrollment.enrollment_id, role, old_period),
                        )
                continue
            with connection.transaction():
                connection.execute("SET LOCAL session_replication_role=replica")
                if new_period is not None:
                    connection.execute(
                        "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                        "SET parent_period_end=%s WHERE enrollment_id=%s "
                        "AND member_ordinal=1 AND operand_code=%s "
                        "AND parent_period_end=%s",
                        (new_period, enrollment.enrollment_id, role, old_period),
                    )
                else:
                    connection.execute(
                        "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                        "SET numeric_value=%s WHERE enrollment_id=%s "
                        "AND member_ordinal=1 AND operand_code=%s "
                        "AND parent_period_end=%s",
                        (new_value, enrollment.enrollment_id, role, old_period),
                    )
                assert connection.execute(
                    "SELECT analytics.fv_cq_forward_expected_score_v1(%s,1)",
                    (enrollment.enrollment_id,),
                ).fetchone()[0] is None
                if new_period is not None:
                    connection.execute(
                        "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                        "SET parent_period_end=%s WHERE enrollment_id=%s "
                        "AND member_ordinal=1 AND operand_code=%s "
                        "AND parent_period_end=%s",
                        (old_period, enrollment.enrollment_id, role, new_period),
                    )
                else:
                    original = next(
                        item.numeric_value
                        for item in enrollment.members[0].evidence
                        if item.operand_code == role
                        and item.parent_period_end == old_period
                    )
                    connection.execute(
                        "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                        "SET numeric_value=%s WHERE enrollment_id=%s "
                        "AND member_ordinal=1 AND operand_code=%s "
                        "AND parent_period_end=%s",
                        (original, enrollment.enrollment_id, role, old_period),
                    )
        with connection.transaction():
            connection.execute("SET LOCAL session_replication_role=replica")
            connection.execute(
                "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                "SET parent_period_end=parent_period_end-121 "
                "WHERE enrollment_id=%s AND member_ordinal=1 "
                "AND operand_code='TOTAL_DEBT' AND parent_period_end<='2025-06-30'",
                (enrollment.enrollment_id,),
            )
            assert connection.execute(
                "SELECT analytics.fv_cq_forward_expected_score_v1(%s,1)",
                (enrollment.enrollment_id,),
            ).fetchone()[0] is None
            connection.execute(
                "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                "SET parent_period_end=parent_period_end+121 "
                "WHERE enrollment_id=%s AND member_ordinal=1 "
                "AND operand_code='TOTAL_DEBT' AND parent_period_end<='2025-03-01'",
                (enrollment.enrollment_id,),
            )


def test_v24_sql_hash_atoms_and_period_dates_fail_closed(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT analytics.fv_cq_forward_hash_atom_v1(chr(160))"
        ).fetchone()[0] is True
        for invalid in ("AUTH:V1", "V1|REV", "\t", "\n", " \t\n\r\f\v"):
            with pytest.raises(psycopg.Error):
                with connection.transaction():
                    connection.execute("SET LOCAL session_replication_role=replica")
                    connection.execute(
                        "UPDATE analytics.fv_cq_forward_planned_entry_v1 "
                        "SET schedule_source_id=%s WHERE enrollment_id=%s AND mic='XNAS'",
                        (invalid, enrollment.enrollment_id),
                    )
        for start, end in (
            ("infinity", "2026-06-30"),
            ("2026-07-01", "2026-06-30"),
            ("2026-06-01", "infinity"),
        ):
            with pytest.raises(psycopg.Error):
                with connection.transaction():
                    connection.execute("SET LOCAL session_replication_role=replica")
                    connection.execute(
                        "UPDATE analytics.fv_cq_forward_member_evidence_v1 "
                        "SET parent_period_start=%s::DATE,parent_period_end=%s::DATE "
                        "WHERE enrollment_id=%s AND member_ordinal=1 AND evidence_ordinal=1",
                        (start, end, enrollment.enrollment_id),
                    )


def test_v24_database_rejects_recording_before_session_completion(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    _, database_url = v24_postgres_enrollment
    with psycopg.connect(database_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute("SET LOCAL session_replication_role=replica")
                connection.execute(
                    "INSERT INTO analytics.fv_cq_forward_decision_session_v1 VALUES "
                    "(%s,'XNAS',%s,'TEST','v1',DATE '2026-07-29',"
                    "TIMESTAMPTZ '2026-07-29 13:30:00+00',"
                    "TIMESTAMPTZ '2026-07-29 20:00:00+00',false,"
                    "TIMESTAMPTZ '2026-07-29 20:00:02+00',"
                    "TIMESTAMPTZ '2026-07-29 20:00:01+00',%s,%s,%s)",
                    (uuid4(), uuid4(), HASH, HASH, HASH),
                )


def test_v24_database_uniqueness_and_numeric_wire_parity(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    with psycopg.connect(database_url) as connection:
        uniqueness_updates = (
            "UPDATE analytics.fv_cq_forward_member_v1 target "
            "SET ticker_assignment_id=source.ticker_assignment_id "
            "FROM analytics.fv_cq_forward_member_v1 source "
            "WHERE target.enrollment_id=source.enrollment_id "
            "AND target.enrollment_id=%s AND target.member_ordinal=2 "
            "AND source.member_ordinal=1",
            "UPDATE analytics.fv_cq_forward_decision_session_v1 target "
            "SET calendar_id=source.calendar_id,calendar_version=source.calendar_version "
            "FROM analytics.fv_cq_forward_decision_session_v1 source "
            "WHERE target.enrollment_id=source.enrollment_id "
            "AND target.enrollment_id=%s AND target.mic='XNYS' AND source.mic='XNAS'",
            "UPDATE analytics.fv_cq_forward_member_evidence_v1 target "
            "SET selection_request_id=source.selection_request_id "
            "FROM analytics.fv_cq_forward_member_evidence_v1 source "
            "WHERE target.enrollment_id=source.enrollment_id "
            "AND target.enrollment_id=%s AND target.member_ordinal=1 "
            "AND target.evidence_ordinal=2 AND source.member_ordinal=1 "
            "AND source.evidence_ordinal=1",
            "UPDATE analytics.fv_cq_forward_member_evidence_v1 target "
            "SET normalized_parent_id=source.normalized_parent_id "
            "FROM analytics.fv_cq_forward_member_evidence_v1 source "
            "WHERE target.enrollment_id=source.enrollment_id "
            "AND target.enrollment_id=%s AND target.member_ordinal=1 "
            "AND target.operand_code='PRETAX_INCOME' "
            "AND source.member_ordinal=1 AND source.operand_code='INCOME_TAX' "
            "AND target.parent_period_end=source.parent_period_end",
        )
        for statement in uniqueness_updates:
            with pytest.raises(psycopg.errors.UniqueViolation):
                with connection.transaction():
                    connection.execute("SET LOCAL session_replication_role=replica")
                    connection.execute(statement, (enrollment.enrollment_id,))

        integer_digits = Decimal("1e131071")
        fractional_digits = Decimal("1e-16383")
        assert connection.execute("SELECT %s::NUMERIC", (integer_digits,)).fetchone()[0] == (
            integer_digits
        )
        assert connection.execute("SELECT %s::NUMERIC", (fractional_digits,)).fetchone()[0] == (
            fractional_digits
        )
        for invalid in (Decimal("1e131072"), Decimal("1e-16384")):
            with pytest.raises(psycopg.Error):
                with connection.transaction():
                    connection.execute("SELECT %s::NUMERIC", (invalid,))
def test_v24_python_and_database_reject_semantic_tamper(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, _ = v24_postgres_enrollment
    first = enrollment.members[0]
    with pytest.raises(ValueError, match="canonical field mapping"):
        CompanyQualityForwardRepositoryV1("postgresql://unused").enroll(
            seal_enrollment(
                replace(
                    enrollment,
                    members=(
                        seal_member(
                            replace(
                                first,
                                evidence=(
                                    replace(first.evidence[0], canonical_field_code="NET_INCOME"),
                                    *first.evidence[1:],
                                ),
                            )
                        ),
                        *enrollment.members[1:],
                    ),
                )
            )
        )


def test_v24_database_rejects_provider_normalized_parent_drift(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    first = enrollment.members[0]
    provider_index = next(
        index
        for index, item in enumerate(first.evidence)
        if item.provenance_kind == "V24_PROVIDER_NORMALIZED_PARENT"
    )
    drifted_evidence = list(first.evidence)
    drifted_evidence[provider_index] = replace(
        drifted_evidence[provider_index],
        parent_normalized_record_hash=_hash("forged-normalized-parent"),
    )
    evidence = tuple(drifted_evidence)
    evidence_hash, source_hash = evidence_aggregate_hashes(evidence)
    drifted_member = seal_member(
        replace(
            first,
            evidence=evidence,
            evidence_content_hash=evidence_hash,
            source_content_hash=source_hash,
            producer_output_content_hash=producer_output_hash(
                first.predictor_score, evidence_hash, source_hash
            ),
        )
    )
    candidate = _clone(
        enrollment,
        "normalized-parent-drift",
        members=(drifted_member, *enrollment.members[1:]),
    )
    with pytest.raises(psycopg.Error, match="FV_CQ_FORWARD_ENROLLMENT_INCOMPLETE"):
        CompanyQualityForwardRepositoryV1(database_url).enroll(candidate)


def _clone(enrollment: Enrollment, tag: str, **changes: object) -> Enrollment:
    return seal_enrollment(
        replace(
            enrollment,
            enrollment_id=_uuid(13, tag),
            idempotency_key=f"fv-v24-negative-{tag}",
            content_hash="",
            **changes,
        )
    )


def test_v24_database_rejects_missing_selection_and_canonical_drift(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    binding = next(
        item
        for item in enrollment.members[0].evidence
        if item.provenance_kind == "V22_SELECTED_EVIDENCE"
    )
    assert binding.selection_request_id is not None
    assert binding.canonical_evidence_id is not None
    repository = CompanyQualityForwardRepositoryV1(database_url)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        result = connection.execute(
            "SELECT * FROM analytics.evidence_selection_result_v1 WHERE request_id=%s",
            (binding.selection_request_id,),
        ).fetchone()
        seal = connection.execute(
            "SELECT * FROM analytics.evidence_selection_seal_v1 WHERE request_id=%s",
            (binding.selection_request_id,),
        ).fetchone()
        assert result is not None and seal is not None
        with connection.transaction():
            connection.execute("SET LOCAL session_replication_role=replica")
            connection.execute(
                "DELETE FROM analytics.evidence_selection_seal_v1 WHERE request_id=%s",
                (binding.selection_request_id,),
            )
            connection.execute(
                "DELETE FROM analytics.evidence_selection_result_v1 WHERE request_id=%s",
                (binding.selection_request_id,),
            )
    try:
        with pytest.raises(psycopg.Error, match="FV_CQ_FORWARD_ENROLLMENT_INCOMPLETE"):
            repository.enroll(_clone(enrollment, "missing-selection"))
    finally:
        with psycopg.connect(database_url) as connection:
            with connection.transaction():
                connection.execute("SET LOCAL session_replication_role=replica")
                connection.execute(
                    """INSERT INTO analytics.evidence_selection_result_v1
                    (request_id,selector_version,state,reason_code,selected_evidence_id,
                    result_content_hash,recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    tuple(result.values()),
                )
                connection.execute(
                    """INSERT INTO analytics.evidence_selection_seal_v1
                    (request_id,candidate_count,rejection_count,sealed_at)
                    VALUES (%s,%s,%s,%s)""",
                    tuple(seal.values()),
                )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        policy = connection.execute(
            """SELECT policy.* FROM analytics.evidence_selector_policy_v1 policy
            JOIN analytics.evidence_selection_request_v1 request ON request.policy_id=policy.id
            WHERE request.request_id=%s""",
            (binding.selection_request_id,),
        ).fetchone()
        assert policy is not None
        altered_constraints = dict(policy["domain_constraints"])
        altered_constraints["metricCode"] = "NET_INCOME"
        with connection.transaction():
            connection.execute("SET LOCAL session_replication_role=replica")
            connection.execute(
                """UPDATE analytics.evidence_selector_policy_v1
                SET field_code='NET_INCOME',domain_constraints=%s WHERE id=%s""",
                (Jsonb(altered_constraints), policy["id"]),
            )
    try:
        with pytest.raises(psycopg.Error, match="FV_CQ_FORWARD_ENROLLMENT_INCOMPLETE"):
            repository.enroll(_clone(enrollment, "policy-domain-drift"))
    finally:
        with psycopg.connect(database_url) as connection:
            with connection.transaction():
                connection.execute("SET LOCAL session_replication_role=replica")
                connection.execute(
                    """UPDATE analytics.evidence_selector_policy_v1
                    SET field_code=%s,domain_constraints=%s WHERE id=%s""",
                    (policy["field_code"], Jsonb(policy["domain_constraints"]), policy["id"]),
                )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        original = connection.execute(
            "SELECT canonical_data FROM analytics.canonical_evidence_v1 WHERE evidence_id=%s",
            (binding.canonical_evidence_id,),
        ).fetchone()
        assert original is not None
        with connection.transaction():
            connection.execute("SET LOCAL session_replication_role=replica")
            connection.execute(
                """UPDATE analytics.canonical_evidence_v1
                SET canonical_data=jsonb_set(
                  jsonb_set(canonical_data,'{metricCode}','\"NET_INCOME\"'),
                  '{periodEnd}','\"2026-06-29\"')
                WHERE evidence_id=%s""",
                (binding.canonical_evidence_id,),
            )
    try:
        with pytest.raises(psycopg.Error, match="FV_CQ_FORWARD_ENROLLMENT_INCOMPLETE"):
            repository.enroll(_clone(enrollment, "canonical-field-drift"))
    finally:
        with psycopg.connect(database_url) as connection:
            with connection.transaction():
                connection.execute("SET LOCAL session_replication_role=replica")
                connection.execute(
                    "UPDATE analytics.canonical_evidence_v1 SET canonical_data=%s "
                    "WHERE evidence_id=%s",
                    (Jsonb(original["canonical_data"]), binding.canonical_evidence_id),
                )


def test_v24_database_rejects_identity_session_cutoff_and_parent_chronology(
    v24_postgres_enrollment: tuple[Enrollment, str],
) -> None:
    enrollment, database_url = v24_postgres_enrollment
    repository = CompanyQualityForwardRepositoryV1(database_url)
    first = enrollment.members[0]
    wrong_identity = seal_member(replace(first, listing_id=uuid4()))
    with pytest.raises(psycopg.Error):
        repository.enroll(
            _clone(
                enrollment,
                "wrong-identity",
                members=(wrong_identity, *enrollment.members[1:]),
            )
        )
    wrong_ticker = seal_member(replace(first, ticker_assignment_id=uuid4()))
    with pytest.raises(psycopg.Error):
        repository.enroll(
            _clone(
                enrollment,
                "wrong-ticker",
                members=(wrong_ticker, *enrollment.members[1:]),
            )
        )
    with pytest.raises(psycopg.Error):
        repository.enroll(
            _clone(
                enrollment,
                "wrong-session",
                decision_sessions=(
                    replace(enrollment.decision_sessions[0], completed_session_id=uuid4()),
                    enrollment.decision_sessions[1],
                ),
            )
        )
    with pytest.raises(ValueError, match="decision-session identity/calendar/chronology"):
        repository.enroll(
            _clone(
                enrollment,
                "wrong-cutoff",
                decision_cutoff=datetime(2026, 7, 29, 19, tzinfo=UTC),
                evidence_cutoff=datetime(2026, 7, 29, 18, tzinfo=UTC),
            )
        )
    bad_parent = replace(
        first.evidence[0],
        parent_available_at=first.evidence[0].parent_ingested_at + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="chronology"):
        repository.enroll(
            _clone(
                enrollment,
                "bad-parent-chronology",
                members=(
                    seal_member(
                        replace(first, evidence=(bad_parent, *first.evidence[1:]))
                    ),
                    *enrollment.members[1:],
                ),
            )
        )
    with pytest.raises(ValueError, match="accepted producer output"):
        CompanyQualityForwardRepositoryV1("postgresql://unused").enroll(
            seal_enrollment(
                replace(
                    enrollment,
                    members=(
                        seal_member(replace(first, predictor_score=first.predictor_score + 1)),
                        *enrollment.members[1:],
                    ),
                )
            )
        )
    selected = next(
        item
        for item in first.evidence
        if item.provenance_kind == "V22_SELECTED_EVIDENCE"
    )
    assert selected.selection_request_id is not None
    xnas_session = next(
        row.completed_session_id
        for row in enrollment.decision_sessions
        if row.mic == "XNAS"
    )
    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            connection.execute("SET LOCAL session_replication_role=replica")
            connection.execute(
                "UPDATE analytics.evidence_selection_request_v1 "
                "SET completed_session_id=%s WHERE request_id=%s",
                (xnas_session, selected.selection_request_id),
            )
    try:
        with pytest.raises(psycopg.Error, match="FV_CQ_FORWARD_ENROLLMENT_INCOMPLETE"):
            repository.enroll(_clone(enrollment, "cross-mic-request"))
    finally:
        with psycopg.connect(database_url) as connection:
            with connection.transaction():
                connection.execute("SET LOCAL session_replication_role=replica")
                connection.execute(
                    "UPDATE analytics.evidence_selection_request_v1 "
                    "SET completed_session_id=%s WHERE request_id=%s",
                    (
                        next(
                            row.completed_session_id
                            for row in enrollment.decision_sessions
                            if row.mic == first.listing_mic
                        ),
                        selected.selection_request_id,
                    ),
                )
