import json
from pathlib import Path

from equity_analysis.provider_validation.expansion_gate import canonical_hash
from equity_analysis.provider_validation.final_billing_reconciliation import (
    calculate_budget,
)


def test_independent_final_budget_recalculation() -> None:
    weights = [192, *([240] * 10), 228]
    assert sum(weights) == 2820
    assert calculate_budget(weights, 235) == {
        "configuredLocalWeights": 2820,
        "provisionalProviderBilling": 5875,
        "hardProviderBilledSafetyCeiling": 8813,
    }


def test_final_billing_sidecar_is_canonical_and_value_free() -> None:
    root = Path(__file__).resolve().parents[2]
    artifact = json.loads(
        (
            root
            / "docs/generated/formula-ready-243-final-billing-reconciliation-v1.json"
        ).read_text(encoding="utf-8")
    )
    without_hash = {
        key: value for key, value in artifact.items() if key != "artifactContentHash"
    }
    assert artifact["artifactContentHash"] == canonical_hash(without_hash)
    assert artifact["dashboard"] == {
        "before": 21712,
        "after": 26647,
        "observedProviderBilledDelta": 4935,
    }
    assert artifact["runLevelBillingStatus"] == "PROVISIONALLY_RECONCILED"
    assert artifact["endpointLevelBillingStatus"] == "NOT_RECONCILED"
    assert artifact["physicalAttempts"]["eodhd"] == 705
    assert artifact["physicalAttempts"]["sec"] == 476
    assert artifact["physicalAttempts"]["total"] == 1181
    assert artifact["physicalAttempts"]["retries"] == 0
    assert artifact["securityCounts"] == {
        "unique": 243,
        "formulaReady": 223,
        "insufficientData": 20,
        "systemExecutionFailures": 0,
    }
    assert len(artifact["componentEvidence"]) == 12
    assert sum(
        len(item["checkpoints"]) for item in artifact["componentEvidence"]
    ) == 239
    assert artifact["rawProviderValuesIncluded"] is False
    assert artifact["licensedPayloadsIncluded"] is False
    assert artifact["credentialsIncluded"] is False
    assert artifact["objectiveRatingExecuted"] is False


def test_sidecar_links_all_report_checkpoint_and_terminal_payload_hashes() -> None:
    root = Path(__file__).resolve().parents[2]
    artifact = json.loads(
        (
            root
            / "docs/generated/formula-ready-243-final-billing-reconciliation-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert all(
        len(item["reportSha256"]) == 64
        and len(item["preflightJournalSha256"]) == 64
        and len(item["completeJournalSha256"]) == 64
        for item in artifact["componentEvidence"]
    )
    assert all(
        len(checkpoint["sha256"]) == 64
        for item in artifact["componentEvidence"]
        for checkpoint in item["checkpoints"]
    )
    terminal_count = sum(
        len(item["terminalPayloads"]) for item in artifact["componentEvidence"]
    ) + len(artifact["terminalEvidenceOutsideSlices"])
    assert terminal_count == 243
