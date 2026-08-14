from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, getcontext, localcontext
from pathlib import Path
from uuid import UUID

import pytest

from equity_analysis.fundamental_value.prospective_company_quality_v1 import (
    MAX_ABS_PARENT_VALUE,
    MAX_PARENT_FRACTIONAL_DIGITS,
    UUID_FIELD_NAMES,
    VARCHAR_LIMITS,
    CompanyQualityForwardRepositoryV1,
    DecisionSession,
    Enrollment,
    EvidenceBinding,
    Member,
    PlannedEntry,
    TerminalState,
    _best_first_members,
    _bounded_hash_atom,
    _iso_date,
    _pg_timestamp,
    _uuid_value,
    canonical_decimal_text,
    company_quality_score_from_parents,
    evaluate_offline_readiness,
    evidence_aggregate_hashes,
    producer_output_hash,
    seal_enrollment,
    seal_member,
    validate_enrollment,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "database/migrations/V24__create_fundamental_value_company_quality_forward_enrollment_v1.sql"
)
HASH = "sha256:" + "a" * 64


def _member(ordinal: int = 1) -> Member:
    suffix = f"{ordinal:012d}"
    periods = (
        date(2026, 6, 30),
        date(2026, 3, 31),
        date(2025, 12, 31),
        date(2025, 9, 30),
        date(2025, 6, 30),
        date(2025, 3, 31),
        date(2024, 12, 31),
        date(2024, 9, 30),
    )
    counts = (
        ("REVENUE", 8),
        ("OPERATING_INCOME", 8),
        ("NET_INCOME", 8),
        ("OPERATING_CASH_FLOW", 8),
        ("CAPITAL_EXPENDITURE", 8),
        ("INCOME_TAX", 4),
        ("PRETAX_INCOME", 4),
        ("STOCKHOLDERS_EQUITY", 5),
        ("TOTAL_DEBT", 5),
        ("CASH_AND_EQUIVALENTS", 5),
    )
    evidence_items: list[EvidenceBinding] = []
    for role, count in counts:
        for period in periods[:count]:
            index = len(evidence_items) + 1
            provider_only = role in {"INCOME_TAX", "PRETAX_INCOME"}
            value = {
                "REVENUE": Decimal("100"),
                "OPERATING_INCOME": Decimal("12") - Decimal(ordinal) / 100,
                "NET_INCOME": Decimal("6"),
                "OPERATING_CASH_FLOW": Decimal("8"),
                "CAPITAL_EXPENDITURE": Decimal("2"),
                "INCOME_TAX": Decimal("2"),
                "PRETAX_INCOME": Decimal("10"),
                "STOCKHOLDERS_EQUITY": Decimal("100"),
                "TOTAL_DEBT": Decimal("20"),
                "CASH_AND_EQUIVALENTS": Decimal("10"),
            }[role]
            evidence_items.append(
                EvidenceBinding(
                    evidence_ordinal=index,
                    operand_code=role,
                    canonical_field_code=(
                        "TOTAL_EQUITY" if role == "STOCKHOLDERS_EQUITY" else role
                    ),
                    provenance_kind=(
                        "V24_PROVIDER_NORMALIZED_PARENT"
                        if provider_only
                        else "V22_SELECTED_EVIDENCE"
                    ),
                    numeric_value=value,
                    selection_request_id=(
                        None if provider_only else UUID(int=ordinal * 100 + index)
                    ),
                    selection_result_hash=(
                        None
                        if provider_only
                        else "sha256:" + f"{ordinal * 100 + index:064x}"
                    ),
                    canonical_evidence_id=(
                        None
                        if provider_only
                        else UUID(int=100_000 + ordinal * 100 + index)
                    ),
                    normalized_parent_id=(
                        UUID(int=300_000 + ordinal * 100 + index)
                        if provider_only
                        else None
                    ),
                    raw_manifest_id=UUID(int=200_000 + ordinal * 100 + index),
                    provider_code="TEST_ONLY_V24",
                    provider_schema_version="test-schema-v1",
                    source_record_id=f"member-{ordinal}-parent-{index}",
                    source_revision=1,
                    parent_period_start=(
                        None
                        if role
                        in {"STOCKHOLDERS_EQUITY", "TOTAL_DEBT", "CASH_AND_EQUIVALENTS"}
                        else period - timedelta(days=89)
                    ),
                    parent_period_end=period,
                    parent_source_content_hash=HASH,
                    parent_normalized_record_hash=(
                        "sha256:" + f"{300_000 + ordinal * 100 + index:064x}"
                    ),
                    parent_effective_at=datetime(2026, 7, 1, 12, tzinfo=UTC),
                    parent_available_at=datetime(2026, 7, 2, 12, tzinfo=UTC),
                    parent_ingested_at=datetime(2026, 7, 2, 13, tzinfo=UTC),
                    currency="USD",
                    unit="USD",
                )
            )
    evidence = tuple(evidence_items)
    evidence_hash, source_hash = evidence_aggregate_hashes(evidence)
    score = company_quality_score_from_parents(evidence)
    return seal_member(
        Member(
            member_ordinal=ordinal,
            security_id=UUID("00000000-0000-0000-0000-" + suffix),
            company_id=UUID("10000000-0000-0000-0000-" + suffix),
            instrument_id=UUID("20000000-0000-0000-0000-" + suffix),
            share_class_id=UUID("30000000-0000-0000-0000-" + suffix),
            listing_id=UUID("40000000-0000-0000-0000-" + suffix),
            ticker_assignment_id=UUID("50000000-0000-0000-0000-" + suffix),
            listing_mic="XNYS" if ordinal <= 122 else "XNAS",
            terminal_state=TerminalState.USABLE_VALID,
            reasons=(),
            predictor_score=score,
            predictor_rank=ordinal,
            predictor_group=("HIGH" if ordinal <= 38 else "LOW" if ordinal > 153 else "MIDDLE"),
            evidence_available_at=datetime(2026, 7, 2, 12, tzinfo=UTC),
            evidence_ingested_at=datetime(2026, 7, 2, 13, tzinfo=UTC),
            evidence_content_hash=evidence_hash,
            source_content_hash=source_hash,
            producer_contract_content_hash="sha256:a9a8787104d9cb9bb764a21df3de6b22807f893ff86da5c69609b6bbbd89a995",
            producer_output_content_hash=producer_output_hash(score, evidence_hash, source_hash),
            row_content_hash=HASH,
            evidence=evidence,
        )
    )


