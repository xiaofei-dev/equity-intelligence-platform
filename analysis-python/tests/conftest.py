from __future__ import annotations

import decimal
import platform
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
CONTROLLED_CACHE = REPOSITORY / "storage/historical-validation/yahoo-daily-price-cache-v1"
CONTROLLED_PREDICTORS = (
    REPOSITORY
    / "storage/fundamental-value-historical-validation-v1"
    / "stage7c5-provider-native/sealed-predictors.json"
)

# These tests replay licensed/private transport checkpoints or local evidence images. The
# public suite keeps every Git-safe contract, formula, tamper, and canonical-hash check, but
# cannot manufacture or publish the controlled inputs merely to make hosted CI pass.
CONTROLLED_CACHE_TESTS = {
    "test_fundamental_value_historical_company_quality_approximation_v1.py::test_actual_25_100_216_replay_is_value_free_and_bound",
    "test_fundamental_value_historical_company_quality_pilot_v1.py::test_actual_value_free_replay_is_mechanically_bound_to_checked_summary",
    "test_fundamental_value_historical_confirmation_v1.py::test_fresh_dates_and_policy_are_frozen_before_outcomes",
    "test_fundamental_value_historical_confirmation_v1.py::test_predictor_seal_is_outcome_blind_and_above_100",
    "test_fundamental_value_historical_confirmation_v1.py::test_c9_terminal_registry_and_result_are_complete_and_self_validating",
    "test_fundamental_value_historical_confirmation_v1.py::test_c9_full_replay_is_exact_under_hostile_outer_decimal_context",
    "test_fundamental_value_historical_confirmation_v1.py::test_post_closeout_summary_exactly_reproduces_immutable_final",
    "test_quant_trading_historical_result_v118.py::test_controlled_result_exact_artifact_hash_readback",
    "test_quant_trading_historical_result_v118.py::test_controlled_result_metrics_and_frozen_gate_evaluation_replay_exactly",
    "test_quant_trading_historical_runner_v11.py::test_controlled_c7_c9_loader_verifies_structure_without_numeric_decode",
    "test_quant_trading_historical_validation_v1.py::test_controlled_cache_is_structurally_ready_only_for_development_track",
    "test_quant_trading_historical_validation_v1.py::test_population_batches_are_deterministic_and_complete",
    "test_quant_trading_historical_validation_v1.py::test_identity_drift_fails_closed",
    "test_quant_trading_historical_validation_v1.py::test_optimized_real_formula_path_matches_the_strict_stage1_core",
    "test_quant_trading_historical_validation_v1.py::test_pilot_is_deterministic_and_keeps_unavailable_benchmarks_explicit",
    "test_quant_trading_historical_validation_v2.py::test_preoutcome_intent_binds_structural_sources_without_outcomes",
    "test_quant_trading_historical_validation_v2.py::test_run_identity_is_exclusive_before_outcome_access",
}
CONTROLLED_PREDICTOR_TESTS = {
    "test_fundamental_value_historical_outcome_execution_v1.py::test_plan_is_exact_203_and_aliases_are_collision_free",
    "test_fundamental_value_historical_outcome_execution_v1.py::test_plan_artifact_refuses_to_hide_missing_requests",
    "test_fundamental_value_historical_outcome_execution_v1.py::test_reuse_registry_binds_exact_adapter_range_and_request",
    "test_fundamental_value_historical_outcome_execution_v1.py::test_journal_binds_plan_request_chain_and_blocks_unknown",
    "test_fundamental_value_historical_outcome_execution_v1.py::test_journal_rejects_plan_drift_and_copied_request_event",
    "test_fundamental_value_historical_provider_native_company_quality_v1.py::test_controlled_predictor_checkpoint_matches_git_safe_coverage",
    "test_fundamental_value_historical_outcome_path_preflight_v1.py::test_blocked_preflight_cannot_claim_execution_or_stage8",
}
LOCAL_IMAGE_TESTS = {
    "test_fundamental_value_historical_quarterly_semantics_replay_v1.py::test_correct_support_source_is_visually_corroborated_and_approximation_only",
    "test_fundamental_value_historical_quarterly_semantics_replay_v1.py::test_actual_empirical_result_is_value_free_bound_and_stops_replay",
    "test_fundamental_value_historical_quarterly_semantics_support_v1.py::test_supplied_hash_is_bound_but_visual_quote_mismatch_blocks_read",
}
SEALED_RUNTIME_TEST = (
    "test_fundamental_value_historical_confirmation_v1.py::"
    "test_post_closeout_acceptance_is_self_authenticating"
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-controlled-artifacts",
        action="store_true",
        default=False,
        help="Fail instead of skipping when private controlled validation artifacts are absent.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "controlled_artifact: requires private or licensed validation evidence excluded from Git",
    )


def _matches(nodeid: str, identities: set[str]) -> bool:
    normalized = nodeid.removeprefix("tests/")
    return any(normalized.startswith(identity) for identity in identities)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    controlled_requested = config.getoption("--require-controlled-artifacts")
    missing_cache = not (
        CONTROLLED_CACHE / "stage7c7-outcome-execution-receipt.json"
    ).is_file()
    missing_predictors = not CONTROLLED_PREDICTORS.is_file()
    local_images_available = all(
        path.is_file()
        for path in (
            Path(
                "C:/Users/simon/AppData/Local/Temp/"
                "codex-clipboard-43e89aa3-b33a-4eac-916c-1e71b4490960.png"
            ),
            Path(
                "C:/Users/simon/AppData/Local/Temp/"
                "codex-clipboard-4bbaece8-9610-4759-b5f5-afe2ada80a0f.png"
            ),
        )
    )
    sealed_runtime_available = (
        sys.implementation.name,
        platform.python_version(),
        sys.implementation.cache_tag,
        decimal.__name__,
        decimal.__version__,
        decimal.__libmpdec_version__,
    ) == ("cpython", "3.14.2", "cpython-314", "decimal", "1.70", "4.0.0")
    missing: list[str] = []
    for item in items:
        unavailable = (
            (
                (not controlled_requested or missing_cache)
                and _matches(item.nodeid, CONTROLLED_CACHE_TESTS)
            )
            or (
                (not controlled_requested or missing_predictors)
                and _matches(item.nodeid, CONTROLLED_PREDICTOR_TESTS)
            )
            or (
                (not controlled_requested or not local_images_available)
                and _matches(item.nodeid, LOCAL_IMAGE_TESTS)
            )
            or (
                not sealed_runtime_available
                and _matches(item.nodeid, {SEALED_RUNTIME_TEST})
            )
        )
        if not unavailable:
            continue
        item.add_marker("controlled_artifact")
        missing.append(item.nodeid)
        item.add_marker(
            pytest.mark.skip(
                reason=(
                    "CONTROLLED_ARTIFACT_NOT_AVAILABLE: private validation evidence is "
                    "intentionally excluded from the public repository"
                )
            )
        )
    if controlled_requested and missing:
        raise pytest.UsageError(
            "Required controlled artifacts are unavailable for: " + ", ".join(missing)
        )
