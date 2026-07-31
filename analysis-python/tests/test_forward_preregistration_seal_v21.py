from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v21 import (
    BENCHMARK_CONSTRUCTION_V21,
    EQUAL_WEIGHT_CONSTRUCTION_VERSION,
    MINIMUM_OBJECTIVE_SCORE_COUNT,
    MINIMUM_OBJECTIVE_SCORE_COVERAGE,
    MOMENTUM_CONSTRUCTION_VERSION,
    OBJECTIVE_SCORE_CONSTRUCTION_VERSION,
    SECTOR_CONSTRUCTION_VERSION,
    BenchmarkCostPolicyV21,
)
from equity_analysis.forward_validation.preregistration_seal_v21 import (
    _write_or_verify,
    build_benchmark_construction_policy_binding,
    build_preregistration_seal_bundle,
    verify_seal_bundle,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PARENT_REGISTERED_AT = datetime(2026, 7, 30, 3, 10, tzinfo=UTC)
BENCHMARK_REGISTERED_AT = datetime(
    2026,
    7,
    30,
    3,
    10,
    1,
    tzinfo=UTC,
)


def _bundle():
    return build_preregistration_seal_bundle(
        repository_root=REPOSITORY_ROOT,
        parent_registered_at=PARENT_REGISTERED_AT,
        benchmark_registered_at=BENCHMARK_REGISTERED_AT,
    )


def test_seal_binds_freezes_universe_boundaries_and_six_benchmarks() -> None:
    bundle = _bundle()

    assert bundle.parent.schema_version == "FORWARD-DQV-PREREGISTRATION-v2.0.0"
    assert bundle.benchmark.schema_version == (
        "FORWARD-BENCHMARK-PREREGISTRATION-v2.1.0"
    )
    assert bundle.parent.registered_at > max(
        item.frozen_at for item in bundle.parent.model_freezes
    )
    assert bundle.benchmark.registered_at > bundle.parent.registered_at
    assert bundle.parent.prospective_universe.security_count == 66
    assert len(bundle.parent.prospective_universe.securities) == 66
    assert len(
        {
            item.public_security_id
            for item in bundle.parent.prospective_universe.securities
        }
    ) == 66
    assert tuple(item.role for item in bundle.parent.evidence_boundaries) == (
        "DEVELOPMENT_OBSERVED",
        "SEALED_HISTORICAL_VALIDATION",
        "PROSPECTIVE_FORWARD",
    )
    assert tuple(bundle.benchmark.required_benchmark_kinds) == tuple(BenchmarkKind)
    assert bundle.parent.missing_data_neutral_substitution_allowed is False
    assert bundle.parent.point_in_time_availability_required is True
    assert bundle.parent.independent_dataset_freshness_required is True


def test_legacy_beaa9952_is_explicitly_ineligible() -> None:
    bundle = _bundle()

    assert bundle.seal.legacy_decision.data_snapshot_id.startswith("beaa9952")
    assert bundle.seal.legacy_decision.preregistration_eligible is False
    assert bundle.seal.legacy_decision.upgrade_allowed is False
    assert (
        bundle.seal.legacy_decision.decision_as_of
        < bundle.parent.registered_at
        < bundle.benchmark.registered_at
    )
    assert bundle.seal.future_decision_must_be_strictly_after == (
        bundle.benchmark.registered_at
    )


def test_preregistration_cannot_precede_or_equal_freeze() -> None:
    with pytest.raises(ValueError, match="must follow both model freezes"):
        build_preregistration_seal_bundle(
            repository_root=REPOSITORY_ROOT,
            parent_registered_at=datetime(2026, 7, 30, 0, 45, tzinfo=UTC),
            benchmark_registered_at=datetime(
                2026,
                7,
                30,
                0,
                45,
                1,
                tzinfo=UTC,
            ),
        )


def test_benchmark_preregistration_must_strictly_follow_parent() -> None:
    with pytest.raises(
        ValueError,
        match="Benchmark preregistration must follow the parent",
    ):
        build_preregistration_seal_bundle(
            repository_root=REPOSITORY_ROOT,
            parent_registered_at=PARENT_REGISTERED_AT,
            benchmark_registered_at=PARENT_REGISTERED_AT,
        )


def test_construction_policy_binding_matches_frozen_builder_policy() -> None:
    bundle = _bundle()
    version, actual = build_benchmark_construction_policy_binding(bundle.parent)
    expected = canonical_hash(
        {
            "version": BENCHMARK_CONSTRUCTION_V21,
            "requiredKinds": tuple(item.value for item in BenchmarkKind),
            "sectorPolicy": SECTOR_CONSTRUCTION_VERSION,
            "equalWeightPolicy": EQUAL_WEIGHT_CONSTRUCTION_VERSION,
            "momentumPolicy": MOMENTUM_CONSTRUCTION_VERSION,
            "objectivePolicy": OBJECTIVE_SCORE_CONSTRUCTION_VERSION,
            "minimumObjectiveScoreCount": MINIMUM_OBJECTIVE_SCORE_COUNT,
            "minimumObjectiveScoreCoverage": MINIMUM_OBJECTIVE_SCORE_COVERAGE,
            "parentLiquidityCostPolicyHash": bundle.parent.cost_policy_hash,
            "costPolicyHash": canonical_hash(BenchmarkCostPolicyV21()),
        }
    )

    assert version == BENCHMARK_CONSTRUCTION_V21
    assert actual == expected
    assert bundle.benchmark.construction_policy_hash == expected


def test_immutable_writer_accepts_exact_replay_and_rejects_conflict(
    tmp_path: Path,
) -> None:
    path = tmp_path / "immutable.json"
    payload = b'{"status":"SEALED"}\n'

    _write_or_verify(path, payload)
    _write_or_verify(path, payload)
    with pytest.raises(ValueError, match="Immutable artifact conflict"):
        _write_or_verify(path, b'{"status":"CHANGED"}\n')


def test_seal_hash_verification_rejects_tampering() -> None:
    bundle = _bundle()
    verify_seal_bundle(bundle, repository_root=REPOSITORY_ROOT)
    tampered = bundle.seal.model_copy(
        update={"prospective_security_count": 65}
    )

    with pytest.raises(ValueError, match="does not match its immutable inputs"):
        verify_seal_bundle(
            bundle.__class__(
                parent=bundle.parent,
                benchmark=bundle.benchmark,
                seal=tampered,
            ),
            repository_root=REPOSITORY_ROOT,
        )


def test_git_safe_payloads_contain_no_values_or_secrets() -> None:
    bundle = _bundle()
    payload = json.dumps(
        {
            "parent": bundle.parent.model_dump(mode="json", by_alias=True),
            "benchmark": bundle.benchmark.model_dump(
                mode="json",
                by_alias=True,
            ),
            "seal": bundle.seal.model_dump(mode="json", by_alias=True),
        },
        sort_keys=True,
    ).lower()

    for forbidden in (
        '"value"',
        "api_token",
        "api_key",
        "authorization",
        "rawproviderpayload",
        '"score"',
    ):
        assert forbidden not in payload
    assert bundle.seal.deterministic_scores_included is False
