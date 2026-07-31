from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash

AUDIT_VERSION = "PROSPECTIVE-OUTCOME-PERSISTENCE-READINESS-AUDIT-v1.0.0"

MIGRATION_PATHS = tuple(
    Path(f"database/migrations/V{version}__{name}.sql")
    for version, name in (
        (1, "create_application_schemas"),
        (2, "create_market_data_tables"),
        (3, "enforce_unique_security_symbols"),
        (4, "create_source_and_security_history"),
        (5, "create_immutable_analytics_observations"),
        (6, "create_snapshots_and_universes"),
        (7, "create_strategy_metadata_and_screening_runs"),
        (8, "create_screening_results"),
        (9, "create_analytics_access_roles_and_views"),
        (10, "enforce_fundamental_fact_idempotency"),
        (11, "create_forward_validation"),
        (12, "create_user_and_portfolio_context"),
        (13, "seal_market_provider_in_snapshots"),
        (14, "create_market_intelligence_reference_data"),
        (15, "create_market_intelligence_observations_and_screening"),
        (16, "create_market_intelligence_refresh_operations"),
        (17, "persist_market_intelligence_screening_contract"),
    )
)

CONTRACT_PATHS = (
    Path(
        "analysis-python/src/equity_analysis/forward_validation/"
        "prospective_protocol_v2.py"
    ),
    Path(
        "analysis-python/src/equity_analysis/forward_validation/outcomes_v2.py"
    ),
    Path(
        "analysis-python/src/equity_analysis/forward_validation/"
        "prospective_enrollment_v1.py"
    ),
    Path(
        "analysis-python/src/equity_analysis/forward_validation/persistence.py"
    ),
    Path(
        "analysis-python/src/equity_analysis/forward_validation/ledger.py"
    ),
    Path(
        "analysis-python/src/equity_analysis/forward_validation/models.py"
    ),
)
V18_PATH = Path(
    "database/migrations/V18__create_forward_dqv_v2_outcome_ledger.sql"
)
V21_CONTRACT_PATHS = (
    Path(
        "analysis-python/src/equity_analysis/forward_validation/outcomes_v21.py"
    ),
    Path(
        "analysis-python/src/equity_analysis/forward_validation/"
        "outcome_persistence_v21.py"
    ),
)


class ProspectiveOutcomePersistenceAuditError(ValueError):
    pass


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _require_tokens(
    path: Path,
    required: tuple[str, ...],
    forbidden: tuple[str, ...] = (),
) -> None:
    content = path.read_text(encoding="utf-8")
    missing = [token for token in required if token not in content]
    present_forbidden = [token for token in forbidden if token in content]
    if missing or present_forbidden:
        raise ProspectiveOutcomePersistenceAuditError(
            f"{path.name} contract drift: "
            f"missing={missing}, forbidden={present_forbidden}"
        )


def _source_binding(repository_root: Path, relative_path: Path) -> dict[str, Any]:
    path = (repository_root / relative_path).resolve()
    if not path.is_file():
        raise ProspectiveOutcomePersistenceAuditError(
            f"Source file is missing: {relative_path.as_posix()}"
        )
    return {
        "path": relative_path.as_posix(),
        "fileSha256": _file_sha256(path),
    }


