"""Deterministic C9 terminal-registry and outcome aggregation runner."""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from .historical_confirmation_v1 import (
    ARITHMETIC_CONTEXT,
    C8_DATES,
    DATES,
    cost_rate,
    ordinal_correlation,
    select_dates,
)
from .historical_quarterly_semantics_support_v1 import canonical_hash
from .historical_validation_v1 import annualize_total_return

HORIZONS = (252, 504, 756)
POLICY_HASH = "11A639CA376DE3C1205F6F22EF312210E5A8620D549431168A7CCA67C5419D73"
PREDICTOR_HASH = "E110C20287CB1B9E2260E9DAA33C2F2A8B5CD290F11E20EB733B918F61F595DD"
CALENDAR_HASH = "7FE1CA16970AE0346C67120DD4F32BA3BEF039276B9800757D15D3744189AA2C"
RECEIPT_HASH = "B74761883F9395F1334B3F78983DB4237DF0F3F245F449EFFDC73F98FBB738AD"
REUSE_HASH = "2F3B706745B8E99F14037CC52C83FA360580761E462A307E11C6BB28DBEFD711"
INTENT_HASH = "641B9463500E26274C7DEC28C01ACD8B79957CA899F501DD2F0EA18AF36E7DE5"


def _d(value: object) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Finite Decimal required")
    return result


def _mean(values: list[Decimal]) -> Decimal:
    if not values:
        raise ValueError("Nonempty values required")
    return sum(values, Decimal(0)) / Decimal(len(values))


def _mdd(values: list[Decimal]) -> Decimal:
    peak, worst = values[0], Decimal(0)
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


