from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from equity_analysis.fundamental_value.historical_company_quality_pilot_v1 import (
    SEC_V4_PATH,
    bind_controlled_100_sec_intersection,
)
from equity_analysis.fundamental_value.historical_quarterly_semantics_support_v1 import (
    FIELD_MAPPINGS,
    ComparableFactV1,
    SupportEvidenceError,
    build_frozen_protocol,
    canonical_hash,
    compare_exact_cross_provider,
    compare_quarter_sums_to_annual,
)
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

REPLAY_VERSION = "FV-STAGE7C4R-QUARTERLY-SEMANTICS-REPLAY-v1.0.0"
CORRECT_SCREENSHOT_SHA256 = (
    "9F335DFDD59CDB2E53F90E4F21B18CB9D9DCF043B55CE98C2026E79377579C4B"
)
SAMPLE_SEED = "FV-STAGE7C4-SEMANTICS-SAMPLE-20260801-v1"


def seal_correct_support_evidence(path: Path) -> dict[str, object]:
    observed = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    if observed != CORRECT_SCREENSHOT_SHA256:
        raise SupportEvidenceError("C4R_SUPPORT_SCREENSHOT_HASH_DRIFT")
    body: dict[str, object] = {
        "schemaVersion": "FV-STAGE7C4R-SUPPORT-EVIDENCE-v1.0.0",
        "sourceType": "HUMAN_SUPPLIED_EODHD_SUPPORT_CHAT_SCREENSHOT",
        "fileSha256": CORRECT_SCREENSHOT_SHA256,
        "fileSizeBytes": 21767,
        "fileTimestampUtc": "2026-07-28T08:51:57Z",
        "quote": (
            "Financials values for the quarters are not cumulative. "
            "Restatement data is updated when possible."
        ),
        "quoteVisuallyCorroborated": True,
        "visibleContext": (
            "EODHD support chat links EODHD bulk fundamentals documentation."
        ),
        "provenance": "Human supplied; not independently obtained by provider API.",
        "supportLimitation": "Provider support statements may be incomplete or wrong.",
        "revisionLimitation": (
            "Restatements update current history; no immutable revision or strict PIT claim."
        ),
        "authorizedStratum": "CURRENT_REVISION_APPROXIMATION",
    }
    body["contentHash"] = canonical_hash(body)
    return body


def _sample20(intersection: dict[str, object]) -> tuple[dict[str, object], ...]:
    by_sector: dict[str, list[dict[str, object]]] = defaultdict(list)
    for raw in intersection["securities"]:
        row = dict(raw)
        by_sector[str(row["sector"])].append(row)
    for rows in by_sector.values():
        rows.sort(key=lambda item: (
            hashlib.sha256(
                f"{SAMPLE_SEED}|{item['securityId']}".encode()).hexdigest(),
            str(item["securityId"])))
    sectors = sorted(by_sector)
    selected: list[dict[str, object]] = []
    offset = 0
    while len(selected) < 20:
        progressed = False
        for sector in sectors:
            if offset < len(by_sector[sector]):
                selected.append(by_sector[sector][offset])
                progressed = True
                if len(selected) == 20:
                    break
        if not progressed:
            break
        offset += 1
    if len(selected) != 20 or len({str(item["sector"]) for item in selected}) < 8:
        raise SupportEvidenceError("C4R_SAMPLE_REQUIREMENT_FAILED")
    return tuple(selected)