def _verify_current_contracts(repository_root: Path) -> None:
    v11 = repository_root / MIGRATION_PATHS[10]
    _require_tokens(
        v11,
        (
            "CREATE TABLE analytics.forward_enrollment",
            "CREATE TABLE analytics.forward_observation_result",
            "CREATE TABLE analytics.forward_metric_result",
            "CHECK (horizon_trading_days IN (5, 20, 60))",
            "'E_SECTOR_ETF', 'E_SPY'",
            "result_version INTEGER NOT NULL DEFAULT 1",
            "supersedes_result_id UUID REFERENCES",
            "CREATE TRIGGER tr_forward_observation_append_only",
        ),
        (
            "horizon_trading_days IN (5, 20, 60, 126, 252)",
            "'PURE_MOMENTUM'",
            "'PURE_VALUE'",
            "'PURE_QUALITY'",
        ),
    )
    v16 = repository_root / MIGRATION_PATHS[15]
    _require_tokens(
        v16,
        (
            "CREATE TABLE analytics.analytics_audit_event",
            "detail JSONB NOT NULL",
            "CONSTRAINT uq_analytics_audit_hash UNIQUE (event_hash)",
            "CREATE TRIGGER tr_analytics_audit_append_only",
        ),
    )
    v17 = repository_root / MIGRATION_PATHS[16]
    _require_tokens(
        v17,
        (
            "CREATE TABLE analytics.security_profile_snapshot",
            "CREATE TABLE analytics.market_intelligence_horizon_view",
            "CREATE TABLE analytics.market_intelligence_screening_run",
            "CREATE TRIGGER tr_market_intelligence_run_append_only",
        ),
    )
    protocol = repository_root / CONTRACT_PATHS[0]
    _require_tokens(
        protocol,
        (
            "sessions != (5, 20, 60, 126, 252)",
            "len(set(self.required_benchmark_kinds)) != 6",
            "class ForwardV2Enrollment",
            "preregistration_content_hash",
            "decision_manifest_content_hash",
            "frozen_population_hash",
            "model_freeze_hashes",
            "storage/forward-validation/enrollments-v2",
        ),
    )
    outcomes = repository_root / CONTRACT_PATHS[1]
    _require_tokens(
        outcomes,
        (
            "_REQUIRED_BENCHMARKS = tuple(BenchmarkKind)",
            "class ForwardOutcomeBatch",
            "class SecurityOutcomeRecord",
            "gross_return",
            "round_trip_cost_rate",
            "net_return",
            "price_action_evidence_hash",
            "completed_sessions not in {5, 20, 60, 126, 252}",
            "storage/forward-validation/outcomes-v2",
            "def write_outcome_bundle",
            "maximum_drawdown",
            "downside_capture",
        ),
        (
            "maximum_favorable_excursion",
            "maximum_adverse_excursion",
        ),
    )
    bridge = repository_root / CONTRACT_PATHS[2]
    _require_tokens(
        bridge,
        (
            "frozenForwardHorizonsTradingDays",
            "[5, 20, 60]",
            "longHorizonIsContextOnly",
            "INSERT INTO analytics.forward_observation_result",
        ),
    )
    persistence = repository_root / CONTRACT_PATHS[3]
    _require_tokens(
        persistence,
        (
            "INSERT INTO analytics.forward_enrollment",
            "INSERT INTO analytics.forward_candidate_signal",
        ),
        (
            "INSERT INTO analytics.forward_dqv_",
            "INSERT INTO analytics.forward_outcome_batch",
        ),
    )
    ledger = repository_root / CONTRACT_PATHS[4]
    _require_tokens(
        ledger,
        (
            "maximum_adverse_excursion",
            "maximum_drawdown",
            "HORIZONS = (5, 20, 60)",
        ),
        ("maximum_favorable_excursion",),
    )


def _verify_v18_successor(repository_root: Path) -> tuple[dict[str, Any], ...]:
    v18 = repository_root / V18_PATH
    _require_tokens(
        v18,
        (
            "CREATE TABLE analytics.forward_dqv_enrollment_v2",
            "CREATE TABLE analytics.forward_dqv_maturity_schedule_v2",
            "CREATE TABLE analytics.forward_dqv_outcome_batch_v2",
            "CREATE TABLE analytics.forward_dqv_security_outcome_v2",
            "CREATE TABLE analytics.forward_dqv_benchmark_outcome_v2",
            "CREATE TABLE analytics.forward_dqv_path_metric_v2",
            "CREATE TABLE analytics.forward_dqv_quality_report_v2",
            "completed_sessions IN (5, 20, 60, 126, 252)",
            "'PURE_MOMENTUM', 'PURE_VALUE', 'PURE_QUALITY'",
            "'MAXIMUM_ADVERSE_EXCURSION'",
            "'MAXIMUM_FAVORABLE_EXCURSION'",
            "CREATE CONSTRAINT TRIGGER tr_forward_dqv_batch_complete",
            "CREATE TRIGGER tr_forward_dqv_quality_report_append_only",
        ),
        ("CREATE TABLE app.",),
    )
    contract = repository_root / V21_CONTRACT_PATHS[0]
    _require_tokens(
        contract,
        (
            'FORWARD_DQV_OUTCOME_V21 = "FORWARD-DQV-OUTCOME-v2.1.0"',
            "class ForwardOutcomeBatchV21",
            "MAXIMUM_ADVERSE_EXCURSION",
            "MAXIMUM_FAVORABLE_EXCURSION",
            "DOWNSIDE_CAPTURE",
            "verify_outcome_batch_v21",
        ),
    )
    persistence = repository_root / V21_CONTRACT_PATHS[1]
    _require_tokens(
        persistence,
        (
            "class ForwardDqvOutcomeRepositoryV21",
            "persist_enrollment",
            "persist_outcome_batch",
            "persist_quality_report",
            "read_outcome_batch",
            "ForwardDqvPersistenceConflict",
        ),
    )
    return tuple(
        _source_binding(repository_root, path)
        for path in (V18_PATH, *V21_CONTRACT_PATHS)
    )