def _load_payloads(storage: Path, receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payloads = {}
    for item in receipt["records"]:
        path = storage / "payloads" / item["symbol"] / f"{item['payloadContentHash']}.json"
        payload = json.loads(path.read_text())
        body = {key: value for key, value in payload.items() if key != "contentHash"}
        if canonical_hash(body) != item["payloadContentHash"]:
            raise ValueError("Yahoo payload hash drift")
        required = {
            "symbol": item["symbol"],
            "requestedStartDate": "2014-01-01",
            "requestedEndDate": "2026-07-28",
            "providerCode": "yfinance",
            "providerSchemaVersion": "yfinance-download-v1",
            "parserVersion": "yfinance-parser-v1.0.0",
        }
        if any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("Yahoo payload adapter/range drift")
        adjustment = payload.get("adjustment", {})
        if adjustment.get("policyVersion") != "YAHOO-ADJCLOSE-RATIO-OHLC-v1.0.0":
            raise ValueError("Yahoo adjustment policy drift")
        if adjustment.get("normalizedAdjustmentMode") != "TOTAL_RETURN_ADJUSTED":
            raise ValueError("Yahoo adjustment mode drift")
        payload_bars = payload.get("bars")
        dates = [row.get("tradingDate") for row in payload_bars]
        if dates != sorted(set(dates)) or len(dates) != payload.get("barCount"):
            raise ValueError("Yahoo bar cardinality/order drift")
        for row in payload_bars:
            for field in ("adjustedClose", "close"):
                if _d(row["raw"][field]) <= 0:
                    raise ValueError("Yahoo price domain drift")
            if _d(row["volume"]) < 0:
                raise ValueError("Yahoo volume domain drift")
        payloads[item["symbol"]] = payload
    if len(payloads) != 203:
        raise ValueError("Exactly 203 payloads required")
    return payloads


def _verify_artifact(value: dict[str, Any], expected_hash: str, label: str) -> None:
    body = {key: item for key, item in value.items() if key != "contentHash"}
    if value.get("contentHash") != expected_hash or canonical_hash(body) != expected_hash:
        raise ValueError(f"{label} hash drift")


def _validate_inputs(
    policy: dict[str, Any],
    predictor: dict[str, Any],
    calendar: dict[str, Any],
    receipt: dict[str, Any],
    reuse: dict[str, Any],
) -> None:
    for value, expected, label in (
        (policy, POLICY_HASH, "C9 policy"),
        (predictor, PREDICTOR_HASH, "C9 predictor"),
        (calendar, CALENDAR_HASH, "C7 calendar"),
        (receipt, RECEIPT_HASH, "C7 receipt"),
        (reuse, REUSE_HASH, "C8 reuse registry"),
    ):
        _verify_artifact(value, expected, label)
    bindings = policy.get("bindings", {})
    if bindings.get("predictorSeal") != PREDICTOR_HASH or bindings.get("calendar") != CALENDAR_HASH:
        raise ValueError("C9 policy binding drift")
    if bindings.get("c7Receipt") != RECEIPT_HASH:
        raise ValueError("C9 receipt binding drift")
    expected_dates = [item.isoformat() for item in DATES]
    if policy.get("dateSelection", {}).get("dates") != expected_dates:
        raise ValueError("C9 policy date drift")
    terminals = predictor.get("terminalRows", [])
    records = predictor.get("records", [])
    if len(terminals) != 191 * 9 or len(records) != 1385:
        raise ValueError("C9 predictor cardinality drift")
    for row in [*terminals, *records]:
        _verify_artifact(row, row.get("contentHash", ""), "C9 predictor row")
    terminal_keys = {(row["securityId"], row["decisionDate"]) for row in terminals}
    if len(terminal_keys) != 191 * 9 or {row["decisionDate"] for row in terminals} != set(
        expected_dates
    ):
        raise ValueError("C9 predictor terminal population drift")
    terminal_by_key = {(row["securityId"], row["decisionDate"]): row for row in terminals}
    record_keys = [(row["securityId"], row["decisionDate"]) for row in records]
    if len(set(record_keys)) != len(record_keys):
        raise ValueError("C9 ranked predictor duplicate key")
    for row in records:
        terminal = terminal_by_key[(row["securityId"], row["decisionDate"])]
        if terminal["state"] != "VALID" or row.get("terminalRowHash") != terminal["contentHash"]:
            raise ValueError("C9 ranked-to-terminal binding drift")
    for decision in expected_dates:
        ranked = sorted(
            (row for row in records if row["decisionDate"] == decision),
            key=lambda row: (-_d(row["value"]), row["securityId"]),
        )
        size, extreme = len(ranked), len(ranked) // 5
        for index, row in enumerate(ranked):
            expected_group = (
                "HIGH" if index < extreme else ("LOW" if index >= size - extreme else "MIDDLE")
            )
            if (
                row.get("ordinalRank") != index + 1
                or row.get("group") != expected_group
                or row.get("populationCount") != size
                or row.get("higherIsBetter") is not True
            ):
                raise ValueError("C9 ranked predictor recomputation drift")
    receipt_records = receipt.get("records", [])
    if len(receipt_records) != 203 or len({row["symbol"] for row in receipt_records}) != 203:
        raise ValueError("C7 receipt matrix drift")


def _run_confirmation(
    *,
    policy: dict[str, Any],
    predictor_seal: dict[str, Any],
    calendar: dict[str, Any],
    receipt: dict[str, Any],
    intent: dict[str, Any],
    storage: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if policy["outcomesReadBeforeIntent"] is not False:
        raise ValueError("C9 policy was not pre-outcome")
    reuse = json.loads((storage / "stage7c8-reuse-registry.json").read_text())
    _validate_inputs(policy, predictor_seal, calendar, receipt, reuse)
    _verify_artifact(intent, INTENT_HASH, "C9 outcome access intent")
    if (
        intent.get("policyHash") != policy["contentHash"]
        or intent.get("predictorSealHash") != predictor_seal["contentHash"]
        or intent.get("calendarHash") != calendar["contentHash"]
        or intent.get("receiptHash") != receipt["contentHash"]
    ):
        raise ValueError("C9 outcome intent binding drift")
    payloads = _load_payloads(storage, receipt)
    bars = {
        symbol: {item["tradingDate"]: item for item in payload["bars"]}
        for symbol, payload in payloads.items()
    }
    sessions = sorted(bars["SPY"])
    selection = select_dates(sessions, set(C8_DATES), calendar)
    if selection["contentHash"] != policy["dateSelection"]["selectionArtifactHash"]:
        raise ValueError("C9 date selection artifact drift")
    valid_by_key = {
        (item["securityId"], item["decisionDate"]): item for item in predictor_seal["records"]
    }
    terminal_predictors = predictor_seal["terminalRows"]
    terminal_rows: list[dict[str, Any]] = []
    path_cache: dict[tuple[str, str, int], list[Decimal]] = {}
    resolved = {}
    for decision in policy["dateSelection"]["dates"]:
        later = [item for item in sessions if item > decision]
        if len(later) <= 756:
            raise ValueError("Unmatured C9 date")
        resolved[decision] = {"entry": later[0], "exits": {h: later[h] for h in HORIZONS}}
    prelim: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for terminal in terminal_predictors:
        security_id, decision = terminal["securityId"], terminal["decisionDate"]
        predictor = valid_by_key.get((security_id, decision))
        for horizon in HORIZONS:
            base: dict[str, Any] = {
                "securityId": security_id,
                "symbol": terminal["symbol"],
                "decisionDate": decision,
                "horizonSessions": horizon,
                "predictorTerminalHash": terminal["contentHash"],
                "fundamentalSourceHash": terminal["sourceHash"],
                "outcomePayloadHash": payloads[terminal["symbol"]]["contentHash"],
                "entrySession": resolved[decision]["entry"],
                "exitSession": resolved[decision]["exits"][horizon],
            }
            if predictor is None:
                row = {
                    **base,
                    "state": "MISSING",
                    "reason": f"PREDICTOR_{terminal['reason']}",
                }
                row["contentHash"] = canonical_hash(row)
                terminal_rows.append(row)
                continue
            symbol_bars = bars[terminal["symbol"]]
            entry, exit_value = base["entrySession"], base["exitSession"]
            path_dates = sessions[sessions.index(entry) : sessions.index(exit_value) + 1]
            prior = [symbol_bars[item] for item in sorted(symbol_bars) if item < entry]
            if len(prior) < 60:
                row = {
                    **base,
                    "predictorHash": predictor["contentHash"],
                    "group": predictor["group"],
                    "ordinalRank": predictor["ordinalRank"],
                    "state": "MISSING",
                    "reason": "LIQUIDITY_HISTORY_MISSING",
                }
                row["contentHash"] = canonical_hash(row)
                terminal_rows.append(row)
                continue
            if any(item not in symbol_bars for item in path_dates):
                row = {
                    **base,
                    "predictorHash": predictor["contentHash"],
                    "group": predictor["group"],
                    "ordinalRank": predictor["ordinalRank"],
                    "state": "MISSING",
                    "reason": "MISSING_TERMINAL_EVENT_UNPROVEN",
                }
                row["contentHash"] = canonical_hash(row)
                terminal_rows.append(row)
                continue
            liquidity = prior[-60:]
            adv_values = [_d(item["raw"]["close"]) * _d(item["volume"]) for item in liquidity]
            if any(value <= 0 for value in adv_values):
                row = {
                    **base,
                    "predictorHash": predictor["contentHash"],
                    "group": predictor["group"],
                    "ordinalRank": predictor["ordinalRank"],
                    "state": "MISSING",
                    "reason": "INVALID_LIQUIDITY_OBSERVATION",
                }
                row["contentHash"] = canonical_hash(row)
                terminal_rows.append(row)
                continue
            wealth = [
                _d(symbol_bars[item]["raw"]["adjustedClose"])
                / _d(symbol_bars[entry]["raw"]["adjustedClose"])
                for item in path_dates
            ]
            path_cache[(security_id, decision, horizon)] = wealth
            prelim[(decision, horizon)].append(
                {
                    "base": base,
                    "predictor": predictor,
                    "adv": _mean(adv_values),
                    "gross": wealth[-1] - 1,
                    "payloadHash": payloads[terminal["symbol"]]["contentHash"],
                    "liquidityHash": canonical_hash([item["tradingDate"] for item in liquidity]),
                    "pathHash": canonical_hash([str(item) for item in wealth]),
                }
            )
    for _key, rows in prelim.items():
        counts = defaultdict(int)
        for item in rows:
            counts[item["predictor"]["group"]] += 1
        for item in rows:
            predictor, base = item["predictor"], item["base"]
            cost = cost_rate(Decimal(100000) / Decimal(counts[predictor["group"]]), item["adv"])
            row = {
                **base,
                "predictorHash": predictor["contentHash"],
                "group": predictor["group"],
                "ordinalRank": predictor["ordinalRank"],
                "state": "USABLE",
                "reason": "VALID",
                "payloadHash": item["payloadHash"],
                "liquidityWindowHash": item["liquidityHash"],
                "pathHash": item["pathHash"],
                "averageDailyDollarVolume": str(item["adv"]),
                "orderNotional": str(Decimal(100000) / Decimal(counts[predictor["group"]])),
                "grossTotalReturn": str(item["gross"]),
                "costRate": str(cost),
                "netTotalReturn": str(item["gross"] - cost),
            }
            row["contentHash"] = canonical_hash(row)
            terminal_rows.append(row)
    terminal_rows.sort(
        key=lambda item: (item["decisionDate"], item["horizonSessions"], item["securityId"])
    )
    actual_keys = {
        (item["securityId"], item["decisionDate"], item["horizonSessions"])
        for item in terminal_rows
    }
    expected_keys = {
        (item["securityId"], item["decisionDate"], horizon)
        for item in terminal_predictors
        for horizon in HORIZONS
    }
    if len(terminal_rows) != 191 * 9 * 3 or actual_keys != expected_keys:
        raise ValueError("C9 terminal registry cardinality failure")
    numeric_fields = {
        "averageDailyDollarVolume",
        "orderNotional",
        "grossTotalReturn",
        "costRate",
        "netTotalReturn",
        "pathHash",
        "liquidityWindowHash",
    }
    if any(row["state"] == "MISSING" and numeric_fields.intersection(row) for row in terminal_rows):
        raise ValueError("C9 missing terminal row contains numeric outcome")
    registry: dict[str, Any] = {
        "schemaVersion": "FV-STAGE7C9-TERMINAL-REGISTRY-v1.0.0",
        "policyHash": policy["contentHash"],
        "predictorSealHash": predictor_seal["contentHash"],
        "calendarHash": calendar["contentHash"],
        "receiptHash": receipt["contentHash"],
        "outcomeAccessIntentHash": intent["contentHash"],
        "expectedRowCount": 5157,
        "terminalKeySetHash": canonical_hash(
            [
                [item["securityId"], item["decisionDate"], item["horizonSessions"]]
                for item in terminal_rows
            ]
        ),
        "stateReasonCounts": {
            f"{state}|{reason}": sum(
                item["state"] == state and item["reason"] == reason for item in terminal_rows
            )
            for state, reason in sorted({(item["state"], item["reason"]) for item in terminal_rows})
        },
        "rows": terminal_rows,
    }
    registry["contentHash"] = canonical_hash(registry)

    aggregates = []
    for decision in policy["dateSelection"]["dates"]:
        for horizon in HORIZONS:
            population = [
                item for item in predictor_seal["records"] if item["decisionDate"] == decision
            ]
            usable = [
                item
                for item in terminal_rows
                if item["decisionDate"] == decision
                and item["horizonSessions"] == horizon
                and item["state"] == "USABLE"
            ]
            sealed_groups = defaultdict(int)
            usable_groups = defaultdict(int)
            for item in population:
                sealed_groups[item["group"]] += 1
            for item in usable:
                usable_groups[item["group"]] += 1
            coverage = Decimal(len(usable)) / Decimal(len(population))
            eligible = (
                len(usable) >= 100
                and coverage >= Decimal("0.90")
                and usable_groups["HIGH"] >= 20
                and usable_groups["LOW"] >= 20
                and Decimal(usable_groups["HIGH"]) / sealed_groups["HIGH"] >= Decimal("0.90")
                and Decimal(usable_groups["LOW"]) / sealed_groups["LOW"] >= Decimal("0.90")
            )
            groups = {}
            entry, exit_value = resolved[decision]["entry"], resolved[decision]["exits"][horizon]
            path_dates = sessions[sessions.index(entry) : sessions.index(exit_value) + 1]
            spy_wealth = [
                _d(bars["SPY"][item]["raw"]["adjustedClose"])
                / _d(bars["SPY"][entry]["raw"]["adjustedClose"])
                for item in path_dates
            ]
            spy_prior = [bars["SPY"][item] for item in sessions if item < entry][-60:]
            spy_adv = _mean([_d(x["raw"]["close"]) * _d(x["volume"]) for x in spy_prior])
            for group in ("HIGH", "MIDDLE", "LOW"):
                rows = [item for item in usable if item["group"] == group]
                if not rows:
                    groups[group] = {
                        "state": "NOT_OBSERVED",
                        "sealed": sealed_groups[group],
                        "usable": 0,
                    }
                    continue
                gross = _mean([_d(x["grossTotalReturn"]) for x in rows])
                cost = _mean([_d(x["costRate"]) for x in rows])
                net = gross - cost
                wealth = [
                    _mean([path_cache[(x["securityId"], decision, horizon)][i] for x in rows])
                    for i in range(len(path_dates))
                ]
                spy_cost = cost_rate(Decimal(100000), spy_adv)
                spy_net = spy_wealth[-1] - 1 - spy_cost
                hit_spy_cost = cost_rate(Decimal(100000) / Decimal(len(rows)), spy_adv)
                hit_spy_net = spy_wealth[-1] - 1 - hit_spy_cost
                hit_count = sum(_d(item["netTotalReturn"]) > hit_spy_net for item in rows)
                severe_count = sum(_d(item["netTotalReturn"]) <= Decimal("-0.30") for item in rows)
                daily = [wealth[i] / wealth[i - 1] - 1 for i in range(1, len(wealth))]
                spy_daily = [
                    spy_wealth[i] / spy_wealth[i - 1] - 1 for i in range(1, len(spy_wealth))
                ]
                down = [i for i, v in enumerate(spy_daily) if v < 0]
                downside = None
                if len(down) >= 20 and _mean([spy_daily[i] for i in down]) != 0:
                    downside = _mean([daily[i] for i in down]) / _mean([spy_daily[i] for i in down])
                groups[group] = {
                    "state": "OBSERVED",
                    "sealed": sealed_groups[group],
                    "usable": len(rows),
                    "coverage": str(Decimal(len(rows)) / sealed_groups[group]),
                    "grossTotalReturn": str(gross),
                    "costContribution": str(cost),
                    "netTotalReturn": str(net),
                    "netAnnualizedReturn": str(annualize_total_return(net, horizon // 252)),
                    "spyNetAnnualizedReturn": str(annualize_total_return(spy_net, horizon // 252)),
                    "netAnnualizedSpyExcess": str(
                        annualize_total_return(net, horizon // 252)
                        - annualize_total_return(spy_net, horizon // 252)
                    ),
                    "grossMdd": str(_mdd(wealth)),
                    "spyGrossMdd": str(_mdd(spy_wealth)),
                    "downsideCapture": None if downside is None else str(downside),
                    "hitCount": hit_count,
                    "hitDenominator": len(rows),
                    "hitRate": str(Decimal(hit_count) / Decimal(len(rows))),
                    "severeLossCount": severe_count,
                    "severeLossDenominator": len(rows),
                    "severeLossFrequency": str(Decimal(severe_count) / Decimal(len(rows))),
                }
            predictor_ranks = {x["securityId"]: int(x["ordinalRank"]) for x in usable}
            returns = {x["securityId"]: _d(x["netTotalReturn"]) for x in usable}
            predictor_scores = {
                item["securityId"]: _d(valid_by_key[(item["securityId"], decision)]["value"])
                for item in usable
            }
            ic = ordinal_correlation(predictor_ranks, returns, predictor_scores)
            aggregate = {
                "decisionDate": decision,
                "dateType": "PRIMARY_CONFIRMATORY_DEVELOPMENT",
                "horizonSessions": horizon,
                "sealedPredictors": len(population),
                "completePairs": len(usable),
                "coverage": str(coverage),
                "state": "ELIGIBLE" if eligible else "INSUFFICIENT_OUTCOME_COVERAGE",
                "deterministicOrdinalRankCorrelation": None if ic is None else str(ic),
                "groups": groups,
                "sectorDiagnostic": {
                    "state": "NOT_OBSERVED",
                    "reason": "CURRENT_CLASSIFICATION_MAPPING_NOT_BOUND_TO_C9_PREDICTOR_SEAL",
                    "thresholdEligible": False,
                },
            }
            if groups["HIGH"]["state"] == "OBSERVED" and groups["LOW"]["state"] == "OBSERVED":
                aggregate["highMinusLowNetAnnualized"] = str(
                    _d(groups["HIGH"]["netAnnualizedReturn"])
                    - _d(groups["LOW"]["netAnnualizedReturn"])
                )
            aggregates.append(aggregate)
    result: dict[str, Any] = {
        "schemaVersion": "FV-STAGE7C9-RESULT-v1.0.0",
        "policyHash": policy["contentHash"],
        "terminalRegistryHash": registry["contentHash"],
        "outcomeAccessIntentHash": intent["contentHash"],
        "claim": "DEVELOPMENT_CONFIRMATORY_AFTER_PROTOCOL_REPAIR_CURRENT_REVISION_APPROXIMATION",
        "dateHorizonResults": aggregates,
        "providerValuesIncluded": False,
    }
    result["contentHash"] = canonical_hash(result)
    return registry, result


def run_confirmation(
    *,
    policy: dict[str, Any],
    predictor_seal: dict[str, Any],
    calendar: dict[str, Any],
    receipt: dict[str, Any],
    intent: dict[str, Any],
    storage: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replay C9 under its sealed arithmetic context, isolated from the caller."""
    with localcontext(ARITHMETIC_CONTEXT):
        return _run_confirmation(
            policy=policy,
            predictor_seal=predictor_seal,
            calendar=calendar,
            receipt=receipt,
            intent=intent,
            storage=storage,
        )
