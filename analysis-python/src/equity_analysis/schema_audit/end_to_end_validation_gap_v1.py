from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash

SCHEMA_VERSION = "END-TO-END-VALIDATION-COMPLETION-GAP-AUDIT-v1.0.0"
ARTIFACT_TYPE = "END_TO_END_VALIDATION_COMPLETION_GAP_AUDIT"

_PRICE_PREFLIGHT = Path(
    "docs/generated/future-price-history-final-preexecution-preflight-v2-1.json"
)
_BENCHMARK_CANDIDATES = Path("docs/generated/forward-benchmark-candidate-construction-v2-2.json")
_MODEL_PREFLIGHT = Path("docs/generated/post-freeze-model-execution-v2-2-preflight-v2.json")
_SNAPSHOT_FIXTURE = Path("docs/generated/post-freeze-decision-snapshot-v2-2-contract-fixture.json")
_READINESS = Path("docs/generated/forward-v2-2-final-successor-readiness-closeout-v2.json")
_ENROLLMENT_PREFLIGHT = Path("docs/generated/prospective-enrollment-adapter-v2-2-preflight.json")
_V18_ACCEPTANCE = Path("docs/generated/forward-dqv-v18-acceptance-v1.json")
_HISTORICAL_CLOSEOUT = Path("docs/generated/historical-dqv-v2-2-slice-diagnostic-closeout.json")
_PROTOCOL_FIXTURE = Path(
    "docs/generated/forward-decision-quality-validation-v2-2-protocol-fixture.json"
)
_POST_CLOSE_PREFLIGHT = Path(
    "docs/generated/post-close-pipeline-orchestrator-v2-2-preflight-v3.json"
)
_V19_ACCEPTANCE = Path("docs/generated/forward-dqv-v19-chronology-acceptance-v1.json")
_MATURITY_ACCEPTANCE = Path("docs/generated/forward-dqv-maturity-engine-v2-2-acceptance.json")
_STATISTICS_PREFLIGHT = Path("docs/generated/forward-dqv-v2-2-statistical-engine-preflight.json")
_MATURITY_STATISTICS_ADAPTER_PREFLIGHT = Path(
    "docs/generated/forward-dqv-maturity-statistics-adapter-v2-2-preflight.json"
)


class EndToEndValidationGapAuditError(ValueError):
    pass


def _read_json(repository_root: Path, relative_path: Path) -> dict[str, Any]:
    path = repository_root / relative_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EndToEndValidationGapAuditError(
            f"{relative_path.as_posix()} must contain a JSON object"
        )
    return payload


def _verified_artifact(
    repository_root: Path,
    relative_path: Path,
) -> tuple[dict[str, Any], dict[str, str]]:
    path = repository_root / relative_path
    payload = _read_json(repository_root, relative_path)
    claim = payload.get("artifactContentHash")
    if not isinstance(claim, str):
        raise EndToEndValidationGapAuditError(
            f"{relative_path.as_posix()} has no artifactContentHash"
        )
    body = dict(payload)
    body.pop("artifactContentHash")
    if canonical_hash(body) != claim:
        raise EndToEndValidationGapAuditError(
            f"{relative_path.as_posix()} has an invalid canonical hash"
        )
    return payload, {
        "path": relative_path.as_posix(),
        "artifactContentHash": claim,
        "fileSha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _source_binding(
    repository_root: Path,
    relative_path: str,
    symbols: tuple[str, ...],
) -> dict[str, Any]:
    path = repository_root / relative_path
    text = path.read_text(encoding="utf-8")
    missing = tuple(symbol for symbol in symbols if symbol not in text)
    if missing:
        raise EndToEndValidationGapAuditError(
            f"{relative_path} is missing required markers: {missing}"
        )
    return {
        "path": relative_path,
        "fileSha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        "verifiedMarkers": list(symbols),
    }


def _require_absent(repository_root: Path, relative_path: str) -> None:
    if (repository_root / relative_path).exists():
        raise EndToEndValidationGapAuditError(
            f"Expected current-state gap is no longer true: {relative_path} exists"
        )


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise EndToEndValidationGapAuditError(
            f"{label} changed: expected {expected!r}, found {actual!r}"
        )


