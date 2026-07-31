from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from controlled_data import require_artifact_controlled_references

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_v22_feasibility import (
    _same_current_snapshot_operands,
    build_benchmark_v22_feasibility_artifact,
    select_top_quintile_valid_candidates,
    selected_count_for_valid_candidates,
)
from equity_analysis.forward_validation.preregistration_seal_v21 import (
    BENCHMARK_ARTIFACT_RELATIVE_PATH,
    SEAL_ARTIFACT_RELATIVE_PATH,
    load_preregistration_seal_bundle,
)
from equity_analysis.forward_validation.preregistration_seal_v22 import (
    PreregistrationSealBundleV22,
    _write_or_verify,
    build_preregistration_seal_bundle_v22,
    verify_preregistration_seal_bundle_v22,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTROLLED_MANIFESTS = (
    "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-7.json",
    "docs/generated/objective-rating-v1-current-snapshot-supplements-v3.json",
)


def _require_controlled_benchmark_inputs() -> None:
    require_artifact_controlled_references(
        REPOSITORY_ROOT,
        CONTROLLED_MANIFESTS,
        purpose="Forward benchmark v2.2 construction",
    )


def _times() -> tuple[datetime, datetime]:
    predecessor = load_preregistration_seal_bundle(
        repository_root=REPOSITORY_ROOT
    )
    rule_frozen_at = predecessor.seal.sealed_at + timedelta(seconds=1)
    return rule_frozen_at, rule_frozen_at + timedelta(microseconds=1)


def _bundle() -> PreregistrationSealBundleV22:
    _require_controlled_benchmark_inputs()
    rule_frozen_at, registered_at = _times()
    return build_preregistration_seal_bundle_v22(
        repository_root=REPOSITORY_ROOT,
        rule_frozen_at=rule_frozen_at,
        registered_at=registered_at,
    )


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate(
    public_security_id: str,
    score: str,
    *,
    status: str = "VALID",
) -> dict[str, str]:
    return {
        "publicSecurityId": public_security_id,
        "score": score,
        "status": status,
    }


def test_mechanical_top_quintile_count_and_stable_tie_break() -> None:
    assert selected_count_for_valid_candidates(44) == 9
    assert selected_count_for_valid_candidates(55) == 11

    candidates = tuple(
        _candidate(f"id-{index:02d}", "100" if index < 3 else str(90 - index))
        for index in range(44)
    )
    selected = select_top_quintile_valid_candidates(candidates)

    assert len(selected) == 9
    assert selected[:3] == ("id-00", "id-01", "id-02")


def test_checked_in_feasibility_artifact_is_canonical_and_git_safe() -> None:
    path = REPOSITORY_ROOT / "docs/generated/forward-benchmark-v2-2-feasibility.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    body = dict(artifact)
    claim = body.pop("artifactContentHash")

    assert canonical_hash(body) == claim
    rendered = json.dumps(artifact, sort_keys=True).lower()
    assert '"value":' not in rendered
    assert "api_token" not in rendered
    assert "authorization" not in rendered


def test_missing_candidates_count_against_coverage_gate() -> None:
    candidates = tuple(
        _candidate(f"id-{index:02d}", str(index))
        for index in range(43)
    ) + tuple(
        _candidate(f"missing-{index:02d}", "0", status="MISSING")
        for index in range(12)
    )

    with pytest.raises(ValueError, match="below the frozen 80 percent gate"):
        select_top_quintile_valid_candidates(candidates)


def test_negative_numerator_is_valid_but_denominator_must_be_positive() -> None:
    source_hash = f"sha256:{'a' * 64}"
    numerator = {
        "status": "VALID",
        "unit": "USD",
        "currency": "USD",
        "availableAt": "2026-07-29T00:00:00Z",
        "sourceContentHashes": [source_hash],
        "orderedEvidenceIds": ["numerator-evidence"],
        "periodIds": ["TTM:2026-06-30"],
        "value": "-10",
    }
    denominator = {
        **numerator,
        "orderedEvidenceIds": ["denominator-evidence"],
        "value": "100",
    }

    assert _same_current_snapshot_operands(
        numerator,
        denominator,
        denominator_must_be_positive=True,
    ) == (True, ())
    denominator["value"] = "0"
    ready, reasons = _same_current_snapshot_operands(
        numerator,
        denominator,
        denominator_must_be_positive=True,
    )
    assert ready is False
    assert reasons == ("DENOMINATOR_NOT_POSITIVE",)


def test_feasibility_preserves_population_and_freezes_data_pending_rules() -> None:
    _require_controlled_benchmark_inputs()
    rule_frozen_at, _ = _times()
    predecessor = load_preregistration_seal_bundle(
        repository_root=REPOSITORY_ROOT
    )
    artifact = build_benchmark_v22_feasibility_artifact(
        repository_root=REPOSITORY_ROOT,
        evaluated_at=rule_frozen_at,
    )

    assert artifact["evaluatedPopulation"] == {
        "securityCount": 66,
        "identityBindingHash": (
            predecessor.parent.prospective_universe.identity_binding_hash
        ),
        "rolesUnchanged": True,
        "stableIdsUnchanged": True,
        "includedCount": 55,
    }
    assert artifact["currentCacheDiagnostic"]["requiredCount"] == 44
    assert artifact["currentCacheDiagnostic"]["valueReadyCount"] == 42
    assert artifact["currentCacheDiagnostic"]["qualityReadyCount"] == 42
    assert artifact["currentCacheDiagnostic"]["constructionReady"] is False
    policy = artifact["candidatePolicy"]
    assert policy["objectiveRatingScoreDependency"] is False
    assert policy["selectionCountFormula"] == (
        "CEILING(VALID_CANDIDATE_COUNT * 0.20)"
    )
    assert policy["selectedCountAtMinimumCoverage"] == 9
    assert policy["selectedCountAtFullCoverage"] == 11
    assert policy["missingOrStaleOrConflictingInputs"] == (
        "EXCLUDE_AND_COUNT_IN_COVERAGE"
    )


def test_external_reference_universe_reuses_spy_and_xlk_ids() -> None:
    bundle = _bundle()
    predecessor = load_preregistration_seal_bundle(
        repository_root=REPOSITORY_ROOT
    )
    evaluated_ids = {
        row.symbol: str(row.public_security_id)
        for row in predecessor.parent.prospective_universe.securities
    }
    references = {
        row["symbol"]: row
        for row in bundle.external_reference_universe["references"]
    }

    assert len(references) == 12
    assert len(
        {row["publicSecurityId"] for row in references.values()}
    ) == 12
    assert references["SPY"]["publicSecurityId"] == evaluated_ids["SPY"]
    assert references["XLK"]["publicSecurityId"] == evaluated_ids["XLK"]
    assert references["SPY"]["identitySource"] == (
        "FROZEN_EVALUATED_POPULATION"
    )
    assert references["XLK"]["identitySource"] == (
        "FROZEN_EVALUATED_POPULATION"
    )
    assert sum(row["sector"] is not None for row in references.values()) == 11


def test_preflight_is_all_55_offline_and_zero_retry() -> None:
    preflight = _bundle().data_preflight

    assert preflight["scopeSecurityCount"] == 55
    assert len(preflight["symbols"]) == 55
    assert len({row["symbol"] for row in preflight["symbols"]}) == 55
    assert preflight["endpointAttemptCeiling"] == 55
    assert preflight["configuredWeightCeiling"] == 550
    assert preflight["retryCount"] == 0
    assert preflight["networkExecutionAuthorized"] is False


def test_v22_chronology_follows_predecessor_and_blocks_legacy_upgrades() -> None:
    bundle = _bundle()
    predecessor = load_preregistration_seal_bundle(
        repository_root=REPOSITORY_ROOT
    )

    assert bundle.benchmark.rule_frozen_at > predecessor.seal.sealed_at
    assert bundle.benchmark.registered_at > bundle.benchmark.rule_frozen_at
    assert bundle.seal.sealed_at == bundle.benchmark.registered_at
    assert bundle.seal.legacy_decisions_upgrade_allowed is False
    assert bundle.seal.legacy_results_upgrade_allowed is False
    assert bundle.seal.predecessor_results_upgrade_allowed is False
    assert bundle.seal.benchmark_evidence_available is False
    assert bundle.benchmark.readiness_controller_compatibility == (
        "REQUIRES_V2_2_ADAPTER"
    )

    with pytest.raises(ValueError, match="must follow the predecessor seal"):
        build_preregistration_seal_bundle_v22(
            repository_root=REPOSITORY_ROOT,
            rule_frozen_at=predecessor.seal.sealed_at,
            registered_at=predecessor.seal.sealed_at
            + timedelta(microseconds=1),
        )


def test_old_v21_artifacts_are_not_modified_by_v22_build() -> None:
    old_paths = (
        REPOSITORY_ROOT / BENCHMARK_ARTIFACT_RELATIVE_PATH,
        REPOSITORY_ROOT / SEAL_ARTIFACT_RELATIVE_PATH,
    )
    before = tuple(_hash(path) for path in old_paths)

    _bundle()

    assert tuple(_hash(path) for path in old_paths) == before


def test_immutable_writer_replays_exact_bytes_and_rejects_conflict(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifact.json"
    payload = {"artifactContentHash": f"sha256:{'a' * 64}"}

    _write_or_verify(path, payload)
    _write_or_verify(path, payload)
    with pytest.raises(ValueError, match="Immutable v2.2 artifact conflict"):
        _write_or_verify(
            path,
            {"artifactContentHash": f"sha256:{'b' * 64}"},
        )


def test_seal_rejects_tampering_and_git_safe_outputs_omit_values() -> None:
    bundle = _bundle()
    verify_preregistration_seal_bundle_v22(
        bundle,
        repository_root=REPOSITORY_ROOT,
    )
    tampered = bundle.seal.model_copy(
        update={"legacy_results_upgrade_allowed": True}
    )
    with pytest.raises(ValueError, match="canonical hash is invalid"):
        verify_preregistration_seal_bundle_v22(
            PreregistrationSealBundleV22(
                feasibility=bundle.feasibility,
                candidate_policy=bundle.candidate_policy,
                external_reference_universe=bundle.external_reference_universe,
                data_preflight=bundle.data_preflight,
                benchmark=bundle.benchmark,
                seal=tampered,
            ),
            repository_root=REPOSITORY_ROOT,
        )

    rendered = json.dumps(
        {
            "feasibility": bundle.feasibility,
            "candidatePolicy": bundle.candidate_policy,
            "externalReferenceUniverse": bundle.external_reference_universe,
            "dataPreflight": bundle.data_preflight,
            "benchmark": bundle.benchmark.model_dump(
                mode="json",
                by_alias=True,
            ),
            "seal": bundle.seal.model_dump(mode="json", by_alias=True),
        },
        sort_keys=True,
    ).lower()
    assert '"value":' not in rendered
    assert '"score":' not in rendered
    assert "api_token" not in rendered
    assert "authorization" not in rendered
