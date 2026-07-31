from __future__ import annotations

import json
from pathlib import Path

import pytest

from equity_analysis.historical_validation.provider_backtest_preflight_v1 import (
    REPOSITORY_ROOT,
    ProviderBacktestPreflightError,
    build_provider_backtest_preflight,
    canonical_hash,
    select_backtest_universe,
    write_preflight,
)


def test_selects_exactly_one_hundred_formula_ready_issuers() -> None:
    selected = select_backtest_universe()

    assert len(selected) == 100
    assert len({item.symbol for item in selected}) == 100
    assert len({item.security_id for item in selected}) == 100
    assert sum(item.role == "RETAINED_V1" for item in selected) == 42
    assert sum(item.role.startswith("EXPANSION_") for item in selected) == 58
    assert all(item.security_id == f"US:{item.symbol}" for item in selected)
    assert all(len(item.formula_input_content_hash) == 64 for item in selected)


def test_preflight_is_zero_network_and_reuses_controlled_inputs() -> None:
    artifact = build_provider_backtest_preflight()

    yahoo = artifact["acquisition"]["yahooHistoricalPrice"]
    eodhd = artifact["acquisition"]["eodhd"]
    assert (
        artifact["status"]
        == "READY_FOR_ZERO_NETWORK_CONTROLLED_DATA_AUDIT"
    )
    assert artifact["selection"]["issuerCount"] == 100
    assert artifact["selection"]["marketBenchmark"] == "SPY"
    assert yahoo["symbolCount"] == 0
    assert yahoo["offlineCanaryReadCount"] == 8
    assert yahoo["plannedPhysicalWrapperCalls"] == 0
    assert yahoo["hardPhysicalWrapperCallCeiling"] == 0
    assert yahoo["providerRetryLimit"] == 0
    assert eodhd["plannedPhysicalRequests"] == 0
    assert eodhd["hardBilledCallCeiling"] == 0
    assert eodhd["minimumUnusedReserve"] == 10_000
    assert artifact["networkRequestsExecuted"] is False
    assert artifact["providerValuesIncluded"] is False


def test_expansion_is_balanced_across_supported_sectors() -> None:
    artifact = build_provider_backtest_preflight()
    expanded = [
        item
        for item in artifact["securities"]
        if item["role"].startswith("EXPANSION_")
    ]
    counts: dict[str, int] = {}
    for item in expanded:
        counts[item["sector"]] = counts.get(item["sector"], 0) + 1

    assert sorted(counts.values()) == [7, 7, 7, 7, 7, 7, 8, 8]
    assert set(counts) == {
        "Communication Services",
        "Consumer Discretionary",
        "Consumer Staples",
        "Health Care",
        "Industrials",
        "Information Technology",
        "Materials",
        "Utilities",
    }


def test_preflight_hash_is_canonical_and_deterministic() -> None:
    first = build_provider_backtest_preflight()
    second = build_provider_backtest_preflight()
    body = dict(first)
    claimed = body.pop("artifactContentHash")

    assert first == second
    assert claimed == canonical_hash(body)


def test_write_preflight_is_immutable(tmp_path: Path) -> None:
    path = tmp_path / "preflight.json"
    payload = build_provider_backtest_preflight()
    write_preflight(path, payload)
    write_preflight(path, payload)

    changed = dict(payload)
    changed["status"] = "CHANGED"
    with pytest.raises(
        ProviderBacktestPreflightError,
        match="IMMUTABLE_PREFLIGHT_CONFLICT",
    ):
        write_preflight(path, changed)


def test_changed_source_artifact_hash_fails_closed(tmp_path: Path) -> None:
    for relative in (
        "analysis-python/resources/universes/"
        "market-intelligence-closed-test-us-v1.json",
        "analysis-python/tests/fixtures/provider_expansion_universe_v2.json",
        "docs/generated/formula-ready-243-final-aggregate-v1.json",
        "docs/generated/"
        "historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json",
        "docs/generated/provider-cached-transport-semantic-audit-v1.2.json",
    ):
        source = REPOSITORY_ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    aggregate_path = (
        tmp_path / "docs/generated/formula-ready-243-final-aggregate-v1.json"
    )
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["uniqueSecurityCount"] = 242
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")

    with pytest.raises(
        ProviderBacktestPreflightError,
        match="FORMULA_INPUT_AGGREGATE_CONTENT_HASH_MISMATCH",
    ):
        build_provider_backtest_preflight(repository_root=tmp_path)
