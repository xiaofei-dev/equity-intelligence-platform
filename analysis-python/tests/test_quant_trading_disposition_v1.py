from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from equity_analysis.quant_trading.disposition_v1 import (
    QuantTradingDispositionViolation,
    frozen_v1_disposition,
    validate_v1_disposition,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "contracts" / "quant-trading-v1" / "stage3-disposition.json"


def test_frozen_disposition_matches_canonical_fixture() -> None:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert value == frozen_v1_disposition()
    validate_v1_disposition(value)


def test_disposition_keeps_v1_rejected_and_not_validated() -> None:
    value = frozen_v1_disposition()
    assert value["disposition"] == "REJECTED_FOR_PRODUCTION_ECONOMIC_PERFORMANCE"
    assert value["modelEvidenceLabel"] == "NOT_VALIDATED"
    assert value["ruling"]["sameOutcomeParameterTuningAllowed"] is False
    assert value["ruling"]["successorMustUseNewVersionIdentity"] is True


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("modelEvidenceLabel",), "BACKTEST_SUPPORTED"),
        (("disposition",), "ACCEPTED"),
        (("observed", "cagr"), "0.1128"),
        (("ruling", "sameOutcomeParameterTuningAllowed"), True),
    ],
)
def test_disposition_rejects_claim_or_result_drift(
    path: tuple[str, ...], replacement: object
) -> None:
    value = deepcopy(frozen_v1_disposition())
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    with pytest.raises(QuantTradingDispositionViolation):
        validate_v1_disposition(value)