def _capability_matrix() -> tuple[dict[str, Any], ...]:
    return (
        {
            "requirement": "IMMUTABLE_FORWARD_V2_ENROLLMENT",
            "currentDisposition": "PARTIAL_LEGACY_ONLY",
            "existingStructures": (
                "analytics.forward_enrollment",
                "analytics.analytics_audit_event",
            ),
            "supported": (
                "Append-only legacy enrollment identity, idempotency and input hash"
            ),
            "gap": (
                "No typed binding for preregistration hash, v2 decision manifest and "
                "controlled artifact, five-horizon schedule, frozen population hash, "
                "both model freezes, or complete terminal population."
            ),
            "v18Required": True,
        },
        {
            "requirement": "FIVE_MATURITY_HORIZONS",
            "currentDisposition": "HARD_SCHEMA_BLOCK",
            "existingStructures": ("analytics.forward_observation_result",),
            "supported": "5, 20 and 60 completed sessions only",
            "gap": (
                "The V11 CHECK constraint rejects 126 and 252 completed sessions. "
                "The V17 bridge also persists only 5/20/60 and treats Long Horizon "
                "as context-only."
            ),
            "v18Required": True,
        },
        {
            "requirement": "SIX_FORMAL_BENCHMARK_ARMS",
            "currentDisposition": "SEMANTIC_SCHEMA_BLOCK",
            "existingStructures": (
                "analytics.forward_shadow_order",
                "analytics.forward_observation_result",
            ),
            "supported": "Legacy sector ETF and SPY trading arms",
            "gap": (
                "The legacy arm constraint is an entry-policy experiment and has no "
                "typed SPY/SECTOR/EQUAL_WEIGHT/PURE_MOMENTUM/PURE_VALUE/PURE_QUALITY "
                "outcome identity or one-row-per-kind completeness constraint."
            ),
            "v18Required": True,
        },
        {
            "requirement": "GROSS_NET_COST_AND_PATH_METRICS",
            "currentDisposition": "PARTIAL_GENERIC_METRICS",
            "existingStructures": (
                "analytics.forward_metric_result",
                "analytics.forward_daily_valuation",
            ),
            "supported": (
                "Generic version-bound numeric metrics and immutable daily valuations"
            ),
            "gap": (
                "No typed current Forward v2 persistence contract binds gross return, "
                "liquidity-sensitive cost, net return, MAE, MFE, drawdown and downside "
                "metrics to the same security or benchmark outcome and source chain. "
                "Forward outcomes_v2 has gross/net/cost and aggregate drawdown/downside, "
                "but no MAE/MFE fields; the legacy ledger has MAE but not MFE."
            ),
            "v18Required": True,
            "contractExtensionRequired": True,
        },
        {
            "requirement": "SOURCE_AND_VERSION_BINDINGS",
            "currentDisposition": "AUDIT_EVENT_ONLY",
            "existingStructures": (
                "analytics.source_record",
                "analytics.analytics_audit_event",
                "analytics.forward_experiment",
            ),
            "supported": (
                "Append-only hashes, generic JSON audit detail and legacy experiment versions"
            ),
            "gap": (
                "No authoritative outcome row enforces preregistration, model freeze, "
                "benchmark contract, cost policy, decision manifest, population, "
                "calendar, action and price-evidence hashes as one immutable chain."
            ),
            "v18Required": True,
        },
        {
            "requirement": "APPEND_ONLY_CORRECTIONS",
            "currentDisposition": "PARTIAL_RESULT_CHAIN",
            "existingStructures": (
                "analytics.forward_observation_result.result_version",
                "analytics.forward_observation_result.supersedes_result_id",
            ),
            "supported": "Append-only legacy result versions and supersession link",
            "gap": (
                "The current chain cannot cover 126/252 or bind a corrected batch's "
                "complete security population, six benchmark rows and source evidence. "
                "Daily valuation and fill primary keys also cannot accept correction "
                "revisions because updates are rejected and revision columns are absent."
            ),
            "v18Required": True,
        },
        {
            "requirement": "DURABLE_QUALITY_REPORT_EVIDENCE",
            "currentDisposition": "LEGACY_REPORT_ONLY",
            "existingStructures": ("analytics.forward_report_snapshot",),
            "supported": "Legacy one-month/two-month immutable report JSON",
            "gap": (
                "Report types and bindings do not represent Forward v2 targets, "
                "5/20/60/126/252 horizons, block-bootstrap evidence, outcome batch "
                "hashes, or model and preregistration versions."
            ),
            "v18Required": True,
        },
    )


