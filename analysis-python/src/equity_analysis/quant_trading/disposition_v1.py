"""Immutable economic disposition for the rejected Quant Trading v1 strategy."""

from __future__ import annotations

import hashlib
import json
from typing import Any

DISPOSITION_VERSION = "QUANT-TRADING-V1-DISPOSITION-v1.0.0"
PROTOCOL_HASH = "84B5DEEDF5ABE572C135E3E1CF3D4FF7ED391F93A20A82D4F3B6C1BF48F070BC"
FULL_RESULT_HASH = "F87E4AF65E9E2AAF73BC6ADA7142FB5C78E21D0E2D8E95771D83963C1533AB8D"


class QuantTradingDispositionViolation(ValueError):
    pass


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest().upper()


def frozen_v1_disposition() -> dict[str, Any]:
    body: dict[str, Any] = {
        "schemaVersion": DISPOSITION_VERSION,
        "modelVersion": "QUANT-TRADING-v1.0.0",
        "strategyVersion": "MOMENTUM-CONTINUATION-v1.0.0",
        "validationProtocolHash": PROTOCOL_HASH,
        "fullPopulationResultHash": FULL_RESULT_HASH,
        "populationCount": 191,
        "track": "YAHOO_ADJUSTED_OHLCV_CURRENT_SURVIVOR_APPROXIMATION",
        "claimCeiling": "DEVELOPMENT_OBSERVED_CURRENT_REVISION_CURRENT_SURVIVOR",
        "modelEvidenceLabel": "NOT_VALIDATED",
        "disposition": "REJECTED_FOR_PRODUCTION_ECONOMIC_PERFORMANCE",
        "observed": {
            "initialNavUsd": "100000",
            "finalNavUsd": "113808.46",
            "totalReturn": "0.1380846",
            "cagr": "0.01128",
            "maximumDrawdown": "-0.1202",
            "annualizedVolatility": "0.0751",
            "sharpeRfZero": "0.187",
            "closedTrades": 1243,
            "winRate": "0.3138",
            "severeLossRate": "0.000805",
            "totalCostUsd": "2867.34",
            "spyFinalNavUsd": "438691.69",
            "spyTotalReturn": "3.3869169",
            "spyCagr": "0.13676",
            "spyMaximumDrawdown": "-0.3369",
            "spySharpeRfZero": "0.823",
        },
        "ruling": {
            "lowerDrawdownIsInsufficientWithoutCompetitiveReturn": True,
            "sameOutcomeParameterTuningAllowed": False,
            "productionPersistenceAllowed": False,
            "publicApiAllowed": False,
            "brokerageExecutionAllowed": False,
            "evidenceUpgradeAllowed": False,
            "successorMustUseNewVersionIdentity": True,
            "successorSameHistoryClaim": "DEVELOPMENT_ONLY_NOT_UNTOUCHED_HOLDOUT",
        },
        "limitations": [
            "CURRENT_SURVIVOR_POPULATION",
            "CURRENT_REVISION_PRICE_HISTORY",
            "NO_STRICT_V22_IDENTITY",
            "NO_STRICT_CORPORATE_ACTION_OR_TERMINAL_AUTHORITY",
            "NO_UNTOUCHED_HOLDOUT",
        ],
    }
    body["contentHash"] = canonical_hash(body)
    return body


def validate_v1_disposition(value: dict[str, Any]) -> None:
    expected = frozen_v1_disposition()
    if value != expected:
        raise QuantTradingDispositionViolation("Quant Trading v1 disposition drift")
    supplied_hash = value.get("contentHash")
    body = {key: item for key, item in value.items() if key != "contentHash"}
    if supplied_hash != canonical_hash(body):
        raise QuantTradingDispositionViolation("Quant Trading v1 disposition hash drift")
