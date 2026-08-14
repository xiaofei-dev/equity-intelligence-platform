"""Final Stage 7 C9 confirmatory protocol and deterministic runner."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from pathlib import Path
from typing import Any

from equity_analysis.historical_validation.provider_backtest_coverage_v1 import (
    _completed_fundamentals_events,
    _load_object,
    _resolve_raw_fundamentals,
    _transport_fundamentals_evidence,
    _verify_artifact,
)
from equity_analysis.historical_validation.provider_backtest_preflight_v1 import (
    CACHED_TRANSPORT_AUDIT_PATH,
)

from .historical_provider_native_company_quality_v1 import (
    _company_quality,
    _routing_state,
    build_provider_native_contract,
    produce_values,
)
from .historical_quarterly_semantics_support_v1 import canonical_hash

VERSION = "FV-STAGE7C9-CONFIRMATION-v1.0.0"
ARITHMETIC_VERSION = "FV-STAGE7C9-DECIMAL-ARITHMETIC-v1.0.0"
ARITHMETIC_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
DATE_VERSION = "FV-STAGE7C9-FRESH-DATE-SELECTION-v1.0.0"
DATES = tuple(
    date.fromisoformat(value)
    for value in (
        "2015-11-12",
        "2016-10-06",
        "2017-12-26",
        "2018-11-06",
        "2019-11-25",
        "2020-11-06",
        "2021-10-22",
        "2022-11-17",
        "2023-01-09",
    )
)
DATE_SELECTION_HASH = "124596447E3FE8C5E28D5EC9320F6B34C0C390C579723B6806A7DE2FCBF1FE3B"
C5_IDENTITY_HASH = "B29306CE3B1A047C074B68FDA07149FFF72F7B2ECD2BC0D78AAD7B42692656C7"
C7_CALENDAR_HASH = "7FE1CA16970AE0346C67120DD4F32BA3BEF039276B9800757D15D3744189AA2C"
C8_DATES = frozenset(
    {
        "2015-05-07",
        "2016-05-19",
        "2017-06-30",
        "2018-04-09",
        "2019-06-21",
        "2020-04-20",
        "2021-06-02",
        "2022-05-18",
        "2023-05-18",
        "2018-09-20",
        "2020-02-19",
        "2022-01-03",
    }
)


def select_dates(
    sessions: list[str], excluded: set[str], calendar: dict[str, Any]
) -> dict[str, Any]:
    calendar_body = {key: value for key, value in calendar.items() if key != "contentHash"}
    if (
        calendar.get("contentHash") != C7_CALENDAR_HASH
        or canonical_hash(calendar_body) != C7_CALENDAR_HASH
    ):
        raise ValueError("Exact sealed C7 calendar required")
    if sessions != sorted(set(sessions)) or not sessions:
        raise ValueError("Calendar sessions must be sorted and unique")
    for session in sessions:
        date.fromisoformat(session)
    if canonical_hash(sessions) != calendar.get("orderedSessionSetHash"):
        raise ValueError("Calendar ordered session set hash drift")
    if excluded != C8_DATES:
        raise ValueError("Exact twelve-date C8 exclusion set required")
    selected = []
    for year in range(2015, 2023):
        candidates = [
            item
            for item in sessions
            if item[:4] == str(year)
            and 10 <= int(item[5:7]) <= 12
            and item not in excluded
            and sum(value > item for value in sessions) > 756
        ]
        if not candidates:
            raise ValueError(f"No matured Q4 candidate for {year}")
        selected.append(
            min(candidates, key=lambda item: (canonical_hash([DATE_VERSION, year, item]), item))
        )
    candidates = [
        item
        for item in sessions
        if item[:4] == "2023"
        and 1 <= int(item[5:7]) <= 3
        and item not in excluded
        and sum(value > item for value in sessions) > 756
    ]
    if not candidates:
        raise ValueError("No matured Q1 candidate for 2023")
    selected.append(
        min(candidates, key=lambda item: (canonical_hash([DATE_VERSION, 2023, item]), item))
    )
    body: dict[str, Any] = {
        "version": DATE_VERSION,
        "tupleEncoding": "CANONICAL_JSON_ARRAY",
        "dates": sorted(selected),
        "calendarHash": C7_CALENDAR_HASH,
    }
    body["contentHash"] = canonical_hash(body)
    return body


def build_predictor_seal(
    repository: Path, controlled_root: Path, identities: dict[str, str]
) -> dict[str, Any]:
    if len(identities) != 191 or canonical_hash(sorted(identities)) != C5_IDENTITY_HASH:
        raise ValueError("Exact C5 identity population required")
    transport = _load_object(controlled_root / CACHED_TRANSPORT_AUDIT_PATH)
    _verify_artifact(transport, label="C9_CACHED_TRANSPORT")
    evidence = _transport_fundamentals_evidence(transport)
    events = _completed_fundamentals_events(controlled_root)
    cache: dict[str, tuple[dict[str, Any], str]] = {}

    def payload(symbol: str) -> tuple[dict[str, Any], str]:
        if symbol not in cache:
            raw, binding = _resolve_raw_fundamentals(
                repository_root=controlled_root,
                symbol=symbol,
                evidence=evidence[symbol],
                completed_events=events,
            )
            cache[symbol] = (raw, str(binding["responseContentHash"]))
        return cache[symbol]

    terminal, valid = [], []
    for cutoff in DATES:
        for security_id, symbol in sorted(identities.items()):
            raw, source_hash = payload(symbol)
            routing = _routing_state(raw)
            reason = routing
            score = None
            if routing == "GENERIC_ELIGIBLE":
                values, reasons = produce_values(raw, cutoff)
                score = _company_quality(values)
                reason = (
                    "VALID"
                    if score is not None
                    else ";".join(
                        f"{key}:{value}"
                        for key, value in sorted(reasons.items())
                        if value != "VALID"
                    )
                    or "COMPONENT_MISSING"
                )
            row: dict[str, Any] = {
                "securityId": security_id,
                "symbol": symbol,
                "decisionDate": cutoff.isoformat(),
                "sourceHash": source_hash,
                "state": "VALID" if score is not None else "MISSING",
                "reason": reason,
            }
            row["contentHash"] = canonical_hash(row)
            terminal.append(row)
            if score is not None:
                valid.append({**row, "value": str(score)})
    ranked = []
    for cutoff in DATES:
        rows = [item for item in valid if item["decisionDate"] == cutoff.isoformat()]
        ordered = sorted(rows, key=lambda item: (-Decimal(item["value"]), item["securityId"]))
        n, extreme = len(ordered), len(ordered) // 5
        for index, item in enumerate(ordered):
            group = "HIGH" if index < extreme else ("LOW" if index >= n - extreme else "MIDDLE")
            terminal_row_hash = item["contentHash"]
            record = {
                **{key: value for key, value in item.items() if key != "contentHash"},
                "terminalRowHash": terminal_row_hash,
                "ordinalRank": index + 1,
                "populationCount": n,
                "group": group,
                "higherIsBetter": True,
            }
            record["contentHash"] = canonical_hash(record)
            ranked.append(record)
    counts = {
        item.isoformat(): sum(row["decisionDate"] == item.isoformat() for row in ranked)
        for item in DATES
    }
    body: dict[str, Any] = {
        "schemaVersion": "FV-STAGE7C9-PREDICTOR-SEAL-v1.0.0",
        "track": "DEVELOPMENT_CONFIRMATORY_AFTER_PROTOCOL_REPAIR",
        "availability": "CURRENT_REVISION_APPROXIMATION",
        "producerContractHash": build_provider_native_contract()["contentHash"],
        "dateSelectionHash": DATE_SELECTION_HASH,
        "identitySetHash": C5_IDENTITY_HASH,
        "terminalCount": len(terminal),
        "validCounts": counts,
        "outcomesReadBeforeSeal": False,
        "terminalRows": terminal,
        "records": ranked,
    }
    body["contentHash"] = canonical_hash(body)
    return body


def cost_rate(order_notional: Decimal, adv: Decimal) -> Decimal:
    with localcontext(ARITHMETIC_CONTEXT):
        if not order_notional.is_finite() or not adv.is_finite() or order_notional <= 0 or adv <= 0:
            raise ValueError("Positive finite order notional and ADTV required")
        participation = order_notional / adv
        impact = min(Decimal(50), Decimal(25) * participation.sqrt())
        return +(Decimal(2) + Decimal(2) * (Decimal(1) + impact)) / Decimal(10000)


def ordinal_correlation(
    predictor_ranks: dict[str, int],
    net_returns: dict[str, Decimal],
    predictor_scores: dict[str, Decimal],
) -> Decimal | None:
    with localcontext(ARITHMETIC_CONTEXT):
        if set(predictor_ranks) != set(net_returns) or set(predictor_ranks) != set(
            predictor_scores
        ):
            raise ValueError("Exact predictor/score/return identity pairing required")
        identities = sorted(predictor_ranks)
        if len(identities) < 100:
            return None
        ranks = [predictor_ranks[item] for item in identities]
        if any(type(rank) is not int or rank <= 0 for rank in ranks) or len(set(ranks)) != len(
            ranks
        ):
            raise ValueError("Predictor ranks must be unique positive sealed ordinals")
        raw_returns = [net_returns[item] for item in identities]
        raw_scores = [predictor_scores[item] for item in identities]
        if any(not value.is_finite() for value in [*raw_returns, *raw_scores]):
            raise ValueError("Finite predictor scores and realized returns required")
        if len(set(raw_returns)) == 1 or len(set(raw_scores)) == 1:
            return None
        ordered = sorted(identities, key=lambda item: (-net_returns[item], item))
        return_ranks = {security_id: index + 1 for index, security_id in enumerate(ordered)}
        xs = [Decimal(predictor_ranks[item]) for item in identities]
        ys = [Decimal(return_ranks[item]) for item in identities]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        dx, dy = [item - mx for item in xs], [item - my for item in ys]
        denominator = (sum(item * item for item in dx) * sum(item * item for item in dy)).sqrt()
        if denominator == 0:
            return None
        return +(sum(x * y for x, y in zip(dx, dy, strict=True)) / denominator)