def _v18_responsibility() -> dict[str, Any]:
    return {
        "proposedMigration": (
            "V18__persist_prospective_forward_dqv_v2.sql"
        ),
        "ownership": "Python Analytics owns new analytics.* objects",
        "legacyBoundary": (
            "Do not alter or reinterpret V11 records; V1-V17 remain append-only "
            "and continue serving the legacy forward experiment."
        ),
        "tables": (
            {
                "name": "analytics.forward_dqv_enrollment_v2",
                "responsibility": (
                    "One immutable v2 enrollment root with idempotency/request hash, "
                    "preregistration and decision artifact hashes/references, READY "
                    "snapshot, decision/effective timestamps, frozen universe and "
                    "population hashes, both model freeze bindings, benchmark/cost "
                    "contract versions and hashes, terminal counts and enrollment hash."
                ),
            },
            {
                "name": "analytics.forward_dqv_maturity_schedule_v2",
                "responsibility": (
                    "Exactly one immutable schedule row per enrollment and completed "
                    "session in 5/20/60/126/252, with frozen evaluation role, formal "
                    "eligibility and natural maturity timestamp."
                ),
            },
            {
                "name": "analytics.forward_dqv_outcome_batch_v2",
                "responsibility": (
                    "Versioned immutable outcome batch per enrollment/horizon with "
                    "operational state, observed/matured timestamps, complete source "
                    "manifest hashes, result hash and single-successor supersession chain."
                ),
            },
            {
                "name": "analytics.forward_dqv_security_outcome_v2",
                "responsibility": (
                    "One terminal row per batch and frozen security with explicit "
                    "state/reasons, gross return, liquidity-sensitive cost, net return, "
                    "price/action evidence hash and record hash. Missing data remains null."
                ),
            },
            {
                "name": "analytics.forward_dqv_benchmark_outcome_v2",
                "responsibility": (
                    "Exactly one row per batch and each of the six formal benchmark "
                    "kinds, with identifier, state/reason, gross/cost/net return and "
                    "source evidence hash."
                ),
            },
            {
                "name": "analytics.forward_dqv_path_metric_v2",
                "responsibility": (
                    "Versioned metric/status/reason rows for security, benchmark or "
                    "aggregate subjects, including MAE, MFE, maximum drawdown and "
                    "downside capture without embedding provider prices in Git-safe data."
                ),
            },
            {
                "name": "analytics.forward_dqv_quality_report_v2",
                "responsibility": (
                    "Immutable target-specific Forward v2 quality result bound to "
                    "outcome batches, decision manifests, preregistration, model, "
                    "resampling and maturity hashes; no aggregate claim may replace "
                    "separate Long Horizon targets."
                ),
            },
        ),
        "requiredConstraints": (
            "All new tables reject UPDATE and DELETE.",
            "Enrollment idempotency key and enrollment content hash are unique.",
            (
                "Maturity sessions are limited to 5,20,60,126,252 and unique "
                "per enrollment."
            ),
            (
                "126 sessions is diagnostic-only; 5,20,60 and 252 retain "
                "frozen formal roles."
            ),
            (
                "Benchmark kind is limited to SPY, SECTOR, EQUAL_WEIGHT, "
                "PURE_MOMENTUM, PURE_VALUE and PURE_QUALITY."
            ),
            (
                "A terminal complete batch requires the full frozen security "
                "population and six benchmark rows."
            ),
            (
                "ASSESSED/AVAILABLE rows require gross, cost, net and source "
                "evidence; other states require null numeric values and "
                "explicit reasons."
            ),
            (
                "Net return must equal gross return minus the stored cost "
                "rate within the frozen numeric tolerance."
            ),
            (
                "A correction is a new result_version with one same-enrollment/"
                "same-horizon predecessor; mutation and branching are rejected."
            ),
            (
                "Content hashes and source hashes are required and uniquely "
                "indexed where they define immutable identity."
            ),
            "Raw licensed prices are not stored in Git-safe audit/report payloads.",
            (
                "No app.* object, brokerage execution path or AI-controlled "
                "deterministic field is introduced."
            ),
        ),
        "upgradeTests": (
            "PostgreSQL 17 clean V1-to-V18",
            "V11-to-V18 upgrade preserving every legacy row and trigger",
            "V16-to-V18 and V17-to-V18 upgrades",
            "exact replay and idempotency conflict",
            "five-horizon completeness and 126-session diagnostic-role enforcement",
            "six-benchmark completeness and unavailable-state handling",
            "missing numeric values never become zero",
            "correction successor accepted; mutation, cycles and branches rejected",
            "source/model/benchmark/prereg hash mismatch rejected",
            "full frozen population and terminal-state completeness",
        ),
    }