def _enrollment() -> Enrollment:
    return seal_enrollment(
        Enrollment(
            enrollment_id=UUID("60000000-0000-0000-0000-000000000001"),
            decision_sessions=tuple(
                DecisionSession(
                    mic=mic,
                    completed_session_id=UUID(int=700_000 + index),
                    calendar_id=f"{mic}-COMPLETED-SESSIONS",
                    calendar_version="unified-trading-calendar-v1.0.0",
                    session_date=date(2026, 7, 30),
                    scheduled_open=datetime(2026, 7, 30, 13, 30, tzinfo=UTC),
                    scheduled_close=datetime(2026, 7, 30, 20, tzinfo=UTC),
                    early_close=False,
                    completed_at=datetime(2026, 7, 30, 20, 1, tzinfo=UTC),
                    recorded_at=datetime(2026, 7, 30, 20, 2, tzinfo=UTC),
                    session_content_hash="sha256:" + f"{index:064x}",
                    calendar_content_hash=HASH,
                )
                for index, mic in enumerate(("XNAS", "XNYS"), 1)
            ),
            planned_entries=tuple(
                PlannedEntry(
                    mic=mic,
                    schedule_source_id=f"{mic}-SCHEDULE",
                    schedule_source_version="test-schedule-v1",
                    schedule_source_content_hash=HASH,
                    entry_date=date(2026, 7, 31),
                    scheduled_open=datetime(2026, 7, 31, 13, 30, tzinfo=UTC),
                    scheduled_close=datetime(2026, 7, 31, 20, tzinfo=UTC),
                    early_close=False,
                    schedule_content_hash=HASH,
                )
                for mic in ("XNAS", "XNYS")
            ),
            decision_cutoff=datetime(2026, 7, 30, 21, tzinfo=UTC),
            evidence_cutoff=datetime(2026, 7, 30, 21, tzinfo=UTC),
            sealed_at=datetime(2026, 7, 30, 22, tzinfo=UTC),
            population_content_hash="sha256:b29306ce3b1a047c074b68fda07149fff72f7b2ecd2bc0d78aad7b42692656c7",
            evidence_manifest_content_hash=HASH,
            predictor_contract_content_hash="sha256:a9a8787104d9cb9bb764a21df3de6b22807f893ff86da5c69609b6bbbd89a995",
            producer_version="FV-STAGE7C5-EODHD-PROVIDER-NATIVE-COMPANY-QUALITY-v1.0.0",
            arithmetic_version="FV-STAGE7C9-DECIMAL-ARITHMETIC-v1.0.0",
            cost_policy_version="LIQUIDITY-SENSITIVE-COST-v1.0.0",
            outcome_policy_version="FV-STAGE8A-READINESS-PREREGISTRATION-v1.0.0",
            outcome_protocol_content_hash=HASH,
            stage7_acceptance_content_hash="sha256:97048a8497f44740edd3c072aabd3de86a26d82181462fb620174b8e217bff6b",
            idempotency_key="fv-stage8b-fixture",
            members=tuple(_member(index) for index in range(1, 192)),
            content_hash="",
        )
    )


def test_v24_is_narrow_append_only_and_has_empty_maturity_schedule() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "COMPANY_QUALITY_ONLY" in sql
    assert "NOT_VALIDATED" in sql
    assert "CURRENT_REVISION_APPROXIMATION" in sql
    assert "AWAITING_NATURAL_MATURITY" in sql
    assert "horizon_sessions IN (252,504,756)" in sql
    assert "BEFORE UPDATE OR DELETE OR TRUNCATE" in sql
    assert "outcome_row_count = 0" in sql
    assert "fv_cq_forward_enrollment_seal_v1" in sql
    assert "FV_CQ_FORWARD_ALREADY_SEALED" in sql
    assert "expected_member_count = 191" in sql
    assert "expected_usable_count >= 100" in sql
    assert "floor(usable_count / 5.0)" in sql
    assert "analytics_fv_cq_forward_writer_v1" in sql
    assert "fv_cq_forward_member_evidence_v1" in sql
    assert "bound.scheduled_close<=parent.decision_cutoff" in sql
    assert "portfolio" not in sql.lower()
    assert "broker" not in sql.lower()