def _decimal(value: object) -> Decimal | None:
    if value in (None, "", "NA", "None"):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _eodhd_facts(
    symbol: str, payload: dict[str, object], source_hash: str,
) -> tuple[list[ComparableFactV1], list[ComparableFactV1]]:
    quarterly: list[ComparableFactV1] = []
    annual: list[ComparableFactV1] = []
    financials = payload["Financials"]
    statement_for = {
        "revenue": "Income_Statement", "operating_income": "Income_Statement",
        "net_income": "Income_Statement", "operating_cash_flow": "Cash_Flow",
        "capital_expenditure": "Cash_Flow",
    }
    field_name = {field: FIELD_MAPPINGS[field][0].rsplit(".", 1)[1]
                  for field in FIELD_MAPPINGS}
    for field, statement in statement_for.items():
        data = financials[statement]
        annual_rows = sorted(
            (row for row in data["yearly"].values() if isinstance(row, dict)),
            key=lambda row: str(row.get("date")))
        annual_ends = [date.fromisoformat(str(row["date"])) for row in annual_rows]
        for index, row in enumerate(annual_rows):
            end = annual_ends[index]
            start = ((annual_ends[index - 1] + timedelta(days=1)) if index
                     else date(end.year, 1, 1))
            value = _decimal(row.get(field_name[field]))
            if value is None or row.get("currency_symbol") != "USD":
                continue
            if field == "capital_expenditure":
                value = abs(value)
            annual.append(ComparableFactV1(
                "EODHD", symbol, field, FIELD_MAPPINGS[field][0],
                FIELD_MAPPINGS[field][1], FIELD_MAPPINGS[field][2],
                f"{symbol}:{end.isoformat()}", start, end, end.year,
                "USD", "USD", value, source_hash))
        quarter_rows = sorted(
            (row for row in data["quarterly"].values() if isinstance(row, dict)),
            key=lambda row: str(row.get("date")))
        quarter_ends = [date.fromisoformat(str(row["date"])) for row in quarter_rows]
        for index, row in enumerate(quarter_rows):
            end = quarter_ends[index]
            prior_annual = max((item for item in annual_ends if item < end), default=None)
            candidates = [item for item in annual_ends if item >= end]
            if not candidates:
                continue
            fiscal_end = min(candidates)
            start = ((quarter_ends[index - 1] + timedelta(days=1))
                     if index and (prior_annual is None or quarter_ends[index - 1] > prior_annual)
                     else ((prior_annual + timedelta(days=1)) if prior_annual
                           else end - timedelta(days=89)))
            value = _decimal(row.get(field_name[field]))
            if value is None or row.get("currency_symbol") != "USD":
                continue
            if field == "capital_expenditure":
                value = abs(value)
            quarterly.append(ComparableFactV1(
                "EODHD", symbol, field, FIELD_MAPPINGS[field][0],
                FIELD_MAPPINGS[field][1], FIELD_MAPPINGS[field][2],
                f"{symbol}:{fiscal_end.isoformat()}", start, end, fiscal_end.year,
                "USD", "USD", value, source_hash))
    return quarterly, annual


def _sec_facts(symbol: str, payload: dict[str, object]) -> list[ComparableFactV1]:
    grouped: dict[tuple[str, date], list[dict[str, object]]] = defaultdict(list)
    for row in payload["observations"]:
        field = str(row.get("normalizedOperand"))
        if field not in FIELD_MAPPINGS or row.get("durationClass") != "DISCRETE_QUARTER":
            continue
        if row.get("unit") != "USD" or row.get("currency") != "USD":
            continue
        grouped[(field, date.fromisoformat(str(row["periodEnd"])))].append(row)
    result = []
    for (field, end), rows in grouped.items():
        selected = _select_sec_revision(rows)
        if selected is None:
            continue
        value = _decimal(selected.get("value"))
        if value is None:
            continue
        if field == "capital_expenditure":
            value = abs(value)
        result.append(ComparableFactV1(
            "SEC", symbol, field, FIELD_MAPPINGS[field][1],
            FIELD_MAPPINGS[field][1], FIELD_MAPPINGS[field][2],
            f"SEC:{symbol}:{selected.get('fiscalYear')}:{selected.get('fiscalPeriod')}",
            date.fromisoformat(str(selected["periodStart"])), end,
            int(selected.get("fiscalYear") or end.year), "USD", "USD", value,
            str(selected["contentHash"])))
    return result


def _select_sec_revision(
    rows: list[dict[str, object]],
) -> dict[str, object] | None:
    best_priority = min(int(row.get("mappingPriority", 999)) for row in rows)
    eligible = [row for row in rows
                if int(row.get("mappingPriority", 999)) == best_priority]
    latest_accepted = max(str(row.get("acceptedAt", "")) for row in eligible)
    latest = [row for row in eligible
              if str(row.get("acceptedAt", "")) == latest_accepted]
    semantic_fields = (
        "value", "periodStart", "periodEnd", "fiscalYear", "fiscalPeriod",
        "normalizedOperand", "taxonomy", "concept", "mappingPriority",
        "unit", "currency", "durationClass",
    )
    identities = {tuple(str(row.get(key)) for key in semantic_fields)
                  for row in latest}
    if len(identities) != 1:
        return None
    return min(latest, key=lambda row: str(row.get("contentHash")))