def build_prospective_outcome_persistence_readiness_audit(
    repository_root: Path,
) -> dict[str, Any]:
    root = repository_root.resolve()
    _verify_current_contracts(root)
    migration_bindings = tuple(
        _source_binding(root, path) for path in MIGRATION_PATHS
    )
    contract_bindings = tuple(
        _source_binding(root, path) for path in CONTRACT_PATHS
    )
    capability_matrix = _capability_matrix()
    migration_required = any(
        item["v18Required"] for item in capability_matrix
    )
    if not migration_required:
        raise ProspectiveOutcomePersistenceAuditError(
            "Audit no longer demonstrates a structural persistence gap"
        )
    existing_v18 = sorted(
        path.name
        for path in (root / "database/migrations").glob("V18__*.sql")
    )
    if existing_v18 and existing_v18 != [V18_PATH.name]:
        raise ProspectiveOutcomePersistenceAuditError(
            f"Unexpected V18 migration set exists: {existing_v18}"
        )
    successor_bindings = (
        _verify_v18_successor(root) if existing_v18 else ()
    )
    evidence = {
        "migrations": migration_bindings,
        "contractsAndRepositories": contract_bindings,
        "implementedSuccessor": successor_bindings,
    }
    evidence["evidenceHash"] = canonical_hash(evidence)
    body: dict[str, Any] = {
        "artifactType": "PROSPECTIVE_OUTCOME_PERSISTENCE_READINESS_AUDIT",
        "schemaVersion": AUDIT_VERSION,
        "effectiveDate": "2026-07-29",
        "auditMode": "STRICTLY_OFFLINE_READ_ONLY",
        "status": (
            "V18_SUCCESSOR_IMPLEMENTED_PENDING_ACCEPTANCE"
            if existing_v18
            else "V18_REQUIRED_NOT_IMPLEMENTED"
        ),
        "scope": (
            "Durable PostgreSQL representation of Forward DQV v2 enrollment, "
            "outcomes, corrections and quality evidence. This does not supersede "
            "the earlier V14-V17 runtime-evidence audit."
        ),
        "evidence": evidence,
        "capabilityMatrix": capability_matrix,
        "decision": {
            "reuseV1V17WithoutMigration": False,
            "v18Required": True,
            "reason": (
                "V11 hard-rejects 126/252 sessions and lacks the six formal "
                "benchmark outcome identities and complete Forward v2 hash/version "
                "chain. V16 audit JSON is a trace facility, not a typed authoritative "
                "numeric outcome ledger. Current v2 enrollment/outcomes are durable "
                "only as controlled files and have no PostgreSQL repository."
            ),
            "migrationCreated": bool(existing_v18),
            "contractExtensionRequiredBeforeImplementation": not bool(existing_v18),
            "contractExtensionBoundary": (
                "Add MAE/MFE and their source/metric semantics in a new versioned "
                "Forward outcome contract; do not change formulas or silently add "
                "them to immutable v2.0 artifacts."
            ),
        },
        "v18Responsibility": _v18_responsibility(),
        "execution": {
            "networkRequests": 0,
            "databaseReads": 0,
            "databaseWrites": 0,
            "scoringRuns": 0,
            "formulaChanges": False,
            "migrationFilesCreated": len(existing_v18),
            "commits": 0,
            "pushes": 0,
            "deployments": 0,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_audit(path: Path, artifact: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n"
    ).encode()
    if path.exists():
        if path.read_bytes() != encoded:
            raise ProspectiveOutcomePersistenceAuditError(
                "PROSPECTIVE_OUTCOME_PERSISTENCE_AUDIT_IMMUTABLE_CONFLICT"
            )
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest().upper()