def test_contract_validates_best_first_rank_and_hash() -> None:
    enrollment = _enrollment()
    validate_enrollment(enrollment)
    inverted = replace(
        enrollment,
        members=(
            seal_member(replace(enrollment.members[0], predictor_rank=2)),
            seal_member(replace(enrollment.members[1], predictor_rank=1)),
            *enrollment.members[2:],
        ),
    )
    with pytest.raises(ValueError, match="rank 1"):
        validate_enrollment(seal_enrollment(inverted))
    with pytest.raises(ValueError, match="versions"):
        validate_enrollment(replace(enrollment, producer_version="tampered"))
    wrong_group = seal_member(replace(enrollment.members[38], predictor_group="HIGH"))
    with pytest.raises(ValueError, match="20/60/20"):
        validate_enrollment(
            seal_enrollment(
                replace(
                    enrollment,
                    members=(*enrollment.members[:38], wrong_group, *enrollment.members[39:]),
                )
            )
        )


def test_contract_rejects_chronology_population_shrink_and_numeric_missing() -> None:
    enrollment = _enrollment()
    leaked = seal_member(
        replace(
            enrollment.members[0],
            evidence_ingested_at=datetime(2026, 7, 30, 20, 30, tzinfo=UTC),
        )
    )
    with pytest.raises(ValueError, match="derived from source parents"):
        validate_enrollment(
            seal_enrollment(replace(enrollment, members=(leaked, *enrollment.members[1:])))
        )
    with pytest.raises(ValueError, match="191-member denominator"):
        validate_enrollment(seal_enrollment(replace(enrollment, members=(enrollment.members[1],))))
    missing = seal_member(
        replace(
            enrollment.members[0], terminal_state=TerminalState.MISSING, reasons=("NO_EVIDENCE",)
        )
    )
    with pytest.raises(ValueError, match="non-usable"):
        validate_enrollment(
            seal_enrollment(replace(enrollment, members=(missing, *enrollment.members[1:])))
        )