def run_empirical_semantics_audit(
    repository_root: Path, controlled_root: Path, screenshot_path: Path,
) -> dict[str, object]:
    support = seal_correct_support_evidence(screenshot_path)
    protocol = build_frozen_protocol()
    if protocol.content_hash != (
            "DCB4609B165C1467C91FE6EABBB3EEA5E8B5BE9B6A88DCEF10E93F534B28DF75"):
        raise SupportEvidenceError("FROZEN_C4_PROTOCOL_HASH_DRIFT")
    intersection = bind_controlled_100_sec_intersection(repository_root, controlled_root)
    sample = _sample20(intersection)
    audit = _load_object(controlled_root / CACHED_TRANSPORT_AUDIT_PATH)
    _verify_artifact(audit, label="C4R_CACHED_TRANSPORT")
    evidence = _transport_fundamentals_evidence(audit)
    events = _completed_fundamentals_events(controlled_root)
    sec_manifest = json.loads((repository_root / SEC_V4_PATH).read_text())
    sec_rows = {str(row["symbol"]).upper(): row for row in sec_manifest["securities"]
                if row.get("status") == "SEC_TIMELINE_BUILT"}
    cross_summaries = []
    annual_summaries = []
    per_field = {field: {"matched": 0, "agreed": 0, "contradicted": 0}
                 for field in FIELD_MAPPINGS}
    for identity in sample:
        symbol = str(identity["symbol"]).upper()
        raw, transport = _resolve_raw_fundamentals(
            repository_root=controlled_root, symbol=symbol,
            evidence=evidence[symbol], completed_events=events)
        eod_quarters, eod_annual = _eodhd_facts(
            symbol, raw, str(transport["responseContentHash"]))
        sec_row = sec_rows.get(symbol)
        if sec_row is None:
            continue
        sec_path = controlled_root / str(sec_row["storageReference"])
        sec_payload = json.loads(sec_path.read_text())
        if canonical_hash(sec_payload) != str(sec_row["payloadContentHash"]):
            raise SupportEvidenceError("C4R_SEC_PAYLOAD_HASH_DRIFT")
        sec_facts = _sec_facts(symbol, sec_payload)
        for field in FIELD_MAPPINGS:
            cross = compare_exact_cross_provider(
                [x for x in eod_quarters if x.field == field],
                [x for x in sec_facts if x.field == field], protocol)
            cross_summaries.append((symbol, field, cross))
            per_field[field]["matched"] += int(cross["matchedCount"])
            per_field[field]["agreed"] += int(cross["agreementCount"])
            per_field[field]["contradicted"] += int(cross["contradictionCount"])
        annual_summaries.append((symbol, compare_quarter_sums_to_annual(
            eod_quarters, eod_annual, protocol)))
    matched = sum(item["matched"] for item in per_field.values())
    agreed = sum(item["agreed"] for item in per_field.values())
    annual_matched = sum(int(item[1]["matchedFiscalFieldYears"])
                         for item in annual_summaries)
    annual_agreed = sum(int(item[1]["agreementCount"]) for item in annual_summaries)
    field_rates = {field: (Decimal(row["agreed"]) / row["matched"]
                           if row["matched"] else None)
                   for field, row in per_field.items()}
    cross_rate = Decimal(agreed) / matched if matched else None
    annual_rate = Decimal(annual_agreed) / annual_matched if annual_matched else None
    passed = (matched >= protocol.minimum_cross_provider_matches
              and annual_matched >= protocol.minimum_annual_comparisons
              and cross_rate is not None and cross_rate >= protocol.minimum_overall_agreement
              and annual_rate is not None and annual_rate >= protocol.minimum_overall_agreement
              and all(rate is not None and rate >= protocol.minimum_per_field_agreement
                      for rate in field_rates.values())
              and (Decimal(matched - agreed) / matched
                   <= protocol.maximum_systematic_contradiction_rate))
    body: dict[str, object] = {
        "schemaVersion": REPLAY_VERSION, "supportEvidence": support,
        "frozenProtocolHash": protocol.content_hash,
        "sampleSecurityCount": len(sample),
        "sampleSectorCount": len({str(item["sector"]) for item in sample}),
        "sampleSecuritySetHash": canonical_hash(sorted(str(x["securityId"]) for x in sample)),
        "crossProvider": {"matched": matched, "agreed": agreed,
            "contradicted": matched - agreed, "agreementRate": cross_rate,
            "perField": per_field, "perFieldRates": field_rates},
        "annualQuarterSum": {"matched": annual_matched, "agreed": annual_agreed,
            "contradicted": annual_matched - annual_agreed, "agreementRate": annual_rate},
        "semanticGate": "PASSED" if passed else "FAILED_OR_INSUFFICIENT",
        "approximationReplay": "AUTHORIZED_NOT_RUN" if passed else "NOT_RUN",
        "providerValuesIncluded": False, "outcomesRead": False,
        "networkRequests": 0, "databaseRequests": 0,
    }
    body["contentHash"] = canonical_hash(body)
    return body