def build_end_to_end_validation_gap_audit(
    repository_root: Path,
) -> dict[str, Any]:
    price, price_binding = _verified_artifact(repository_root, _PRICE_PREFLIGHT)
    candidates, candidate_binding = _verified_artifact(
        repository_root,
        _BENCHMARK_CANDIDATES,
    )
    model, model_binding = _verified_artifact(repository_root, _MODEL_PREFLIGHT)
    fixture, fixture_binding = _verified_artifact(
        repository_root,
        _SNAPSHOT_FIXTURE,
    )
    readiness, readiness_binding = _verified_artifact(
        repository_root,
        _READINESS,
    )
    enrollment, enrollment_binding = _verified_artifact(
        repository_root,
        _ENROLLMENT_PREFLIGHT,
    )
    v18, v18_binding = _verified_artifact(repository_root, _V18_ACCEPTANCE)
    historical, historical_binding = _verified_artifact(
        repository_root,
        _HISTORICAL_CLOSEOUT,
    )
    protocol, protocol_binding = _verified_artifact(
        repository_root,
        _PROTOCOL_FIXTURE,
    )
    post_close, post_close_binding = _verified_artifact(
        repository_root,
        _POST_CLOSE_PREFLIGHT,
    )
    if (repository_root / _V19_ACCEPTANCE).exists():
        v19, v19_binding = _verified_artifact(repository_root, _V19_ACCEPTANCE)
    else:
        v19 = None
        v19_binding = {
            "path": _V19_ACCEPTANCE.as_posix(),
            "status": "MISSING_FORMAL_ACCEPTANCE",
        }
    maturity, maturity_binding = _verified_artifact(
        repository_root,
        _MATURITY_ACCEPTANCE,
    )
    statistics, statistics_binding = _verified_artifact(
        repository_root,
        _STATISTICS_PREFLIGHT,
    )
    maturity_adapter, maturity_adapter_binding = _verified_artifact(
        repository_root,
        _MATURITY_STATISTICS_ADAPTER_PREFLIGHT,
    )

    _require_equal(
        price.get("status"),
        "BLOCKED_AWAITING_TARGET_SESSION_COMPLETION",
        "Future price preflight status",
    )
    _require_equal(
        candidates.get("fullBenchmarkConstructionStatus"),
        "PRICE_LIQUIDITY_COST_AND_EXTERNAL_REFERENCE_EVIDENCE_PENDING",
        "Benchmark construction status",
    )
    _require_equal(model.get("status"), "BLOCKED", "Model preflight status")
    _require_equal(
        set(model.get("blockers") or ()),
        {
            "COMPLETED_SESSION_PRICE_EVIDENCE_MISSING",
            "MODEL_INPUT_EVIDENCE_MISSING",
        },
        "Model preflight blockers",
    )
    _require_equal(
        fixture.get("purpose"),
        "CONTRACT_FIXTURE",
        "Decision snapshot purpose",
    )
    _require_equal(readiness.get("status"), "BLOCKED", "Readiness status")
    _require_equal(enrollment.get("status"), "BLOCKED", "Enrollment status")
    _require_equal(v18.get("status"), "READY", "V18 implementation status")
    _require_equal(
        v18.get("enrollmentStatus"),
        "NOT_EXECUTED",
        "V18 enrollment status",
    )
    _require_equal(
        historical.get("terminalStatus"),
        "CLOSED_WITHOUT_MODEL_VALIDATION",
        "Historical diagnostic terminal status",
    )
    _require_equal(
        protocol.get("purpose"),
        "CONTRACT_FIXTURE",
        "Evaluation protocol purpose",
    )
    _require_equal(post_close.get("status"), "BLOCKED", "Post-close preflight status")
    _require_equal(
        set(post_close.get("blockedReasons") or ()),
        {
            "PRODUCTION_66_MODEL_INPUT_EVIDENCE_MISSING",
            "TARGET_SESSION_NOT_COMPLETED",
        },
        "Post-close preflight blockers",
    )
    if v19 is not None:
        _require_equal(v19.get("status"), "READY", "V19 chronology acceptance status")
        _require_equal(
            v19.get("acceptedEnrollmentContract"),
            "FORWARD-DQV-ENROLLMENT-v2.1.1",
            "V19 accepted enrollment contract",
        )
        _require_equal(
            v19.get("rejectedEnrollmentContract"),
            "FORWARD-DQV-ENROLLMENT-v2.1.0",
            "V19 rejected enrollment contract",
        )
    _require_equal(
        maturity.get("status"),
        "OFFLINE_ENGINE_READY",
        "Maturity engine acceptance status",
    )
    _require_equal(
        maturity.get("realExecutionStatus"),
        "BLOCKED_NO_ENROLLMENT",
        "Maturity engine real execution status",
    )
    _require_equal(statistics.get("status"), "BLOCKED", "Statistics preflight status")
    _require_equal(
        maturity_adapter.get("status"),
        "BLOCKED",
        "Maturity statistics adapter preflight status",
    )

    _require_absent(
        repository_root,
        "docs/generated/future-completed-session-price-evidence-v2-2.json",
    )
    _require_absent(
        repository_root,
        "docs/generated/post-freeze-model-input-evidence-v2-2.json",
    )
    _require_absent(
        repository_root,
        "docs/generated/forward-benchmark-manifest-v2-2.json",
    )
    _require_absent(
        repository_root,
        "docs/generated/post-freeze-decision-snapshot-v2-2.json",
    )

    sources = {
        "tacticalModel": _source_binding(
            repository_root,
            "analysis-python/src/equity_analysis/tactical/signal_v22.py",
            ("evaluate_tactical_signal_v22", "_entry_action", "_horizon_assessment"),
        ),
        "longHorizonModel": _source_binding(
            repository_root,
            "analysis-python/src/equity_analysis/research_rating/long_horizon_v11.py",
            (
                "_business_quality",
                "_valuation_entry",
                "_downside_risk",
                "_expected_return",
                "evaluate_long_horizon_v11",
            ),
        ),
        "modelExecution": _source_binding(
            repository_root,
            (
                "analysis-python/src/equity_analysis/forward_validation/"
                "post_freeze_model_execution_v22.py"
            ),
            (
                "SecurityModelExecutionInputV22",
                "execute_post_freeze_model_rows_v22",
                "MODEL_INPUT_EVIDENCE_PATH",
            ),
        ),
        "modelInputAssembly": _source_binding(
            repository_root,
            (
                "analysis-python/src/equity_analysis/forward_validation/"
                "post_close_model_input_assembly_v22.py"
            ),
            (
                "PostCloseModelInputAssemblyV22",
                "assemble_post_close_model_inputs_v22",
                "exact frozen 66 model input rows",
            ),
        ),
        "decisionSnapshot": _source_binding(
            repository_root,
            (
                "analysis-python/src/equity_analysis/forward_validation/"
                "post_freeze_decision_snapshot_v22.py"
            ),
            (
                "PostFreezeDecisionSnapshotV22",
                "AiNarrativeBoundaryV22",
                "result_hash",
                "scores_or_ranks_computed",
            ),
        ),
        "benchmarkConstruction": _source_binding(
            repository_root,
            (
                "analysis-python/src/equity_analysis/forward_validation/"
                "benchmark_construction_v22.py"
            ),
            (
                "build_benchmark_evidence_bundle_v22",
                "EXACT_SIX_BENCHMARK_KINDS_REQUIRED",
            ),
        ),
        "enrollmentAdapter": _source_binding(
            repository_root,
            (
                "analysis-python/src/equity_analysis/forward_validation/"
                "prospective_enrollment_adapter_v22.py"
            ),
            (
                "prepare_prospective_enrollment_v22",
                "persist_prepared_enrollment_v22",
                "ForwardDqvEnrollmentV211",
                "V19_CHRONOLOGY_ACCEPTANCE_MISSING",
            ),
        ),
        "legacyOutcomeContracts": _source_binding(
            repository_root,
            ("analysis-python/src/equity_analysis/forward_validation/outcomes_v21.py"),
            (
                "ForwardOutcomeBatchV21",
                "ForwardQualityReportV21",
                "PathMetricV21",
            ),
        ),
        "legacyOutcomePersistence": _source_binding(
            repository_root,
            ("analysis-python/src/equity_analysis/forward_validation/outcome_persistence_v21.py"),
            (
                "persist_enrollment",
                "persist_outcome_batch",
                "persist_quality_report",
            ),
        ),
        "outcomeContractsV211": _source_binding(
            repository_root,
            ("analysis-python/src/equity_analysis/forward_validation/outcomes_v211.py"),
            (
                "ForwardDqvEnrollmentV211",
                "FORWARD-DQV-ENROLLMENT-v2.1.1",
                "verify_enrollment_v211",
            ),
        ),
        "outcomePersistenceV211": _source_binding(
            repository_root,
            ("analysis-python/src/equity_analysis/forward_validation/outcome_persistence_v211.py"),
            (
                "ForwardDqvOutcomeRepositoryV211",
                "persist_enrollment",
                "verify_enrollment_v211",
            ),
        ),
        "v18Migration": _source_binding(
            repository_root,
            "database/migrations/V18__create_forward_dqv_v2_outcome_ledger.sql",
            (
                "analytics.forward_dqv_enrollment_v2",
                "analytics.forward_dqv_maturity_schedule_v2",
                "analytics.forward_dqv_quality_report_v2",
                "effective_at_completed_session_open <= sealed_at",
            ),
        ),
        "v19Migration": _source_binding(
            repository_root,
            "database/migrations/V19__repair_forward_dqv_enrollment_chronology.sql",
            (
                "FORWARD-DQV-ENROLLMENT-v2.1.1",
                "decision_as_of <= sealed_at",
                "sealed_at <= effective_at_completed_session_open",
            ),
        ),
        "v19AcceptanceBuilder": _source_binding(
            repository_root,
            ("analysis-python/src/equity_analysis/forward_validation/v19_acceptance_v1.py"),
            (
                "FORWARD_DQV_V19_CHRONOLOGY_ACCEPTANCE",
                "acceptedEnrollmentContract",
                "rejectedEnrollmentContract",
            ),
        ),
        "postCloseOrchestrator": _source_binding(
            repository_root,
            (
                "analysis-python/src/equity_analysis/forward_validation/"
                "post_close_pipeline_orchestrator_v22.py"
            ),
            (
                "run_post_close_pipeline_v22",
                "evaluate_successor_readiness_v221",
                "ENROLLMENT_CHRONOLOGY_V19_ACCEPTANCE_MISSING",
            ),
        ),
        "legacyRouteGuard": _source_binding(
            repository_root,
            "analysis-python/src/equity_analysis/forward_validation/routes.py",
            (
                "LEGACY_PROSPECTIVE_ENROLLMENT_DISABLED",
                "controlled Forward DQV v2.1.1 enrollment workflow",
            ),
        ),
        "evaluationProtocol": _source_binding(
            repository_root,
            (
                "analysis-python/src/equity_analysis/forward_validation/"
                "dqv_evaluation_protocol_v22.py"
            ),
            (
                "DETERMINISTIC_CIRCULAR_BLOCK_BOOTSTRAP",
                "HOLM_BONFERRONI",
                "BUSINESS_QUALITY",
                "SECURITY_ATTRACTIVENESS",
                "DOWNSIDE_RISK",
            ),
        ),
        "maturityOutcomeEngine": _source_binding(
            repository_root,
            (
                "analysis-python/src/equity_analysis/forward_validation/"
                "maturity_outcome_engine_v22.py"
            ),
            (
                "evaluate_maturity",
                "Exactly six benchmark paths are required",
                "MAXIMUM_ADVERSE_EXCURSION",
                "MAXIMUM_FAVORABLE_EXCURSION",
                "DOWNSIDE_CAPTURE",
            ),
        ),
        "statisticsContracts": _source_binding(
            repository_root,
            (
                "analysis-python/src/equity_analysis/forward_validation/"
                "dqv_statistics_contracts_v22.py"
            ),
            (
                "MaturedDecisionObservationV22",
                "AiProvenance",
                "HumanProvenance",
                "expected_return_low",
                "timing_category",
            ),
        ),
        "statisticsEngine": _source_binding(
            repository_root,
            ("analysis-python/src/equity_analysis/forward_validation/dqv_statistics_engine_v22.py"),
            (
                "evaluate_forward_dqv_v22",
                "_bootstrap_interval",
                "_apply_holm",
                "_strata_reports",
                "_expected_return_calibration",
                "_tactical_timing_reports",
            ),
        ),
        "maturityStatisticsAdapter": _source_binding(
            repository_root,
            (
                "analysis-python/src/equity_analysis/forward_validation/"
                "maturity_statistics_adapter_v22.py"
            ),
            (
                "adapt_maturity_to_statistics_v22",
                "FROZEN_POPULATION_NOT_66",
                "CONTRACT_FIXTURE_CANNOT_FEED_STATISTICS",
                "ai_may_affect_deterministic_result",
                "human_may_affect_deterministic_result",
            ),
        ),
    }

    artifacts = {
        "futurePricePreflight": price_binding,
        "benchmarkCandidates": candidate_binding,
        "modelExecutionPreflight": model_binding,
        "decisionContractFixture": fixture_binding,
        "successorReadiness": readiness_binding,
        "enrollmentPreflight": enrollment_binding,
        "v18Acceptance": v18_binding,
        "historicalDiagnosticCloseout": historical_binding,
        "evaluationProtocolFixture": protocol_binding,
        "postClosePipelinePreflight": post_close_binding,
        "v19ChronologyAcceptance": v19_binding,
        "maturityEngineAcceptance": maturity_binding,
        "statisticsEnginePreflight": statistics_binding,
        "maturityStatisticsAdapterPreflight": maturity_adapter_binding,
    }
    v19_accepted = v19 is not None

    requirements: list[dict[str, Any]] = [
        {
            "id": "GOVERNANCE_HISTORICAL_CLAIM_BOUNDARY",
            "status": "IMPLEMENTED_OFFLINE",
            "scope": "IMPLEMENTATION_AND_REPOSITORY_CURRENT_ARTIFACT",
            "finding": (
                "Observed historical slices are reproducibly closed as "
                "DIAGNOSTIC_ONLY and are not represented as an untouched holdout."
            ),
            "evidence": [
                "historicalDiagnosticCloseout",
                "evaluationProtocolFixture",
            ],
            "remaining": [],
        },
        {
            "id": "TACTICAL_1W_1M_3M_MODEL_CAPABILITY",
            "status": "IMPLEMENTED_OFFLINE",
            "scope": "DETERMINISTIC_IMPLEMENTATION_ONLY",
            "finding": (
                "Tactical v2.2 implements three independent horizons and entry "
                "actions, but no real post-freeze row has been produced."
            ),
            "evidence": ["tacticalModel", "modelExecution"],
            "remaining": [
                "Build real completed-session inputs and execute the frozen model.",
                "Persist the decision payload required for later timing evaluation.",
            ],
        },
        {
            "id": "LONG_12M_QUALITY_VALUATION_EXPECTED_RETURN_DOWNSIDE",
            "status": "IMPLEMENTED_OFFLINE",
            "scope": "DETERMINISTIC_IMPLEMENTATION_ONLY",
            "finding": (
                "Long Horizon v1.1 implements separate quality, valuation-entry, "
                "expected-return and downside dimensions; no prospective assessment "
                "has been produced or validated."
            ),
            "evidence": ["longHorizonModel", "modelExecution"],
            "remaining": [
                "Build real point-in-time Long Horizon inputs.",
                "Execute and preserve the full deterministic assessment.",
            ],
        },
        {
            "id": "GOOD_COMPANY_VS_ATTRACTIVE_SECURITY_SEPARATION",
            "status": "IMPLEMENTED_OFFLINE",
            "scope": "CONTRACT_ONLY",
            "finding": (
                "The protocol and statistics engine evaluate BUSINESS_QUALITY, "
                "SECURITY_ATTRACTIVENESS and DOWNSIDE_RISK separately. Real frozen "
                "per-security values are not yet available."
            ),
            "evidence": ["longHorizonModel", "decisionSnapshot", "evaluationProtocol"],
            "remaining": [
                "Persist immutable target-specific output payloads and rank inputs.",
                "Bind those payloads into enrollment and quality-report evidence.",
            ],
        },
        {
            "id": "MISSING_AI_HUMAN_AND_EVIDENCE_ROLE_SEPARATION",
            "status": "IMPLEMENTED_OFFLINE",
            "scope": "OFFLINE_TYPED_CONTRACT_AND_ADAPTER",
            "finding": (
                "Missing terminal states, historical claim ceilings, AI provenance "
                "and human provenance are typed. The adapter forbids either AI or "
                "human review from changing deterministic results."
            ),
            "evidence": [
                "decisionSnapshot",
                "evaluationProtocol",
                "historicalDiagnosticCloseout",
                "statisticsContracts",
                "maturityStatisticsAdapter",
            ],
            "remaining": [
                "Populate the typed provenance only from real immutable decision evidence.",
                "Analyze AI and human provenance as descriptive strata only.",
            ],
        },
        {
            "id": "POST_CLOSE_COMPLETED_SESSION_CAPTURE",
            "status": "BLOCKED_BY_TIME",
            "scope": "REAL_EXECUTION",
            "finding": (
                "The bounded capture runner is implemented, but the authoritative "
                "preflight is awaiting the target session and no real completed-session "
                "evidence artifact exists."
            ),
            "evidence": ["futurePricePreflight"],
            "remaining": [
                "Wait for the target session to complete.",
                "Execute the bounded 67-price plus two-calendar capture once.",
                "Verify adjustment, action, liquidity and source hashes.",
            ],
        },
        {
            "id": "POST_FREEZE_66_MODEL_INPUT_ADAPTER",
            "status": "BLOCKED_BY_EVIDENCE",
            "scope": "PRODUCTION_IMPLEMENTATION",
            "finding": (
                "The strict stored-evidence assembler for the exact frozen 66 now "
                "exists, but the authoritative post-close preflight has no real "
                "66-member input artifact and therefore cannot prove production use."
            ),
            "evidence": [
                "modelInputAssembly",
                "modelExecution",
                "modelExecutionPreflight",
                "postClosePipelinePreflight",
            ],
            "remaining": [
                "Run the assembler only after the completed-session evidence exists.",
                "Write the immutable post-freeze model-input evidence artifact.",
            ],
        },
        {
            "id": "SIX_BENCHMARK_CONSTRUCTION",
            "status": "BLOCKED_BY_EVIDENCE",
            "scope": "REAL_EXECUTION",
            "finding": (
                "The construction contract exists and Value/Quality candidates are "
                "frozen, but price, liquidity, cost and external-reference evidence "
                "remain pending and no real six-AVAILABLE manifest exists."
            ),
            "evidence": [
                "benchmarkConstruction",
                "benchmarkCandidates",
                "successorReadiness",
            ],
            "remaining": [
                "Construct SPY, sector, equal-weight, momentum, value and quality "
                "from one completed session and one cost policy.",
                "Persist the real v2.2 benchmark manifest and controlled bundle.",
            ],
        },
        {
            "id": "REAL_POST_FREEZE_MODEL_EXECUTION",
            "status": "NOT_EXECUTED",
            "scope": "REAL_EXECUTION",
            "finding": (
                "The authoritative model preflight generated zero rows and identifies "
                "both completed-session and model-input evidence as missing."
            ),
            "evidence": ["modelExecutionPreflight", "modelExecution"],
            "remaining": [
                "Close the price and input-adapter blockers.",
                "Execute Tactical v2.2 and Long Horizon v1.1 exactly once per frozen row.",
            ],
        },
        {
            "id": "IMMUTABLE_DECISION_OUTPUT_PAYLOAD",
            "status": "BLOCKED_BY_EVIDENCE",
            "scope": "PRODUCTION_CONTRACT",
            "finding": (
                "Assessed terminal rows store input/result hashes but not Tactical "
                "scores, entry actions, Long Horizon dimensions, classifications or "
                "expected-return ranges. Re-running a model later is not an immutable "
                "substitute for the enrolled prediction."
            ),
            "evidence": ["decisionSnapshot", "modelExecution"],
            "remaining": [
                "Store a content-addressed controlled deterministic output payload.",
                "Bind per-horizon and per-target values to the Git-safe decision manifest.",
                "Replace the ambiguous scoresOrRanksComputed=false claim for real execution.",
            ],
        },
        {
            "id": "REAL_66_PROSPECTIVE_DECISION_SNAPSHOT",
            "status": "NOT_EXECUTED",
            "scope": "REAL_EXECUTION",
            "finding": (
                "Only a CONTRACT_FIXTURE exists; it is blocked and contains no real "
                "model results or six available benchmarks."
            ),
            "evidence": ["decisionContractFixture", "successorReadiness"],
            "remaining": [
                "Assemble a PROSPECTIVE_DECISION snapshot after real model execution.",
                "Preserve all 66 assessed, missing, stale, invalid, excluded and abstained rows.",
            ],
        },
        {
            "id": "ENROLLMENT_CHRONOLOGY_LEAKAGE_GUARD",
            "status": "IMPLEMENTED_OFFLINE" if v19_accepted else "BLOCKED_BY_EVIDENCE",
            "scope": (
                "ACCEPTED_IMPLEMENTATION_AND_DATABASE_CONSTRAINT"
                if v19_accepted
                else "STAGED_SUCCESSOR_AWAITING_FORMAL_ACCEPTANCE"
            ),
            "finding": (
                (
                    "The former V18/v2.1.0 chronology is preserved as immutable history. "
                    "V19/v2.1.1 enforces decisionAsOf <= sealedAt <= entryOpen, rejects "
                    "v2.1.0 writes, and has an immutable READY acceptance artifact."
                )
                if v19_accepted
                else (
                    "The former V18/v2.1.0 chronology is preserved as immutable history. "
                    "A corrected V19/v2.1.1 migration, model, repository, adapter and "
                    "legacy-route guard are staged, but the formal V19 acceptance "
                    "artifact is not yet present."
                )
            ),
            "evidence": [
                "v18Migration",
                "v19Migration",
                "outcomeContractsV211",
                "outcomePersistenceV211",
                "enrollmentAdapter",
                "v19AcceptanceBuilder",
                "v19ChronologyAcceptance",
                "legacyRouteGuard",
            ],
            "remaining": [
                *(
                    []
                    if v19_accepted
                    else [
                        "Run PostgreSQL V1-to-V19 and V18-to-V19 acceptance.",
                        "Generate and verify the immutable V19 chronology acceptance artifact.",
                    ]
                ),
                "Regenerate all dependent readiness and enrollment preflights and hashes.",
                "Keep legacy v2.1.0 source and artifacts read-only historical evidence.",
            ],
        },
        {
            "id": "V18_OUTCOME_LEDGER_AND_PERSISTENCE",
            "status": "IMPLEMENTED_OFFLINE",
            "scope": "LEGACY_SCHEMA_AND_REPOSITORY_HISTORY_ONLY",
            "finding": (
                "Seven V18 tables and v2.1 enrollment/outcome/report persistence exist "
                "and passed repository acceptance. Enrollment was not executed. The "
                "v2.1.0 enrollment writer is superseded and must remain unreachable "
                "from production after V19 acceptance."
            ),
            "evidence": [
                "v18Acceptance",
                "v18Migration",
                "legacyOutcomeContracts",
                "legacyOutcomePersistence",
            ],
            "remaining": [
                "Preserve v2.1.0 as immutable history, not a production write path.",
            ],
        },
        {
            "id": "V19_V2_1_1_PRODUCTION_REACHABILITY",
            "status": "IMPLEMENTED_OFFLINE" if v19_accepted else "BLOCKED_BY_EVIDENCE",
            "scope": (
                "ACCEPTED_PRODUCTION_WRITE_BOUNDARY"
                if v19_accepted
                else "IMPLEMENTED_AWAITING_FORMAL_ACCEPTANCE"
            ),
            "finding": (
                "V19 restricts the database to v2.1.1, the v2.1.1 repository overrides "
                "enrollment persistence, the adapter creates v2.1.1, and the legacy "
                "HTTP writer returns 410. "
                + (
                    "The immutable V19 acceptance confirms clean and upgrade database "
                    "paths. The v2.1.0 implementation remains historical only."
                    if v19_accepted
                    else "Formal database and production-reachability acceptance is pending."
                )
            ),
            "evidence": [
                "v19Migration",
                "outcomeContractsV211",
                "outcomePersistenceV211",
                "enrollmentAdapter",
                "legacyRouteGuard",
                "v19ChronologyAcceptance",
            ],
            "remaining": [
                *(
                    []
                    if v19_accepted
                    else ["Complete the formal V19 acceptance and reachability proof."]
                ),
                "Keep future production wiring constrained to v2.1.1 or a stricter successor.",
            ],
        },
        {
            "id": "POST_V19_DEPENDENT_ARTIFACT_REGENERATION",
            "status": "IMPLEMENTED_OFFLINE" if v19_accepted else "BLOCKED_BY_EVIDENCE",
            "scope": "CURRENT_ARTIFACT_GRAPH",
            "finding": (
                (
                    "The versioned post-close v3 preflight binds the READY V19 "
                    "acceptance hash and no longer reports a chronology blocker."
                    if v19_accepted
                    else (
                        "The current post-close preflight correctly records "
                        "ENROLLMENT_CHRONOLOGY_V19_ACCEPTANCE_MISSING."
                    )
                )
                + " It is safe because it blocks execution and cannot authorize enrollment."
            ),
            "evidence": [
                "v19ChronologyAcceptance",
                "postClosePipelinePreflight",
                "enrollmentPreflight",
                "successorReadiness",
            ],
            "remaining": [
                *(
                    []
                    if v19_accepted
                    else [
                        "Regenerate versioned successor readiness and enrollment preflights.",
                        "Bind the accepted V19 artifact hash without overwriting history.",
                    ]
                ),
            ],
        },
        {
            "id": "REAL_V2_2_PROSPECTIVE_ENROLLMENT",
            "status": "NOT_EXECUTED",
            "scope": "REAL_EXECUTION",
            "finding": (
                "The adapter preflight is BLOCKED, enrollmentStatus is NOT_EXECUTED, "
                "and the available CLI only writes a blocked fixture preflight."
            ),
            "evidence": [
                "enrollmentPreflight",
                "v18Acceptance",
                "enrollmentAdapter",
                "postCloseOrchestrator",
            ],
            "remaining": [
                "Close the V19, price, benchmark, output-payload and snapshot blockers.",
                "Accept and bind the v2.1.1 production repository.",
                "Execute only through the explicitly authorized bounded orchestrator path.",
            ],
        },
        {
            "id": "REPEATED_PROSPECTIVE_COHORT_ACCUMULATION",
            "status": "NOT_EXECUTED",
            "scope": "PRODUCTION_ORCHESTRATION",
            "finding": (
                "Formal gates require at least 100 eligible decisions and two distinct "
                "decision dates, while one snapshot has at most 55 candidate securities. "
                "No repeated post-freeze enrollment scheduler/controller is implemented."
            ),
            "evidence": ["evaluationProtocolFixture", "decisionContractFixture"],
            "remaining": [
                "Implement idempotent repeated decision-date enrollment.",
                "Freeze cohort accumulation and overlap/purge/embargo accounting.",
            ],
        },
        {
            "id": "MATURED_OUTCOME_AND_PATH_METRIC_EVALUATOR",
            "status": "IMPLEMENTED_OFFLINE",
            "scope": "OFFLINE_DETERMINISTIC_ENGINE",
            "finding": (
                "Gate H implements all five horizons, exact six benchmarks, gross/"
                "frozen-cost/net returns, MAE, MFE, drawdown, typed downside capture "
                "and hash-rooted evidence. No real enrollment has matured."
            ),
            "evidence": ["maturityOutcomeEngine", "maturityEngineAcceptance"],
            "remaining": [
                "Implement natural-maturity discovery and completed-session path loading.",
                "Execute only after a real v2.1.1 enrollment matures naturally.",
            ],
        },
        {
            "id": "REAL_NATURALLY_MATURED_OUTCOMES",
            "status": "BLOCKED_BY_TIME",
            "scope": "REAL_PROSPECTIVE_EXECUTION",
            "finding": (
                "No v2.1.1 enrollment exists, so none of the 5, 20, 60, 126 or "
                "252 completed-session outcomes can have matured or been observed."
            ),
            "evidence": [
                "maturityEngineAcceptance",
                "maturityStatisticsAdapterPreflight",
            ],
            "remaining": [
                "Enroll real prospective snapshots on at least two decision dates.",
                "Wait for every preregistered horizon to mature naturally.",
            ],
        },
        {
            "id": "REALISTIC_COST_AND_RISK_EVALUATION",
            "status": "IMPLEMENTED_OFFLINE",
            "scope": "OFFLINE_DETERMINISTIC_ENGINE",
            "finding": (
                "Gate H applies the frozen liquidity-sensitive cost policy and computes "
                "gross/cost/net plus required path risk with leakage and source-hash "
                "guards. No real matured cohort has been evaluated."
            ),
            "evidence": [
                "benchmarkConstruction",
                "legacyOutcomeContracts",
                "evaluationProtocol",
            ],
            "remaining": [
                "Execute against immutable adjusted price evidence after natural maturity.",
            ],
        },
        {
            "id": "TACTICAL_ENTRY_TIMING_VALIDATION",
            "status": "IMPLEMENTED_OFFLINE",
            "scope": "OFFLINE_STATISTICS_PROTOCOL_AND_ENGINE",
            "finding": (
                "The final protocol, adapter and statistics engine preserve frozen "
                "opportunity score, setup thesis and actionability, report abstention, "
                "and evaluate preregistered timing/thesis strata without retuning."
            ),
            "evidence": [
                "tacticalModel",
                "evaluationProtocol",
                "statisticsEngine",
                "maturityStatisticsAdapter",
            ],
            "remaining": [
                "Execute only after naturally matured prospective observations exist.",
            ],
        },
        {
            "id": "LONG_EXPECTED_RETURN_CALIBRATION",
            "status": "IMPLEMENTED_OFFLINE",
            "scope": "OFFLINE_STATISTICS_PROTOCOL_AND_ENGINE",
            "finding": (
                "The adapter preserves frozen low/base/high values and the statistics "
                "engine computes prospective bias, absolute error, empirical range "
                "coverage and calibration slope. The range is not a probability interval."
            ),
            "evidence": [
                "longHorizonModel",
                "evaluationProtocol",
                "statisticsEngine",
                "maturityStatisticsAdapter",
            ],
            "remaining": [
                "Execute only at the formal 252-session prospective horizon.",
            ],
        },
        {
            "id": "DQV_STATISTICS_AND_FINAL_QUALITY_REPORT",
            "status": "IMPLEMENTED_OFFLINE",
            "scope": "OFFLINE_DETERMINISTIC_ENGINE",
            "finding": (
                "The offline engine implements deterministic circular block bootstrap, "
                "null-centered one-sided inference, Holm families, sector/size strata, "
                "target-specific terminal rules, timing, calibration and provenance."
            ),
            "evidence": [
                "evaluationProtocol",
                "statisticsContracts",
                "statisticsEngine",
                "statisticsEnginePreflight",
            ],
            "remaining": [
                "Supply 100 eligible naturally matured decisions across at least two dates.",
                "Execute and persist a real versioned quality report.",
            ],
        },
        {
            "id": "MATURITY_TO_STATISTICS_ADAPTER",
            "status": "IMPLEMENTED_OFFLINE",
            "scope": "OFFLINE_HASH_BOUND_ADAPTER",
            "finding": (
                "The adapter requires an exact 66-security join and binds enrollment, "
                "decision snapshot, per-security frozen outputs, maturity batch, session "
                "index, benchmarks, liquidity, AI and human provenance. It rejects "
                "contract fixtures and silent imputation."
            ),
            "evidence": [
                "maturityStatisticsAdapter",
                "maturityStatisticsAdapterPreflight",
            ],
            "remaining": [
                "Provide real frozen decisions, enrollment, matured Gate H evidence and "
                "hash-bound decision-session index evidence.",
            ],
        },
        {
            "id": "REAL_DQV_STATISTICS_EXECUTION",
            "status": "NOT_EXECUTED",
            "scope": "REAL_PROSPECTIVE_EXECUTION",
            "finding": (
                "The statistics and adapter preflights report zero prospective "
                "observations and no executed statistics or quality report."
            ),
            "evidence": [
                "statisticsEnginePreflight",
                "maturityStatisticsAdapterPreflight",
            ],
            "remaining": [
                "Close frozen-output and natural-maturity evidence blockers.",
                "Run the engine without threshold or grouping changes.",
            ],
        },
        {
            "id": "FINAL_PROSPECTIVE_MODEL_VALIDATION",
            "status": "NOT_VALIDATED",
            "scope": "GOAL_COMPLETION",
            "finding": (
                "No prospective enrollment, matured outcome or quality report exists. "
                "Neither model is currently validated; NOT_VALIDATED remains an allowed "
                "future conclusion."
            ),
            "evidence": [
                "successorReadiness",
                "enrollmentPreflight",
                "evaluationProtocolFixture",
            ],
            "remaining": [
                "Close every upstream code and evidence gap.",
                "Accumulate naturally matured prospective evidence.",
                "Issue an honest terminal result without optimizing for favorability.",
            ],
        },
    ]

    critical_findings = [
        {
            "id": "GATE-Z-002",
            "severity": "CRITICAL",
            "title": "Enrolled decision contract does not preserve deterministic outputs",
            "requirementId": "IMMUTABLE_DECISION_OUTPUT_PAYLOAD",
        },
        {
            "id": "GATE-Z-003",
            "severity": "CRITICAL",
            "title": "No real prospective enrollment, matured outcome or quality report",
            "requirementId": "FINAL_PROSPECTIVE_MODEL_VALIDATION",
        },
        {
            "id": "GATE-Z-004",
            "severity": "HIGH",
            "title": "The 66-input assembler has no real immutable execution artifact",
            "requirementId": "POST_FREEZE_66_MODEL_INPUT_ADAPTER",
        },
        {
            "id": "GATE-Z-005",
            "severity": "HIGH",
            "title": "No repeated enrollment mechanism can reach the minimum cohort",
            "requirementId": "REPEATED_PROSPECTIVE_COHORT_ACCUMULATION",
        },
        {
            "id": "GATE-Z-006",
            "severity": "HIGH",
            "title": "Natural-maturity discovery and stored path loading remain unbound",
            "requirementId": "REAL_NATURALLY_MATURED_OUTCOMES",
        },
        {
            "id": "GATE-Z-007",
            "severity": "HIGH",
            "title": "Statistics adapter lacks real frozen per-security evidence",
            "requirementId": "MATURITY_TO_STATISTICS_ADAPTER",
        },
    ]

    body: dict[str, Any] = {
        "artifactType": ARTIFACT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "effectiveDate": "2026-07-30",
        "auditMode": "STRICT_READ_ONLY_OFFLINE_CURRENT_WORKTREE",
        "overallStatus": "CRITICAL_BLOCKED_NOT_VALIDATED",
        "completionClaimAuthorized": False,
        "fixtureMayProveRealExecution": False,
        "historicalObservedDataMayBeCalledUntouchedHoldout": False,
        "modelValidationStatus": {
            "tacticalV22": "NOT_VALIDATED",
            "longHorizonV11": "NOT_VALIDATED",
        },
        "authoritativeArtifacts": artifacts,
        "sourceInventory": sources,
        "requirements": requirements,
        "criticalFindings": critical_findings,
        "pipelineStatus": [
            {"stage": "MODEL_AND_PROTOCOL_FREEZE", "status": "IMPLEMENTED_OFFLINE"},
            {"stage": "HISTORICAL_DIAGNOSTIC_CLOSEOUT", "status": "IMPLEMENTED_OFFLINE"},
            {"stage": "POST_CLOSE_CAPTURE", "status": "BLOCKED_BY_TIME"},
            {"stage": "MODEL_INPUT_ASSEMBLY", "status": "BLOCKED_BY_EVIDENCE"},
            {"stage": "SIX_BENCHMARK_MANIFEST", "status": "BLOCKED_BY_EVIDENCE"},
            {"stage": "REAL_MODEL_EXECUTION", "status": "NOT_EXECUTED"},
            {"stage": "IMMUTABLE_DECISION_OUTPUT", "status": "BLOCKED_BY_EVIDENCE"},
            {"stage": "REAL_PROSPECTIVE_SNAPSHOT", "status": "NOT_EXECUTED"},
            {
                "stage": "V19_CHRONOLOGY_REPAIR",
                "status": ("IMPLEMENTED_OFFLINE" if v19_accepted else "BLOCKED_BY_EVIDENCE"),
            },
            {"stage": "V2_1_1_PRODUCTION_WRITE_BOUNDARY", "status": "IMPLEMENTED_OFFLINE"},
            {"stage": "V2_2_PROSPECTIVE_ENROLLMENT", "status": "NOT_EXECUTED"},
            {"stage": "REPEATED_COHORT_ACCUMULATION", "status": "NOT_EXECUTED"},
            {"stage": "MATURITY_ENGINE", "status": "IMPLEMENTED_OFFLINE"},
            {"stage": "NATURAL_MATURITY_OUTCOMES", "status": "BLOCKED_BY_TIME"},
            {"stage": "MATURITY_STATISTICS_ADAPTER", "status": "IMPLEMENTED_OFFLINE"},
            {"stage": "DQV_STATISTICS_ENGINE", "status": "IMPLEMENTED_OFFLINE"},
            {"stage": "REAL_DQV_STATISTICS", "status": "NOT_EXECUTED"},
            {"stage": "FINAL_MODEL_VALIDATION", "status": "NOT_VALIDATED"},
        ],
        "externalConditions": [
            "The target completed trading session must close and be calendar-verified.",
            "At least two prospective decision dates and 100 eligible decisions must mature.",
            "The 5, 20, 60, 126 and 252 completed-session horizons must mature naturally.",
            "Future fundamental observations must exist for business-quality evaluation.",
        ],
        "executionBoundary": {
            "providerNetworkRequests": 0,
            "databaseReads": 0,
            "databaseWrites": 0,
            "scoresOrRanksComputed": False,
            "enrollmentExecuted": False,
            "outcomesComputed": False,
            "commitCreated": False,
            "pushExecuted": False,
            "deploymentExecuted": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def verify_end_to_end_validation_gap_audit(
    repository_root: Path,
    artifact: dict[str, Any],
) -> None:
    if artifact.get("schemaVersion") != SCHEMA_VERSION:
        raise EndToEndValidationGapAuditError("Gap audit schema version changed")
    body = dict(artifact)
    claim = body.pop("artifactContentHash", None)
    if canonical_hash(body) != claim:
        raise EndToEndValidationGapAuditError("Gap audit canonical content hash is invalid")
    rebuilt = build_end_to_end_validation_gap_audit(repository_root)
    if rebuilt != artifact:
        raise EndToEndValidationGapAuditError("Gap audit no longer matches the current worktree")
    if artifact.get("overallStatus") != "CRITICAL_BLOCKED_NOT_VALIDATED":
        raise EndToEndValidationGapAuditError("Current worktree cannot claim completed validation")
    requirements = {item["id"]: item for item in artifact.get("requirements") or ()}
    allowed_requirement_states = {
        "IMPLEMENTED_OFFLINE",
        "BLOCKED_BY_TIME",
        "BLOCKED_BY_EVIDENCE",
        "NOT_EXECUTED",
        "NOT_VALIDATED",
    }
    invalid_states = {
        item["id"]: item.get("status")
        for item in artifact.get("requirements") or ()
        if item.get("status") not in allowed_requirement_states
    }
    if invalid_states:
        raise EndToEndValidationGapAuditError(
            f"Gap audit has non-authoritative requirement states: {invalid_states}"
        )
    real_execution_ids = {
        "POST_CLOSE_COMPLETED_SESSION_CAPTURE",
        "SIX_BENCHMARK_CONSTRUCTION",
        "REAL_POST_FREEZE_MODEL_EXECUTION",
        "REAL_66_PROSPECTIVE_DECISION_SNAPSHOT",
        "REAL_V2_2_PROSPECTIVE_ENROLLMENT",
        "REAL_NATURALLY_MATURED_OUTCOMES",
        "REAL_DQV_STATISTICS_EXECUTION",
        "FINAL_PROSPECTIVE_MODEL_VALIDATION",
    }
    if any(requirements[item]["status"] == "IMPLEMENTED_OFFLINE" for item in real_execution_ids):
        raise EndToEndValidationGapAuditError(
            "A fixture or contract was incorrectly treated as a real execution"
        )
    v19_binding = artifact["authoritativeArtifacts"]["v19ChronologyAcceptance"]
    expected_chronology = (
        "IMPLEMENTED_OFFLINE" if v19_binding.get("artifactContentHash") else "BLOCKED_BY_EVIDENCE"
    )
    if requirements["ENROLLMENT_CHRONOLOGY_LEAKAGE_GUARD"]["status"] != expected_chronology:
        raise EndToEndValidationGapAuditError(
            "V19 chronology status does not match its formal acceptance evidence"
        )
    if requirements["POST_V19_DEPENDENT_ARTIFACT_REGENERATION"]["status"] != (
        "IMPLEMENTED_OFFLINE"
    ):
        raise EndToEndValidationGapAuditError(
            "Post-V19 dependency regeneration is not represented as implemented offline"
        )


def write_or_verify_gap_audit(
    path: Path,
    artifact: dict[str, Any],
) -> str:
    body = dict(artifact)
    claim = body.pop("artifactContentHash", None)
    if canonical_hash(body) != claim:
        raise EndToEndValidationGapAuditError(
            "Cannot write a gap audit with an invalid canonical hash"
        )
    encoded = (json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise EndToEndValidationGapAuditError(
                "Immutable gap audit conflicts with the current worktree"
            )
    else:
        path.write_bytes(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