@pytest.mark.parametrize(
    "collection_name",
    ("reasons", "evidence", "decision_sessions", "planned_entries", "members"),
)
def test_repository_rejects_list_collections_before_database_access(
    collection_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    enrollment = _enrollment()
    if collection_name in {"reasons", "evidence"}:
        member = enrollment.members[0]
        changed_member = replace(
            member, **{collection_name: list(getattr(member, collection_name))}
        )
        candidate = replace(enrollment, members=(changed_member, *enrollment.members[1:]))
    else:
        candidate = replace(
            enrollment, **{collection_name: list(getattr(enrollment, collection_name))}
        )

    def fail_if_connected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("database connection attempted before tuple validation")

    monkeypatch.setattr(
        "equity_analysis.fundamental_value.prospective_company_quality_v1.psycopg.connect",
        fail_if_connected,
    )
    with pytest.raises(ValueError, match="exact tuples"):
        CompanyQualityForwardRepositoryV1("postgresql://unused").enroll(candidate)


def test_offline_readiness_is_honestly_blocked() -> None:
    result = evaluate_offline_readiness(
        calendar_last_session=date(2026, 7, 28),
        evidence_has_ingested_at=False,
        evidence_has_durable_identity=False,
        required_latest_completed_session=date(2026, 7, 31),
    )
    assert result.status == "STRUCTURAL_DIAGNOSTIC_ONLY"
    assert result.real_enrollment_written is False
    assert set(result.reasons) == {
        "COMPLETED_SESSION_CALENDAR_NOT_CURRENT",
        "CONTRACTUAL_INGESTED_AT_MISSING",
        "DURABLE_SECURITY_IDENTITY_MISSING",
        "NON_AUTHORIZING_STRUCTURAL_DIAGNOSTIC",
    }


def test_contract_rejects_parent_hash_drift_and_incomplete_producer_chain() -> None:
    enrollment = _enrollment()
    original = enrollment.members[0]
    drifted_evidence = (
        replace(original.evidence[0], parent_source_content_hash="sha256:" + "b" * 64),
        *original.evidence[1:],
    )
    drifted = seal_member(replace(original, evidence=drifted_evidence))
    with pytest.raises(ValueError, match="aggregate hash mismatch"):
        validate_enrollment(
            seal_enrollment(replace(enrollment, members=(drifted, *enrollment.members[1:])))
        )
    incomplete_evidence = original.evidence[:-1]
    evidence_hash, source_hash = evidence_aggregate_hashes(incomplete_evidence)
    incomplete = seal_member(
        replace(
            original,
            evidence=incomplete_evidence,
            evidence_content_hash=evidence_hash,
            source_content_hash=source_hash,
            producer_output_content_hash=producer_output_hash(
                original.predictor_score, evidence_hash, source_hash
            ),
        )
    )
    with pytest.raises(ValueError, match="complete ordered source-parent"):
        validate_enrollment(
            seal_enrollment(replace(enrollment, members=(incomplete, *enrollment.members[1:])))
        )


def test_contract_rejects_post_entry_seal_and_wrong_population_hash() -> None:
    enrollment = _enrollment()
    with pytest.raises(ValueError, match="before the first eligible entry"):
        validate_enrollment(
            seal_enrollment(
                replace(
                    enrollment,
                    sealed_at=enrollment.planned_entries[0].scheduled_open,
                )
            )
        )
    with pytest.raises(ValueError, match="191-member denominator"):
        validate_enrollment(seal_enrollment(replace(enrollment, population_content_hash=HASH)))


def test_repository_requires_validation_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_connect(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("psycopg.connect", fail_connect)
    invalid = replace(_enrollment(), content_hash=HASH)
    with pytest.raises(ValueError, match="content hash"):
        CompanyQualityForwardRepositoryV1("postgresql://unused").enroll(invalid)
    assert called is False


def test_v18_to_v19_refusal_contract_is_unchanged() -> None:
    v19 = (
        ROOT / "database/migrations/V19__repair_forward_dqv_enrollment_chronology.sql"
    ).read_text(encoding="utf-8")
    assert "V19 refuses to reinterpret existing Forward DQV v2.1.0 enrollments" in v19


def test_parent_replay_is_independent_of_ambient_decimal_context() -> None:
    baseline = _enrollment()
    baseline_member = baseline.members[0]
    with localcontext() as hostile:
        hostile.prec = 50
        hostile.rounding = ROUND_DOWN
        before = hostile.copy()
        replayed = _enrollment()
        assert repr(getcontext()) == repr(before)
    assert replayed.members[0].predictor_score == baseline_member.predictor_score
    assert replayed.members[0].producer_output_content_hash == (
        baseline_member.producer_output_content_hash
    )
    assert replayed.members[0].row_content_hash == baseline_member.row_content_hash
    assert replayed.content_hash == baseline.content_hash


def test_decimal_canonical_lexeme_normalizes_scale_exponent_and_signed_zero() -> None:
    assert canonical_decimal_text(Decimal("1.2300")) == "1.23"
    assert canonical_decimal_text(Decimal("1.23E+2")) == "123"
    assert canonical_decimal_text(Decimal("-0.000")) == "0"
    with pytest.raises(ValueError, match="must be finite"):
        canonical_decimal_text(Decimal("Infinity"))


def test_hash_bound_timestamps_reject_naive_and_fractional_values() -> None:
    enrollment = _enrollment()
    with pytest.raises(ValueError, match="timezone-aware"):
        seal_enrollment(replace(enrollment, decision_cutoff=datetime(2026, 7, 30, 20)))
    with pytest.raises(ValueError, match="whole-second"):
        seal_enrollment(
            replace(
                enrollment,
                decision_cutoff=datetime(2026, 7, 30, 20, 0, 0, 1, tzinfo=UTC),
            )
        )
    fractional_offset = timezone(timedelta(microseconds=500_000))
    colliding_if_truncated = datetime(2026, 1, 1, tzinfo=fractional_offset)
    truncated_utc = datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert colliding_if_truncated.astimezone(UTC) != truncated_utc
    with pytest.raises(ValueError, match="whole-second precision after UTC normalization"):
        seal_enrollment(
            replace(enrollment, decision_cutoff=colliding_if_truncated)
        )


def test_python_temporal_wire_range_is_exactly_years_0001_through_9999() -> None:
    assert _iso_date(date(1, 1, 1), "lower") == "0001-01-01"
    assert _iso_date(date(9999, 12, 31), "upper") == "9999-12-31"
    assert _pg_timestamp(datetime(1, 1, 1, tzinfo=UTC)) == "0001-01-01 00:00:00+00"
    assert _pg_timestamp(datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)) == (
        "9999-12-31 23:59:59+00"
    )
    with pytest.raises(ValueError, match="canonical UTC year range"):
        _pg_timestamp(
            datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1)))
        )
    with pytest.raises(ValueError, match="canonical UTC year range"):
        _pg_timestamp(
            datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(timedelta(hours=-1)))
        )


def test_equivalent_offset_instants_use_the_same_utc_economic_date() -> None:
    enrollment = _enrollment()
    utc_cutoff = datetime(2026, 7, 30, 22, 30, tzinfo=UTC)
    offset_cutoff = utc_cutoff.astimezone(timezone(timedelta(hours=2)))
    utc_enrollment = seal_enrollment(
        replace(
            enrollment,
            decision_cutoff=utc_cutoff,
            evidence_cutoff=utc_cutoff,
            sealed_at=datetime(2026, 7, 30, 23, tzinfo=UTC),
        )
    )
    offset_enrollment = seal_enrollment(
        replace(
            enrollment,
            decision_cutoff=offset_cutoff,
            evidence_cutoff=offset_cutoff,
            sealed_at=datetime(2026, 7, 30, 23, tzinfo=UTC),
        )
    )
    validate_enrollment(utc_enrollment)
    validate_enrollment(offset_enrollment)
    assert utc_enrollment.content_hash == offset_enrollment.content_hash


