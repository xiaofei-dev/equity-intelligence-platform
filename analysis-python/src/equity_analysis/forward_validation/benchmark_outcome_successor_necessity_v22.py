from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash

BENCHMARK_OUTCOME_SUCCESSOR_NECESSITY_V1 = (
    "FORWARD-DQV-BENCHMARK-OUTCOME-SUCCESSOR-NECESSITY-v1.0.0"
)

_SOURCE_FILES = (
    Path("database/migrations/V18__create_forward_dqv_v2_outcome_ledger.sql"),
    Path(
        "analysis-python/src/equity_analysis/forward_validation/"
        "benchmark_controlled_ledger_v22.py"
    ),
    Path(
        "analysis-python/src/equity_analysis/forward_validation/"
        "maturity_path_loader_v22.py"
    ),
    Path(
        "analysis-python/src/equity_analysis/forward_validation/"
        "maturity_statistics_adapter_v22.py"
    ),
)


class BenchmarkOutcomeSuccessorNecessityError(ValueError):
    pass


def build_benchmark_outcome_successor_necessity_v1(
    repository_root: Path,
) -> dict[str, Any]:
    root = repository_root.resolve()
    sources = {
        path.as_posix(): _read_source(root, path) for path in _SOURCE_FILES
    }
    migration = sources[_SOURCE_FILES[0].as_posix()]
    loader = sources[_SOURCE_FILES[2].as_posix()]
    statistics = sources[_SOURCE_FILES[3].as_posix()]
    ledger = sources[_SOURCE_FILES[1].as_posix()]

    checks = {
        "v18BenchmarkPrimaryKeyIsBatchAndKind": (
            "PRIMARY KEY (outcome_batch_id, benchmark_kind)" in migration
        ),
        "v18BenchmarkOutcomeHasNoSecurityId": _table_segment(
            migration,
            "CREATE TABLE analytics.forward_dqv_benchmark_outcome_v2",
            "CREATE TABLE analytics.forward_dqv_path_metric_v2",
        ).find("security_id") == -1,
        "v18BenchmarkOutcomeHasNoVariantId": _table_segment(
            migration,
            "CREATE TABLE analytics.forward_dqv_benchmark_outcome_v2",
            "CREATE TABLE analytics.forward_dqv_path_metric_v2",
        ).find("variant_id") == -1,
        "ledgerRetainsSectorVariants": (
            "ControlledBenchmarkVariantV22" in ledger
            and "self.kind == BenchmarkKind.SECTOR" in ledger
        ),
        "loaderBlocksUnboundSectorVariant": (
            "SEALED_SECTOR_VARIANT_SELECTION_NOT_BOUND" in loader
        ),
        "loaderBlocksUnprovenLiquidityAggregation": (
            "SEALED_BENCHMARK_LIQUIDITY_AGGREGATION_NOT_PROVEN" in loader
        ),
        "gateHPathHasOneNotional": "order_notional: Decimal | None" in loader,
        "gateHPathHasOneAdtv": (
            "average_daily_dollar_volume: Decimal | None" in loader
        ),
        "statisticsBuildsOneGlobalBenchmarkMap": (
            "benchmark_returns, benchmark_drawdowns = _benchmark_maps("
            in statistics
            and "benchmark_returns=benchmark_returns" in statistics
        ),
    }
    if not all(checks.values()):
        failed = sorted(key for key, passed in checks.items() if not passed)
        raise BenchmarkOutcomeSuccessorNecessityError(
            "SOURCE_CONSTRAINT_PROOF_FAILED:" + ",".join(failed)
        )

    source_bindings = [
        {
            "reference": path.as_posix(),
            "fileSha256": _file_hash(root / path),
        }
        for path in _SOURCE_FILES
    ]
    body: dict[str, Any] = {
        "artifactType": "FORWARD_DQV_BENCHMARK_OUTCOME_SUCCESSOR_NECESSITY",
        "schemaVersion": BENCHMARK_OUTCOME_SUCCESSOR_NECESSITY_V1,
        "status": "SUCCESSOR_REQUIRED_BEFORE_FORMAL_OUTCOME",
        "ledgerReadiness": {
            "status": "READY_CONTRACT_IMPLEMENTED",
            "contractVersion": "FORWARD-DQV-BENCHMARK-PATH-LEDGER-v2.2.0",
            "sixBenchmarkFamiliesRequired": True,
            "sectorVariantsRetained": True,
            "holdingLevelPriceActionLiquidityAndCostEvidenceRetained": True,
        },
        "formalOutcomeSchemaReadiness": {
            "status": "BLOCKED",
            "blockers": [
                "V18_SECTOR_OUTCOME_NOT_SECURITY_SPECIFIC",
                "V18_BENCHMARK_VARIANT_ID_NOT_RETAINED",
                "GATE_H_MULTI_HOLDING_COST_INPUT_NOT_EXPRESSIBLE",
                "STATISTICS_SECTOR_RETURN_REUSED_ACROSS_ALL_SECURITIES",
            ],
        },
        "sourceConstraintChecks": checks,
        "sourceBindings": source_bindings,
        "requiredSuccessorDesign": {
            "suggestedMigrationVersion": "V20",
            "migrationApplied": False,
            "gateHContractTarget": "FORWARD-DQV-GATE-H-v2.3.0",
            "minimumTables": [
                {
                    "name": "analytics.forward_dqv_benchmark_ledger_v3",
                    "key": ["id"],
                    "responsibility": (
                        "Persist the immutable decision-time ledger header, "
                        "enrollment, cutoff, population, model, benchmark, "
                        "classification, and cost-policy roots."
                    ),
                },
                {
                    "name": "analytics.forward_dqv_benchmark_family_v3",
                    "key": ["ledger_id", "benchmark_kind"],
                    "responsibility": (
                        "Persist exactly the six frozen benchmark families "
                        "and each family's terminal evidence state."
                    ),
                },
                {
                    "name": "analytics.forward_dqv_benchmark_variant_v3",
                    "key": ["ledger_id", "benchmark_kind", "variant_id"],
                    "responsibility": (
                        "Persist every sealed benchmark variant, including "
                        "all dated sector ETF variants."
                    ),
                },
                {
                    "name": "analytics.forward_dqv_benchmark_holding_v3",
                    "key": [
                        "ledger_id",
                        "benchmark_kind",
                        "variant_id",
                        "holding_security_id",
                    ],
                    "responsibility": (
                        "Persist decision-time holding weights, notional, "
                        "ADTV, cost, selection, price, action, and lineage."
                    ),
                },
                {
                    "name": (
                        "analytics.forward_dqv_benchmark_variant_outcome_v3"
                    ),
                    "key": [
                        "outcome_batch_id",
                        "benchmark_kind",
                        "variant_id",
                    ],
                    "responsibility": (
                        "Persist each benchmark variant path and its "
                        "portfolio-level gross, cost, net, and evidence roots."
                    ),
                },
                {
                    "name": (
                        "analytics.forward_dqv_security_benchmark_binding_v3"
                    ),
                    "key": [
                        "ledger_id",
                        "security_id",
                        "benchmark_kind",
                    ],
                    "responsibility": (
                        "Bind every frozen security to exactly one variant for "
                        "each benchmark kind, including its dated sector ETF."
                    ),
                },
                {
                    "name": (
                        "analytics.forward_dqv_benchmark_holding_outcome_v3"
                    ),
                    "key": [
                        "outcome_batch_id",
                        "benchmark_kind",
                        "variant_id",
                        "holding_security_id",
                    ],
                    "responsibility": (
                        "Persist each holding weight, notional, ADTV, gross "
                        "contribution, nonlinear cost result, and evidence hash."
                    ),
                },
            ],
            "existingOutcomeBatchHeaderReused": True,
            "outcomeBatchHeaderRule": (
                "V18 forward_dqv_outcome_batch_v2 remains the maturity-run "
                "header and must reference the exact decision-time ledger."
            ),
            "portfolioReturnRule": (
                "Compute weighted holding returns for the selected variant."
            ),
            "portfolioCostRule": (
                "Evaluate liquidity-sensitive cost per holding, then divide "
                "the sum of holding notional multiplied by holding cost rate "
                "by total variant notional; never average ADTV or copy one "
                "holding cost to the portfolio."
            ),
            "sectorComparisonRule": (
                "Resolve the SECTOR variant from each security's sealed dated "
                "classification binding; never reuse one sector outcome for "
                "all securities."
            ),
            "appendOnlyCorrectionRequired": True,
            "exact66BySixBindingCompletenessRequired": True,
            "requiredUpgradeTests": [
                "CLEAN_V1_TO_V20",
                "UPGRADE_V18_TO_V20",
                "UPGRADE_V19_TO_V20",
                "EXACT_SIX_FAMILIES_PER_LEDGER",
                "EXACT_66_BY_SIX_SECURITY_BINDINGS",
                "SECTOR_BINDING_USES_DATED_CLASSIFICATION",
                "MULTI_HOLDING_COST_USES_HOLDING_LEVEL_ADTV",
                "AGGREGATE_ADTV_REJECTED",
                "APPEND_ONLY_CORRECTION_CHAIN",
            ],
        },
        "providerNetworkRequests": 0,
        "databaseReads": 0,
        "databaseWrites": 0,
        "migrationCreated": False,
        "formalOutcomesComputed": False,
        "scoresOrRanksComputed": False,
        "forwardValidatedClaimed": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def _read_source(root: Path, reference: Path) -> str:
    path = (root / reference).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise BenchmarkOutcomeSuccessorNecessityError(
            "SOURCE_REFERENCE_ESCAPES_REPOSITORY"
        ) from exc
    return path.read_text(encoding="utf-8")


def _table_segment(source: str, start: str, end: str) -> str:
    start_index = source.find(start)
    end_index = source.find(end, start_index + len(start))
    if start_index < 0 or end_index < 0:
        raise BenchmarkOutcomeSuccessorNecessityError(
            "V18_BENCHMARK_TABLE_BOUNDARY_NOT_FOUND"
        )
    return source[start_index:end_index]


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
