import json
from pathlib import Path

from equity_analysis.fundamental_value.openfigi_us_composite_diagnostic_v15 import (
    ACCEPTED_DECISION_CODE,
    CONTRACT_VERSION,
    canonical_hash,
)

RESULT_PATH = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "fundamental-value-v1"
    / "stage8c-openfigi-us-composite-diagnostic-v15-result-v1.json"
)


def _walk(value: object) -> list[object]:
    values = [value]
    if isinstance(value, dict):
        for key, item in value.items():
            values.append(key)
            values.extend(_walk(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_walk(item))
    return values


def test_v15_git_safe_result_is_hash_bound_and_diagnostic_only() -> None:
    payload = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    content_hash = payload.pop("contentHash")

    assert payload["run"]["diagnosticContractVersion"] == CONTRACT_VERSION
    assert payload["run"]["planContentHash"] == (
        "F7F2E728FB4B91D9FA7E9B7F63B5E38259655B7B64D798BD63BE54DCA187FB40"
    )
    assert payload["run"]["controllerAuthorityContentHash"] == (
        "E7FDA19F3323AAFFBB05C9CD992768A6DF889F8933C301E95C14155C8A028486"
    )
    assert payload["execution"]["newPhysicalRequests"] == 2
    assert payload["execution"]["newPhysicalRequestsDuringZeroSendReplay"] == 0
    assert payload["execution"]["replayedPhysicalRequestsDuringZeroSendReplay"] == 2
    assert payload["execution"]["retryLimit"] == 0
    assert payload["execution"]["unknownTransportOutcomes"] == 0
    assert payload["review"] == {
        "uniquePrimary": 6,
        "ambiguousPrimary": 0,
        "unresolvedWarnings": 0,
        "errors": 0,
        "noPrimary": 0,
        "completeConvergentPairs": 3,
        "pairConflicts": 0,
    }
    assert payload["decision"]["code"] == ACCEPTED_DECISION_CODE
    assert payload["decision"]["accepted"] is True
    assert payload["decision"]["diagnosticOnly"] is True
    assert payload["decision"]["durableIdentityAuthorized"] is False
    assert payload["decision"]["remainderAuthorized"] is False
    assert payload["decision"]["evidenceUpgradeAuthorized"] is False
    assert payload["methodology"]["postPredecessorObservation"] is True
    assert payload["methodology"]["holdoutClaimed"] is False
    assert payload["boundaries"]["v22EvidenceWriteAuthorizedByThisResult"] is False
    assert payload["boundaries"]["v24EnrollmentAuthorizedByThisResult"] is False
    assert payload["boundaries"]["modelEvidenceLabel"] == "NOT_VALIDATED"
    assert payload["nextGate"]["oldProjectionV1Authorized"] is False
    assert payload["nextGate"]["requiredComponents"] == [
        "SEC_OPERATING_MIC_CORROBORATION",
        "TARGET_DATABASE_IDENTITY_INVENTORY",
        "FORWARD_PROJECTION_V2_CONTRACT",
        "V25_IDENTITY_AUTHORITY_LEDGER",
    ]
    assert content_hash == canonical_hash(payload)


def test_v15_git_safe_result_excludes_raw_provider_identity_values() -> None:
    payload = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    flattened = _walk(payload)
    forbidden_keys = {
        "figi",
        "shareClassFIGI",
        "compositeFIGI",
        "identifierValue",
        "responseBody",
        "rawResponse",
    }

    assert forbidden_keys.isdisjoint(item for item in flattened if isinstance(item, str))