def test_exact_mic_session_and_planned_entry_sets_are_required() -> None:
    enrollment = _enrollment()
    with pytest.raises(ValueError, match="decision-session set"):
        validate_enrollment(
            seal_enrollment(
                replace(enrollment, decision_sessions=enrollment.decision_sessions[:1])
            )
        )
    with pytest.raises(ValueError, match="planned-entry set"):
        validate_enrollment(
            seal_enrollment(replace(enrollment, planned_entries=enrollment.planned_entries[:1]))
        )
    with pytest.raises(ValueError, match="share one entry date"):
        validate_enrollment(
            seal_enrollment(
                replace(
                    enrollment,
                    planned_entries=(
                        enrollment.planned_entries[0],
                        replace(
                            enrollment.planned_entries[1],
                            entry_date=enrollment.planned_entries[1].entry_date
                            + timedelta(days=1),
                            scheduled_open=enrollment.planned_entries[1].scheduled_open
                            + timedelta(days=1),
                            scheduled_close=enrollment.planned_entries[1].scheduled_close
                            + timedelta(days=1),
                        ),
                    ),
                )
            )
        )


def test_python_revision_cutoff_entry_and_nonblank_contract_parity() -> None:
    enrollment = _enrollment()
    with pytest.raises(ValueError, match="revision 1 without supersession"):
        seal_enrollment(
            replace(enrollment, enrollment_revision=2, supersedes_enrollment_id=UUID(int=9))
        )
    unequal_cutoff = seal_enrollment(
        replace(
            enrollment,
            content_hash="",
            evidence_cutoff=enrollment.evidence_cutoff - timedelta(seconds=1),
        )
    )
    with pytest.raises(ValueError, match="invalid enrollment chronology"):
        validate_enrollment(unequal_cutoff)
    mismatched_entries = tuple(
        replace(entry, entry_date=entry.entry_date + timedelta(days=1))
        for entry in enrollment.planned_entries
    )
    mismatched = seal_enrollment(
        replace(enrollment, content_hash="", planned_entries=mismatched_entries)
    )
    with pytest.raises(ValueError, match="planned-entry schedule/chronology"):
        validate_enrollment(mismatched)

    with pytest.raises(ValueError, match="nonblank delimiter-free hash grammar"):
        seal_enrollment(
            replace(
                enrollment,
                content_hash="",
                planned_entries=(
                    replace(enrollment.planned_entries[0], schedule_source_id="   "),
                    enrollment.planned_entries[1],
                ),
            )
        )
    member = enrollment.members[0]
    with pytest.raises(ValueError, match="member reasons must be unique"):
        seal_member(replace(member, reasons=("DUPLICATE", "DUPLICATE")))
    with pytest.raises(ValueError, match="nonblank delimiter-free hash grammar"):
        seal_member(
            replace(
                member,
                evidence=(
                    replace(member.evidence[0], provider_code="   "),
                    *member.evidence[1:],
                ),
            )
        )


def test_parent_replay_requires_aligned_flows_and_c5_balance_boundaries() -> None:
    evidence = _member().evidence
    shifted_flow = tuple(
        replace(item, parent_period_end=item.parent_period_end - timedelta(days=1))
        if item.operand_code == "REVENUE" and item.parent_period_end == date(2026, 6, 30)
        else item
        for item in evidence
    )
    with pytest.raises(ValueError, match="exact common four-quarter"):
        company_quality_score_from_parents(shifted_flow)

    post_boundary = tuple(
        replace(item, parent_period_end=date(2026, 7, 1))
        if item.operand_code == "STOCKHOLDERS_EQUITY"
        and item.parent_period_end == date(2026, 6, 30)
        else item
        for item in evidence
    )
    with pytest.raises(ValueError, match="after the ROIC period boundary"):
        company_quality_score_from_parents(post_boundary)

    missing_start_boundary = tuple(
        replace(item, parent_period_end=item.parent_period_end - timedelta(days=121))
        if item.operand_code == "TOTAL_DEBT"
        and item.parent_period_end <= date(2025, 6, 30)
        else item
        for item in evidence
    )
    with pytest.raises(ValueError, match="balance boundary parent is missing"):
        company_quality_score_from_parents(missing_start_boundary)


def test_parent_replay_rejects_each_negative_capex_parent() -> None:
    evidence = _member().evidence
    changed_one = False
    mixed_sign = []
    for item in evidence:
        if item.operand_code == "CAPITAL_EXPENDITURE" and not changed_one:
            mixed_sign.append(replace(item, numeric_value=Decimal("-1")))
            changed_one = True
        else:
            mixed_sign.append(item)
    assert sum(
        item.numeric_value
        for item in mixed_sign
        if item.operand_code == "CAPITAL_EXPENDITURE"
        and item.parent_period_end >= date(2025, 9, 30)
    ) > 0
    with pytest.raises(ValueError, match="capital-expenditure sign"):
        company_quality_score_from_parents(tuple(mixed_sign))

    oldest_capex_period = min(
        item.parent_period_end
        for item in evidence
        if item.operand_code == "CAPITAL_EXPENDITURE"
    )
    older_negative = tuple(
        replace(item, numeric_value=Decimal("-1"))
        if item.operand_code == "CAPITAL_EXPENDITURE"
        and item.parent_period_end == oldest_capex_period
        else item
        for item in evidence
    )
    with pytest.raises(ValueError, match="capital-expenditure sign"):
        company_quality_score_from_parents(older_negative)


