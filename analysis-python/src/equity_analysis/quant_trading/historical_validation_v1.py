"""Outcome-blind Stage 3 protocol and controlled-cache eligibility audit."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "QUANT-TRADING-HISTORICAL-VALIDATION-v1.0.0"
TRACK = "YAHOO_ADJUSTED_OHLCV_CURRENT_SURVIVOR_APPROXIMATION"
CLAIM_CEILING = "DEVELOPMENT_OBSERVED_CURRENT_REVISION_CURRENT_SURVIVOR"
C7_RECEIPT_HASH = "B74761883F9395F1334B3F78983DB4237DF0F3F245F449EFFDC73F98FBB738AD"
C7_RECEIPT_FILE_SHA256 = "CD830491016535733CB9FE5C4BEAEBC6EE6D48F0186B6C82F131BF30FE8168C8"
C7_CALENDAR_HASH = "7FE1CA16970AE0346C67120DD4F32BA3BEF039276B9800757D15D3744189AA2C"
C7_CALENDAR_FILE_SHA256 = "AF107891BB758C021EC012FDAB52AADDD8A07664F41CFCB7A686434A7B477CE8"
C9_IDENTITY_SET_HASH = "B29306CE3B1A047C074B68FDA07149FFF72F7B2ECD2BC0D78AAD7B42692656C7"
C9_PREDICTOR_SEAL_HASH = "E110C20287CB1B9E2260E9DAA33C2F2A8B5CD290F11E20EB733B918F61F595DD"
POPULATION_SIZE = 191
REQUIRED_HISTORY = 253
MAX_HOLDING_SESSIONS = 60


class QuantHistoricalValidationViolation(ValueError):
    pass


def canonical_hash(value: object) -> str:
    return (
        hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        )
        .hexdigest()
        .upper()
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


@dataclass(frozen=True)
class PopulationMemberV1:
    security_id: str
    symbol: str
    ordinal: int
    batch: str


def frozen_protocol() -> dict[str, Any]:
    body: dict[str, Any] = {
        "schemaVersion": PROTOCOL_VERSION,
        "state": "PREDECLARED_BEFORE_QUANT_OUTCOME_CALCULATION",
        "tracks": {
            "strictGoverned": {
                "state": "BLOCKED_INPUT_AUTHORITY_INCOMPLETE",
                "reason": "V22_IDENTITY_ACTION_LIFECYCLE_AND_TERMINAL_AUTHORITY_ABSENT",
            },
            "developmentApproximation": {
                "state": "AUTHORIZED_FOR_DEVELOPMENT_OBSERVATION",
                "track": TRACK,
                "claimCeiling": CLAIM_CEILING,
            },
        },
        "population": {
            "count": POPULATION_SIZE,
            "identitySetHash": C9_IDENTITY_SET_HASH,
            "source": "C5_CURRENT_SURVIVOR_CONTROLLED_OVERLAP",
            "survivorshipBias": True,
            "historicalMembershipClaimed": False,
            "delistedPopulationClaimed": False,
            "batchPolicy": "SHA256_SECURITY_ID_ASC; PILOT25_THEN_100_THEN_191",
        },
        "priceEvidence": {
            "receiptHash": C7_RECEIPT_HASH,
            "receiptFileSha256": C7_RECEIPT_FILE_SHA256,
            "calendarHash": C7_CALENDAR_HASH,
            "calendarFileSha256": C7_CALENDAR_FILE_SHA256,
            "aliases": 203,
            "equities": POPULATION_SIZE,
            "benchmark": "SPY",
            "adjustment": "YAHOO-ADJCLOSE-RATIO-OHLC-v1.0.0",
            "separateDividendOrSplitCashFlows": False,
        },
        "decisionProtocol": {
            "frequency": "EVERY_COMPLETED_SPY_SESSION",
            "firstDecision": "FIRST_SESSION_WITH_EXACTLY_253_ALIGNED_ROWS",
            "lastDecision": "LATEST_SESSION_WITH_60_LATER_COMPLETED_SESSIONS",
            "signalHistorySessions": REQUIRED_HISTORY,
            "entry": "IMMEDIATE_NEXT_OBSERVED_SPY_SESSION_OPEN",
            "maximumHoldingSessions": MAX_HOLDING_SESSIONS,
            "signalFormula": "MOMENTUM-CONTINUATION-FORMULAS-v1.0.0",
            "entryExitPolicy": "MOMENTUM-CONTINUATION-ENTRY-EXIT-v1.0.0",
            "simulator": "QUANT-TRADING-PORTFOLIO-SIMULATOR-v1.0.0",
            "initialCashUsd": "100000",
            "costPolicy": "C9-NONLINEAR-COST-v1.0.0",
            "parameterChangeAfterOutcomeAccessAllowed": False,
        },
        "terminalPolicy": {
            "missingOrGappedRow": "EXPLICIT_MISSING_NO_FILL",
            "unprovenTerminalEvent": "EXPLICIT_MISSING_FROM_FIRST_UNEXPLAINED_GAP",
            "haltOrSuspensionAuthority": "NOT_PROVEN_IN_APPROXIMATION_TRACK",
            "productionEligibility": False,
        },
        "benchmarks": {
            "primary": "SPY_BUY_AND_HOLD_SAME_CALENDAR_AND_COST_POLICY",
            "cash": "ZERO_RETURN",
            "equalWeight": "NOT_OBSERVED_BLOCKED_FROZEN_ELIGIBLE_POPULATION",
            "sector": "NOT_OBSERVED_NO_DATED_MAPPING",
        },
        "metrics": [
            "FINAL_NAV_USD",
            "TOTAL_RETURN",
            "CAGR",
            "SPY_EXCESS_RETURN",
            "MAX_DRAWDOWN",
            "ANNUALIZED_VOLATILITY",
            "SHARPE_RF_ZERO",
            "TURNOVER",
            "TOTAL_COST_USD",
            "TRADE_COUNT",
            "WIN_RATE",
            "LOSS_RATE",
            "SEVERE_LOSS_RATE",
        ],
        "severeLossDefinition": "CLOSED_TRADE_NET_RETURN_LESS_THAN_OR_EQUAL_TO_MINUS_20_PERCENT",
        "diagnostics": {
            "calendarYears": "EACH_COMPLETE_OR_PARTIAL_CALENDAR_YEAR",
            "subperiods": ["2015-2019", "2020-2022", "2023-2026"],
            "stressWindows": [
                ["2018-09-20", "2018-12-24"],
                ["2020-02-19", "2020-03-23"],
                ["2022-01-03", "2022-06-16"],
            ],
            "diagnosticOnly": True,
        },
        "knownLimitations": [
            "CURRENT_SURVIVOR_POPULATION",
            "CURRENT_REVISION_PRICE_HISTORY",
            "NO_STRICT_V22_IDENTITY",
            "NO_STRICT_CORPORATE_ACTION_OR_TERMINAL_AUTHORITY",
            "NO_HALTS_OR_SUSPENSIONS_AUTHORITY",
            "NO_UNTOUCHED_HOLDOUT",
            "NO_PRODUCTION_ELIGIBILITY",
            "NO_FUTURE_RETURN_GUARANTEE",
        ],
        "preSealDisclosure": {
            "schemaInspectionBeforeSeal": "ONE_ADM_FIRST_BAR_OPENED_FOR_WIRE_SHAPE_ONLY",
            "strategyReturnOrMetricObservedBeforeSeal": False,
            "parameterChangedFromObservedOutcome": False,
        },
        "networkAuthorized": False,
        "providerRequests": 0,
    }
    body["contentHash"] = canonical_hash(body)
    return body


def population_from_c9_structure(value: dict[str, Any]) -> tuple[PopulationMemberV1, ...]:
    if value.get("contentHash") != C9_PREDICTOR_SEAL_HASH:
        raise QuantHistoricalValidationViolation("C9 predictor-seal identity drift")
    rows = value.get("terminalRows")
    if not isinstance(rows, list):
        raise QuantHistoricalValidationViolation("C9 terminal population is absent")
    identities: dict[str, str] = {}
    for row in rows:
        security_id, symbol = row.get("securityId"), row.get("symbol")
        if not isinstance(security_id, str) or not isinstance(symbol, str):
            raise QuantHistoricalValidationViolation("C9 terminal identity is malformed")
        prior = identities.setdefault(security_id, symbol)
        if prior != symbol:
            raise QuantHistoricalValidationViolation("C9 identity alias is ambiguous")
    if len(identities) != POPULATION_SIZE:
        raise QuantHistoricalValidationViolation("C9 population must contain 191 identities")
    ordered = sorted(identities.items(), key=lambda item: (canonical_hash(item[0]), item[0]))
    members = []
    for ordinal, (security_id, symbol) in enumerate(ordered, 1):
        batch = "PILOT25" if ordinal <= 25 else ("EXPANSION100" if ordinal <= 100 else "FULL191")
        members.append(PopulationMemberV1(security_id, symbol, ordinal, batch))
    return tuple(members)


def audit_controlled_cache(*, storage_root: Path, predictor_seal_path: Path) -> dict[str, Any]:
    protocol = frozen_protocol()
    receipt_path = storage_root / "stage7c7-outcome-execution-receipt.json"
    calendar_path = storage_root / "stage7c7-spy-calendar.json"
    if file_sha256(receipt_path) != C7_RECEIPT_FILE_SHA256:
        raise QuantHistoricalValidationViolation("C7 receipt file drift")
    if file_sha256(calendar_path) != C7_CALENDAR_FILE_SHA256:
        raise QuantHistoricalValidationViolation("C7 calendar file drift")
    receipt = json.loads(receipt_path.read_text())
    calendar = json.loads(calendar_path.read_text())
    predictor = json.loads(predictor_seal_path.read_text())
    members = population_from_c9_structure(predictor)
    if receipt.get("contentHash") != C7_RECEIPT_HASH or receipt.get("completed") != 203:
        raise QuantHistoricalValidationViolation("C7 receipt is not complete")
    if calendar.get("contentHash") != C7_CALENDAR_HASH or calendar.get("sessionCount") != 3160:
        raise QuantHistoricalValidationViolation("C7 SPY calendar identity drift")
    receipt_symbols = {row.get("symbol") for row in receipt.get("records", [])}
    missing = sorted(member.symbol for member in members if member.symbol not in receipt_symbols)
    payload_missing: list[str] = []
    payload_hash_drift: list[str] = []
    too_short: list[str] = []
    receipt_by_symbol = {row["symbol"]: row for row in receipt["records"]}
    for member in members:
        record = receipt_by_symbol.get(member.symbol)
        if record is None:
            continue
        path = storage_root / "payloads" / member.symbol / f"{record['payloadContentHash']}.json"
        if not path.is_file():
            payload_missing.append(member.symbol)
            continue
        payload = json.loads(path.read_text())
        body = {key: item for key, item in payload.items() if key != "contentHash"}
        if (
            payload.get("contentHash") != record["payloadContentHash"]
            or canonical_hash(body) != record["payloadContentHash"]
        ):
            payload_hash_drift.append(member.symbol)
            continue
        dates = [row.get("tradingDate") for row in payload.get("bars", [])]
        if dates != sorted(set(dates)) or len(dates) < REQUIRED_HISTORY + MAX_HOLDING_SESSIONS + 1:
            too_short.append(member.symbol)
    strict_blockers = [
        "V22_DURABLE_IDENTITY_AND_TICKER_INTERVAL_AUTHORITY_ABSENT",
        "CORPORATE_ACTION_EVENT_LIFECYCLE_AND_TERMINAL_AUTHORITY_ABSENT",
        "HISTORICAL_MEMBERSHIP_AND_DELISTED_POPULATION_ABSENT",
    ]
    development_usable = not (missing or payload_missing or payload_hash_drift or too_short)
    body: dict[str, Any] = {
        "schemaVersion": "QUANT-TRADING-STAGE3-CACHE-PREFLIGHT-v1.0.0",
        "protocolHash": protocol["contentHash"],
        "strictTrack": {"state": "BLOCKED_INPUT_AUTHORITY_INCOMPLETE", "blockers": strict_blockers},
        "developmentTrack": {
            "state": "READY_FOR_BATCHED_OUTCOME_EXECUTION"
            if development_usable
            else "BLOCKED_CACHE_INCOMPLETE",
            "track": TRACK,
            "claimCeiling": CLAIM_CEILING,
            "populationCount": len(members),
            "pilotCount": 25,
            "expansionCount": 100,
            "fullCount": 191,
            "missingReceiptSymbols": missing,
            "missingPayloadSymbols": payload_missing,
            "payloadHashDriftSymbols": payload_hash_drift,
            "insufficientHistorySymbols": too_short,
        },
        "numericPriceFieldsRead": False,
        "outcomeMetricsCalculated": False,
        "networkRequests": 0,
    }
    body["contentHash"] = canonical_hash(body)
    return body
