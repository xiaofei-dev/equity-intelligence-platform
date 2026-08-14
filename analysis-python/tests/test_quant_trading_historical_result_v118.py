from __future__ import annotations

import hashlib
import json
from pathlib import Path

import equity_analysis.quant_trading.historical_execution_v11 as execution
from equity_analysis.quant_trading.historical_validation_v11 import canonical_hash

REPOSITORY = Path(__file__).resolve().parents[2]
FIXTURE = REPOSITORY / (
    "contracts/quant-trading-v1.1/"
    "historical-execution-v1.1.8-controlled-result.json"
)
CONTROLLED_RUN = REPOSITORY / (
    "storage/historical-validation/yahoo-daily-price-cache-v1/"
    "quant-trading-v11-controlled/QUANT-V11-CONTROLLED-20260812-008"
)
EVENT_FILES = (
    "000001-PREPARATION_INTENT.json",
    "000002-PREPARATION_STRUCTURAL_COMPLETE.json",
    "000003-OUTCOME_ACCESS_INTENT.json",
    "000004-OUTCOME_EXECUTION_INTENT.json",
    "000005-POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL.json",
    "000006-OUTCOME_EXECUTION_COMPLETED.json",
)
OUTPUT_FILES = {
    "PRIMARY_C9": "full191-primary-c9.json",
    "FIXED_FIVE_BPS": "full191-fixed-five-bps.json",
    "SPY": "full191-spy.json",
    "TERMINAL_REGISTRY": "full191-terminal-registry.ndjson",
}


def _fixture() -> dict:
    return json.loads(FIXTURE.read_bytes())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def test_controlled_result_fixture_hash_and_git_safe_boundary() -> None:
    document = _fixture()
    claimed = document.pop("canonicalContentHash")
    assert claimed == "56FB135C51432362049BA163E78F98995D9C583C3CD656DF216BE1E5B3C52814"
    assert canonical_hash(document) == claimed
    assert document["runId"] == "QUANT-V11-CONTROLLED-20260812-008"
    assert document["interpretation"] == (
        "NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME"
    )
    assert document["modelEvidenceLabel"] == "NOT_VALIDATED"
    assert document["claimUpgradeAllowed"] is False
    assert document["sameOutcomeRetuningAllowed"] is False
    assert document["dataBoundary"] == {
        "gitSafeAggregateOnly": True,
        "rawPayloadsIncluded": False,
        "dailyRowsIncluded": False,
        "ordersIncluded": False,
        "securityRowsIncluded": False,
        "licensedValuesIncluded": False,
        "sourceStoragePathsIncluded": False,
    }
    encoded = FIXTURE.read_text(encoding="utf-8")
    assert all(
        forbidden not in encoded
        for forbidden in (
            '"bars"',
            '"dailyNav"',
            '"orders"',
            '"securityId"',
            '"symbol"',
            '"sourceReference"',
            '"relativePath"',
            "storage/",
            "storage\\",
        )
    )


def test_controlled_result_exact_artifact_hash_readback() -> None:
    document = _fixture()
    assert [item["sequence"] for item in document["eventChain"]] == list(range(1, 7))
    for expected, filename in zip(document["eventChain"], EVENT_FILES, strict=True):
        assert _sha256(CONTROLLED_RUN / "events" / filename) == expected["fileSha256"]

    terminal_event = json.loads(
        (CONTROLLED_RUN / "events" / EVENT_FILES[-1]).read_bytes()
    )
    assert terminal_event["artifactContentHash"] == document["eventChain"][-1][
        "artifactContentHash"
    ]
    assert terminal_event["eventHash"] == document["eventChain"][-1]["eventHash"]
    assert terminal_event["artifact"]["postAccessInputSealHash"] == document[
        "sealedInputs"
    ]["postAccessInputSealHash"]

    outputs = {item["outputId"]: item for item in document["outputArtifacts"]}
    for output_id, filename in OUTPUT_FILES.items():
        assert _sha256(CONTROLLED_RUN / "outcomes" / filename) == outputs[output_id][
            "fileSha256"
        ]
    for output_id in ("PRIMARY_C9", "FIXED_FIVE_BPS", "SPY"):
        value = json.loads(
            (CONTROLLED_RUN / "outcomes" / OUTPUT_FILES[output_id]).read_bytes()
        )
        assert value["contentHash"] == outputs[output_id]["contentHash"]


def test_controlled_result_metrics_and_frozen_gate_evaluation_replay_exactly() -> None:
    document = _fixture()
    root = CONTROLLED_RUN / "outcomes"
    primary = execution._decode_portfolio_run(
        execution._load_strict_json(root / OUTPUT_FILES["PRIMARY_C9"])
    )
    fixed = execution._decode_portfolio_run(
        execution._load_strict_json(root / OUTPUT_FILES["FIXED_FIVE_BPS"])
    )
    spy = execution._decode_portfolio_run(
        execution._load_strict_json(root / OUTPUT_FILES["SPY"])
    )
    observed = execution._evaluate_runs(primary, fixed, spy)
    expected = document["evaluation"]
    actual = observed["acceptance"]
    assert actual["state"] == expected["state"]
    assert actual["allGatesPass"] is False
    assert actual["gateResults"] == expected["gateResults"]
    assert actual["gateSetHash"] == expected["gateSetHash"]
    assert actual["acceptanceContentHash"] == expected["acceptanceContentHash"]
    assert sum(item["state"] == "PASS" for item in actual["gateResults"]) == 5
    assert sum(item["state"] == "FAIL" for item in actual["gateResults"]) == 4
    assert [
        item["code"] for item in actual["gateResults"] if item["state"] == "FAIL"
    ] == expected["failedGateCodes"]
    assert observed["modelEvidenceLabel"] == "NOT_VALIDATED"
    assert observed["claimUpgradeAllowed"] is False

    metrics = document["metrics"]
    assert primary.metrics["finalNav"] == metrics["primary"]["finalNav"]
    assert primary.metrics["cagr"] == metrics["primary"]["cagr"]
    assert primary.metrics["maxDrawdown"] == metrics["primary"]["maxDrawdown"]
    assert primary.metrics["sharpeRfZero"] == metrics["primary"]["sharpeRfZero"]
    assert fixed.metrics["finalNav"] == metrics["fixedFiveBps"]["finalNav"]
    assert spy.metrics["finalNav"] == metrics["spy"]["finalNav"]
    assert observed["primaryCagrExcessVsSpy"] == metrics["comparisons"][
        "primaryCagrExcessVsSpy"
    ]