def test_python_varchar_limits_cover_every_bounded_v24_string() -> None:
    expected_limits = {
        "enrollment.producer_version": 128,
        "enrollment.arithmetic_version": 128,
        "enrollment.cost_policy_version": 128,
        "enrollment.outcome_policy_version": 128,
        "enrollment.idempotency_key": 128,
        "decision_session.mic": 4,
        "decision_session.calendar_id": 64,
        "decision_session.calendar_version": 128,
        "planned_entry.mic": 4,
        "planned_entry.schedule_source_id": 128,
        "planned_entry.schedule_source_version": 128,
        "member.listing_mic": 4,
        "member.predictor_group": 8,
        "member.reason": 128,
        "source_parent.operand_code": 64,
        "source_parent.canonical_field_code": 64,
        "source_parent.provenance_kind": 40,
        "source_parent.provider_code": 128,
        "source_parent.provider_schema_version": 128,
        "source_parent.source_record_id": 255,
        "source_parent.currency": 3,
        "source_parent.unit": 32,
    }
    assert VARCHAR_LIMITS == expected_limits
    for name, limit in expected_limits.items():
        _bounded_hash_atom("x" * limit, name)
        with pytest.raises(ValueError, match="PostgreSQL character limit"):
            _bounded_hash_atom("x" * (limit + 1), name)

    enrollment = _enrollment()
    with pytest.raises(ValueError, match="PostgreSQL character limit"):
        seal_enrollment(replace(enrollment, idempotency_key="x" * 129))
    with pytest.raises(ValueError, match="PostgreSQL character limit"):
        seal_enrollment(
            replace(
                enrollment,
                decision_sessions=(
                    replace(enrollment.decision_sessions[0], calendar_id="x" * 65),
                    enrollment.decision_sessions[1],
                ),
            )
        )
    member = enrollment.members[0]
    with pytest.raises(ValueError, match="PostgreSQL character limit"):
        seal_member(
            replace(
                member,
                evidence=(
                    replace(member.evidence[0], source_record_id="x" * 256),
                    *member.evidence[1:],
                ),
            )
        )

    max_revision = seal_member(
        replace(
            member,
            evidence=(
                replace(member.evidence[0], source_revision=2_147_483_647),
                *member.evidence[1:],
            ),
        )
    )
    assert max_revision.row_content_hash
    with pytest.raises(ValueError, match="PostgreSQL INTEGER domain"):
        seal_member(
            replace(
                member,
                evidence=(
                    replace(member.evidence[0], source_revision=2_147_483_648),
                    *member.evidence[1:],
                ),
            )
        )
    with pytest.raises(ValueError, match="PostgreSQL INTEGER domain"):
        seal_enrollment(replace(enrollment, enrollment_revision=True))
    with pytest.raises(ValueError, match="exact boolean"):
        seal_enrollment(
            replace(
                enrollment,
                decision_sessions=(
                    replace(enrollment.decision_sessions[0], early_close=0),
                    enrollment.decision_sessions[1],
                ),
            )
        )
    with pytest.raises(ValueError, match="exact boolean"):
        seal_enrollment(
            replace(
                enrollment,
                planned_entries=(
                    replace(enrollment.planned_entries[0], early_close=1),
                    enrollment.planned_entries[1],
                ),
            )
        )

    assert len(canonical_decimal_text(Decimal("1e131071"))) == 131_072
    assert canonical_decimal_text(Decimal("1e-16383")).endswith("1")
    for invalid in (Decimal("1e131072"), Decimal("1e-16384")):
        with pytest.raises(ValueError, match="PostgreSQL NUMERIC limits"):
            canonical_decimal_text(invalid)
    with pytest.raises(ValueError, match="PostgreSQL NUMERIC limits"):
        seal_member(replace(member, predictor_score=Decimal("1e131072")))
    old_parent = min(member.evidence, key=lambda item: item.parent_period_end)
    with pytest.raises(ValueError, match="PostgreSQL NUMERIC limits"):
        seal_member(
            replace(
                member,
                evidence=tuple(
                    replace(item, numeric_value=Decimal("1e-16384"))
                    if item is old_parent
                    else item
                    for item in member.evidence
                ),
            )
        )


def test_completed_session_recording_cannot_precede_completion() -> None:
    enrollment = _enrollment()
    invalid_session = replace(
        enrollment.decision_sessions[0],
        recorded_at=enrollment.decision_sessions[0].completed_at - timedelta(seconds=1),
    )
    candidate = seal_enrollment(
        replace(
            enrollment,
            decision_sessions=(invalid_session, enrollment.decision_sessions[1]),
        )
    )
    with pytest.raises(ValueError, match="decision-session identity/calendar/chronology"):
        validate_enrollment(candidate)


def test_python_integer_boolean_and_numeric_wire_domains() -> None:
    enrollment = _enrollment()
    member = enrollment.members[0]
    with pytest.raises(ValueError, match="PostgreSQL INTEGER domain"):
        seal_member(replace(member, member_ordinal=True))
    with pytest.raises(ValueError, match="PostgreSQL INTEGER domain"):
        seal_member(replace(member, predictor_rank=True))
    with pytest.raises(ValueError, match="PostgreSQL INTEGER domain"):
        seal_member(
            replace(
                member,
                evidence=(
                    replace(member.evidence[0], evidence_ordinal=True),
                    *member.evidence[1:],
                ),
            )
        )


def test_parent_magnitude_envelope_prevents_sql_intermediate_overflow() -> None:
    member = _enrollment().members[0]
    latest_revenue = sorted(
        (item for item in member.evidence if item.operand_code == "REVENUE"),
        key=lambda item: item.parent_period_end,
        reverse=True,
    )[:2]
    bounded = seal_member(
        replace(
            member,
            evidence=tuple(
                replace(item, numeric_value=MAX_ABS_PARENT_VALUE)
                if item in latest_revenue
                else item
                for item in member.evidence
            ),
        )
    )
    assert company_quality_score_from_parents(bounded.evidence).is_finite()

    old_parent = min(member.evidence, key=lambda item: item.parent_period_end)
    with pytest.raises(ValueError, match="economic magnitude envelope"):
        seal_member(
            replace(
                member,
                evidence=tuple(
                    replace(item, numeric_value=Decimal("1e101"))
                    if item is old_parent
                    else item
                    for item in member.evidence
                ),
            )
        )
    with localcontext() as hostile:
        hostile.prec = 1
        with pytest.raises(ValueError, match="economic magnitude envelope"):
            seal_member(
                replace(
                    member,
                    evidence=tuple(
                        replace(item, numeric_value=Decimal("1.4e100"))
                        if item is old_parent
                        else item
                        for item in member.evidence
                    ),
                )
            )


def test_parent_fractional_scale_envelope_is_shared_and_fail_closed() -> None:
    member = _enrollment().members[0]
    target = next(item for item in member.evidence if item.operand_code == "NET_INCOME")
    assert MAX_PARENT_FRACTIONAL_DIGITS == 100
    for accepted in (Decimal(0), Decimal("1e-100"), Decimal("-1e-100")):
        sealed = seal_member(
            replace(
                member,
                evidence=tuple(
                    replace(item, numeric_value=accepted) if item is target else item
                    for item in member.evidence
                ),
            )
        )
        assert sealed.row_content_hash
    for rejected in (Decimal("1e-101"), Decimal("1e-16383")):
        with pytest.raises(ValueError, match="fractional scale envelope"):
            seal_member(
                replace(
                    member,
                    evidence=tuple(
                        replace(item, numeric_value=rejected) if item is target else item
                        for item in member.evidence
                    ),
                )
            )


def test_best_first_rank_order_is_independent_of_ambient_decimal_context() -> None:
    first, second = _enrollment().members[:2]
    rows = [
        replace(first, predictor_score=Decimal("60.03")),
        replace(second, predictor_score=Decimal("60.04")),
    ]
    with localcontext() as hostile:
        hostile.prec = 1
        hostile.rounding = ROUND_DOWN
        before = hostile.copy()
        ordered = _best_first_members(rows)
        assert repr(getcontext()) == repr(before)
    assert [row.security_id for row in ordered] == [second.security_id, first.security_id]


def test_every_uuid_wire_field_requires_an_exact_uuid_instance() -> None:
    expected = {
        "enrollment.enrollment_id",
        "enrollment.supersedes_enrollment_id",
        "decision_session.completed_session_id",
        "member.security_id",
        "member.company_id",
        "member.instrument_id",
        "member.share_class_id",
        "member.listing_id",
        "member.ticker_assignment_id",
        "source_parent.selection_request_id",
        "source_parent.canonical_evidence_id",
        "source_parent.normalized_parent_id",
        "source_parent.raw_manifest_id",
    }
    assert UUID_FIELD_NAMES == expected
    canonical = UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
    for name in sorted(expected):
        _uuid_value(canonical, name)
        with pytest.raises(ValueError, match="exact UUID instance"):
            _uuid_value(str(canonical).upper(), name)  # type: ignore[arg-type]


def test_python_enforces_only_schema_proven_enrollment_uniqueness() -> None:
    enrollment = _enrollment()
    first, second = enrollment.members[:2]
    for changed_second in (
        replace(second, listing_id=first.listing_id),
        replace(second, ticker_assignment_id=first.ticker_assignment_id),
    ):
        candidate = seal_enrollment(
            replace(
                enrollment,
                members=(first, seal_member(changed_second), *enrollment.members[2:]),
            )
        )
        with pytest.raises(ValueError, match="identity-unique"):
            validate_enrollment(candidate)

    duplicate_calendar = replace(
        enrollment.decision_sessions[1],
        calendar_id=enrollment.decision_sessions[0].calendar_id,
        calendar_version=enrollment.decision_sessions[0].calendar_version,
    )
    candidate = seal_enrollment(
        replace(
            enrollment,
            decision_sessions=(enrollment.decision_sessions[0], duplicate_calendar),
        )
    )
    with pytest.raises(ValueError, match="calendar contract identities must be unique"):
        validate_enrollment(candidate)

    member = enrollment.members[0]
    v22 = [
        item for item in member.evidence if item.provenance_kind == "V22_SELECTED_EVIDENCE"
    ]
    provider = [
        item
        for item in member.evidence
        if item.provenance_kind == "V24_PROVIDER_NORMALIZED_PARENT"
    ]
    mutations = (
        replace(v22[1], selection_request_id=v22[0].selection_request_id),
        replace(v22[1], selection_result_hash=v22[0].selection_result_hash),
        replace(v22[1], canonical_evidence_id=v22[0].canonical_evidence_id),
        replace(provider[1], normalized_parent_id=provider[0].normalized_parent_id),
        replace(
            provider[1],
            parent_normalized_record_hash=provider[0].parent_normalized_record_hash,
        ),
        replace(
            provider[1],
            raw_manifest_id=provider[0].raw_manifest_id,
            canonical_field_code=provider[0].canonical_field_code,
            parent_period_end=provider[0].parent_period_end,
        ),
    )
    for mutation in mutations:
        changed = tuple(
            mutation if item.evidence_ordinal == mutation.evidence_ordinal else item
            for item in member.evidence
        )
        changed_member = seal_member(replace(member, evidence=changed))
        candidate = seal_enrollment(
            replace(
                enrollment,
                members=(changed_member, *enrollment.members[1:]),
            )
        )
        with pytest.raises(ValueError, match="identities must be unique"):
            validate_enrollment(candidate)


def test_hash_atoms_reject_delimiter_collision_inputs() -> None:
    enrollment = _enrollment()
    for whitespace_only in ("\t", "\n", "\r", "\f", "\v", " \t\n\r\f\v", "A\x00B"):
        with pytest.raises(ValueError, match="delimiter-free hash grammar"):
            seal_enrollment(
                replace(
                    enrollment,
                    planned_entries=(
                        replace(
                            enrollment.planned_entries[0],
                            schedule_source_id=whitespace_only,
                        ),
                        enrollment.planned_entries[1],
                    ),
                )
            )
    non_ascii_whitespace = seal_enrollment(
        replace(
            enrollment,
            content_hash="",
            planned_entries=(
                replace(enrollment.planned_entries[0], schedule_source_id="\u00a0"),
                enrollment.planned_entries[1],
            ),
        )
    )
    assert non_ascii_whitespace.content_hash
    with pytest.raises(ValueError, match="delimiter-free hash grammar"):
        seal_enrollment(
            replace(
                enrollment,
                planned_entries=(
                    replace(
                        enrollment.planned_entries[0],
                        schedule_source_id="AUTH:V1",
                        schedule_source_version="REV",
                    ),
                    enrollment.planned_entries[1],
                ),
            )
        )


def test_exact_sha256_grammar_rejects_session_calendar_collision() -> None:
    enrollment = _enrollment()
    session = enrollment.decision_sessions[0]
    for changed in (
        replace(
            session,
            session_content_hash="sha256:a:sha256:b",
            calendar_content_hash="sha256:c",
        ),
        replace(
            session,
            session_content_hash="sha256:a",
            calendar_content_hash="sha256:b:sha256:c",
        ),
    ):
        with pytest.raises(ValueError, match="exact lowercase sha256 digest"):
            seal_enrollment(
                replace(
                    enrollment,
                    decision_sessions=(changed, *enrollment.decision_sessions[1:]),
                )
            )


def test_every_python_hash_field_uses_exact_sha256_grammar() -> None:
    enrollment = _enrollment()
    bad = "sha256:a:sha256:b"
    header_fields = (
        "population_content_hash",
        "evidence_manifest_content_hash",
        "predictor_contract_content_hash",
        "outcome_protocol_content_hash",
        "stage7_acceptance_content_hash",
        "content_hash",
    )
    actions = [
        lambda field=field: seal_enrollment(replace(enrollment, **{field: bad}))
        for field in header_fields
    ]
    session = enrollment.decision_sessions[0]
    for field in ("session_content_hash", "calendar_content_hash"):
        actions.append(
            lambda field=field: seal_enrollment(
                replace(
                    enrollment,
                    decision_sessions=(
                        replace(session, **{field: bad}),
                        *enrollment.decision_sessions[1:],
                    ),
                )
            )
        )
    entry = enrollment.planned_entries[0]
    for field in ("schedule_source_content_hash", "schedule_content_hash"):
        actions.append(
            lambda field=field: seal_enrollment(
                replace(
                    enrollment,
                    planned_entries=(
                        replace(entry, **{field: bad}),
                        *enrollment.planned_entries[1:],
                    ),
                )
            )
        )
    member = enrollment.members[0]
    for field in (
        "evidence_content_hash",
        "source_content_hash",
        "producer_contract_content_hash",
        "producer_output_content_hash",
    ):
        actions.append(lambda field=field: seal_member(replace(member, **{field: bad})))
    evidence = member.evidence[0]
    for field in (
        "selection_result_hash",
        "parent_source_content_hash",
        "parent_normalized_record_hash",
    ):
        actions.append(
            lambda field=field: seal_member(
                replace(
                    member,
                    evidence=(
                        replace(evidence, **{field: bad}),
                        *member.evidence[1:],
                    ),
                )
            )
        )
    for action in actions:
        with pytest.raises(ValueError, match="exact lowercase sha256 digest"):
            action()

    invalid_row = replace(member, row_content_hash=bad)
    candidate = seal_enrollment(
        replace(enrollment, content_hash="", members=(invalid_row, *enrollment.members[1:]))
    )
    with pytest.raises(ValueError, match="exact lowercase sha256 digest"):
        validate_enrollment(candidate)
    with pytest.raises(ValueError, match="delimiter-free hash grammar"):
        seal_enrollment(
            replace(
                enrollment,
                planned_entries=(
                    replace(
                        enrollment.planned_entries[0],
                        schedule_source_id="AUTH",
                        schedule_source_version="V1:REV",
                    ),
                    enrollment.planned_entries[1],
                ),
            )
        )
