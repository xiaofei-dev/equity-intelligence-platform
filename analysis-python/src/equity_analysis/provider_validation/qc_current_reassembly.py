from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.current_factor_windows_v1 import (
    QC_FACTOR_REQUIREMENTS,
    UQ_FACTOR_REQUIREMENTS,
    _current_provider_field_status,
    _derive_arithmetic,
    _derived_ratio,
    _earnings_yield_source_status,
    _factor_status,
    _status,
)
from equity_analysis.provider_validation.eodhd_interest_semantics_audit import (
    _fundamentals_events,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    file_hash,
    write_immutable_json,
)
from equity_analysis.provider_validation.objective_rating_semantics_audit import (
    _load_response,
)

SCHEMA_VERSION = "objective-rating-current-factor-input-manifest-v1.7.0"
SNAPSHOT_VERSION = "objective-rating-current-factor-input-v1.5.0"
WINDOW_POLICY_VERSION = "objective-rating-current-factor-window-v1.5.0"
SOURCE_MANIFEST = (
    "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-5.json"
)
MACHINE_POLICY = (
    "docs/generated/objective-rating-v1-qc-current-input-policy-v1.json"
)
EXPECTED_POLICY_FILE_SHA = (
    "FFFF26EB8FEA82B76BDAFBCFFD96F19BD1FEC668B902B5C04AD530E25C334FD7"
)
EXPECTED_POLICY_CONTENT_HASH = (
    "997F37C2BE1DBBD8A05F7AF49AD60B0928D56F012FB8F5FD6531AFCD68F74BBA"
)
FRESHNESS_DAYS = 150
CURRENT_DURATION_OPERANDS = (
    "capital_expenditure_ttm",
    "diluted_weighted_average_shares_ttm",
    "gross_profit_ttm",
    "income_tax_ttm",
    "interest_expense_ttm",
    "net_income_ttm",
    "operating_cash_flow_ttm",
    "operating_income_ttm",
    "pretax_income_ttm",
    "revenue_ttm",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_artifact(payload: dict[str, Any], expected: str, code: str) -> None:
    actual = canonical_hash(
        {key: value for key, value in payload.items() if key != "artifactContentHash"}
    )
    if payload.get("artifactContentHash") != expected or actual != expected:
        raise ValueError(f"{code}_CANONICAL_HASH_MISMATCH")


def _verify_snapshot(payload: dict[str, Any], expected: str, code: str) -> None:
    actual = canonical_hash(
        {key: value for key, value in payload.items() if key != "contentHash"}
    )
    if payload.get("contentHash") != expected or actual != expected:
        raise ValueError(f"{code}_CONTENT_HASH_MISMATCH")


def _latest_period_end(operand: dict[str, Any]) -> date | None:
    dates = []
    for period_id in operand.get("periodIds", ()):
        candidate = str(period_id).rsplit(":", maxsplit=1)[-1]
        try:
            dates.append(date.fromisoformat(candidate))
        except ValueError:
            continue
    return max(dates) if dates else None


def _demote_stale_current_operands(
    operands: dict[str, dict[str, Any]],
    *,
    cutoff: datetime,
) -> None:
    for name in CURRENT_DURATION_OPERANDS:
        operand = operands[name]
        if operand["status"] != "VALID":
            continue
        period_end = _latest_period_end(operand)
        if period_end and (cutoff.date() - period_end).days > FRESHNESS_DAYS:
            operands[name] = _status(
                "MISSING",
                "CURRENT_TTM_EXCEEDS_FROZEN_150_DAY_FRESHNESS",
            )


def _refresh_current_derivations(
    operands: dict[str, dict[str, Any]],
    provider_fields: dict[str, dict[str, Any]],
) -> None:
    for name in ("revenue_ttm", "gross_profit_ttm"):
        candidate = provider_fields.get(name)
        if (
            operands[name]["status"] != "VALID"
            and candidate
            and candidate["status"] == "VALID"
        ):
            operands[name] = candidate

    operands["fcf_ttm"] = _derive_arithmetic(
        [operands["operating_cash_flow_ttm"], operands["capital_expenditure_ttm"]],
        operation="SUBTRACT",
        reason="FCF_TTM_INPUT_WINDOW_MISSING",
    )
    operands["gross_margin_ttm"] = _derived_ratio(
        operands["gross_profit_ttm"],
        operands["revenue_ttm"],
        reason="GROSS_MARGIN_TTM_INPUT_WINDOW_MISSING",
    )
    operands["operating_margin_ttm"] = _derived_ratio(
        operands["operating_income_ttm"],
        operands["revenue_ttm"],
        reason="OPERATING_MARGIN_TTM_INPUT_WINDOW_MISSING",
    )
    operands["diluted_weighted_average_shares_current"] = operands[
        "diluted_weighted_average_shares_ttm"
    ]
    provider_eps = provider_fields.get("diluted_eps_current")
    operands["diluted_eps_current"] = (
        provider_eps
        if provider_eps and provider_eps["status"] == "VALID"
        else _derived_ratio(
            operands["net_income_ttm"],
            operands["diluted_weighted_average_shares_current"],
            reason="CURRENT_DILUTED_EPS_INPUT_WINDOW_MISSING",
        )
    )
    operands["fcf_per_diluted_share_current"] = _derived_ratio(
        operands["fcf_ttm"],
        operands["diluted_weighted_average_shares_current"],
        reason="CURRENT_FCF_PER_SHARE_INPUT_WINDOW_MISSING",
    )
    operands["ebit_ttm"] = operands["operating_income_ttm"]


def _refresh_factor_statuses(payload: dict[str, Any]) -> None:
    operands = payload["operands"]
    qc = {
        name: _factor_status(requirements, operands)
        for name, requirements in QC_FACTOR_REQUIREMENTS.items()
    }
    earnings_raw = _earnings_yield_source_status(operands)
    fcf_raw = _factor_status(UQ_FACTOR_REQUIREMENTS["fcf_yield"], operands)
    qc["valuation_guardrail"] = {
        "status": (
            "VALID"
            if earnings_raw["status"] == fcf_raw["status"] == "VALID"
            else "MISSING"
        ),
        "reasonCode": (
            "RAW_VALUATION_INPUTS_VALID_COHORT_PERCENTILES_DEFERRED"
            if earnings_raw["status"] == fcf_raw["status"] == "VALID"
            else "RAW_VALUATION_INPUTS_MISSING"
        ),
        "requiredOperands": list(QC_FACTOR_REQUIREMENTS["valuation_guardrail"]),
        "blockingOperands": (
            []
            if earnings_raw["status"] == fcf_raw["status"] == "VALID"
            else earnings_raw["blockingOperands"] + fcf_raw["blockingOperands"]
        ),
    }
    uq = {
        name: _factor_status(requirements, operands)
        for name, requirements in UQ_FACTOR_REQUIREMENTS.items()
    }
    uq["earnings_yield"] = earnings_raw
    payload["qcFactors"] = qc
    payload["uqFactors"] = uq
    payload["currentQcInputReady"] = all(
        factor["status"] == "VALID" for factor in qc.values()
    )
    payload["currentUqInputReady"] = all(
        factor["status"] == "VALID" for factor in uq.values()
    )


def build_reassembled_manifest(
    *,
    repository_root: Path,
    output_path: Path,
    storage_root: Path,
) -> dict[str, Any]:
    policy_path = repository_root / MACHINE_POLICY
    if file_hash(policy_path) != EXPECTED_POLICY_FILE_SHA:
        raise ValueError("MACHINE_POLICY_FILE_HASH_MISMATCH")
    policy = _load(policy_path)
    _verify_artifact(
        policy,
        EXPECTED_POLICY_CONTENT_HASH,
        "MACHINE_POLICY",
    )
    source_path = repository_root / SOURCE_MANIFEST
    source = _load(source_path)
    _verify_artifact(
        source,
        source["artifactContentHash"],
        "SOURCE_MANIFEST",
    )
    if len(source["securities"]) != 55:
        raise ValueError("SOURCE_SECURITY_COUNT_NOT_55")

    cutoff = datetime.fromisoformat(source["cutoff"].replace("Z", "+00:00"))
    events = _fundamentals_events(repository_root)
    records = []
    qc_ready = 0
    factor_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for item in source["securities"]:
        symbol = item["symbol"]
        source_snapshot = _load(repository_root / item["storageReference"])
        _verify_snapshot(
            source_snapshot,
            item["payloadContentHash"],
            f"SOURCE_SNAPSHOT[{symbol}]",
        )
        payload = deepcopy(source_snapshot)
        payload.pop("contentHash", None)
        payload["schemaVersion"] = SNAPSHOT_VERSION
        payload["windowPolicyVersion"] = WINDOW_POLICY_VERSION
        payload["sourceSnapshot"] = {
            "storageReference": item["storageReference"],
            "contentHash": item["payloadContentHash"],
        }
        _demote_stale_current_operands(payload["operands"], cutoff=cutoff)

        provider_fields: dict[str, dict[str, Any]] = {}
        event = events.get(symbol)
        if event:
            response = _load_response(event, repository_root)
            for provider_path, operand_name in (
                ("Highlights.DilutedEpsTTM", "diluted_eps_current"),
                ("Highlights.RevenueTTM", "revenue_ttm"),
                ("Highlights.GrossProfitTTM", "gross_profit_ttm"),
            ):
                provider_fields[operand_name] = _current_provider_field_status(
                    symbol=symbol,
                    response=response,
                    event=event,
                    provider_path=provider_path,
                    cutoff=cutoff,
                )
        _refresh_current_derivations(payload["operands"], provider_fields)
        _refresh_factor_statuses(payload)
        payload["contentHash"] = canonical_hash(payload)
        destination = storage_root / symbol / f"{payload['contentHash']}.json"
        write_immutable_json(destination, payload)
        qc_ready += int(payload["currentQcInputReady"])
        for factor, result in payload["qcFactors"].items():
            factor_counts[factor][result["status"]] += 1
        records.append(
            {
                "symbol": symbol,
                "status": "FACTOR_INPUT_SNAPSHOT_REASSEMBLED",
                "currentQcInputReady": payload["currentQcInputReady"],
                "currentUqInputReady": payload["currentUqInputReady"],
                "storageReference": destination.relative_to(
                    repository_root
                ).as_posix(),
                "payloadContentHash": payload["contentHash"],
                "sourceSnapshotContentHash": item["payloadContentHash"],
                "qcFactorStatuses": {
                    name: result["status"]
                    for name, result in payload["qcFactors"].items()
                },
            }
        )

    ready_symbols = sorted(
        item["symbol"] for item in records if item["currentQcInputReady"]
    )
    manifest = {
        "artifactType": "OBJECTIVE_RATING_CURRENT_FACTOR_INPUT_MANIFEST",
        "schemaVersion": SCHEMA_VERSION,
        "snapshotContractVersion": SNAPSHOT_VERSION,
        "windowPolicyVersion": WINDOW_POLICY_VERSION,
        "cutoff": source["cutoff"],
        "sourceManifest": {
            "path": SOURCE_MANIFEST,
            "fileSha256": file_hash(source_path),
            "artifactContentHash": source["artifactContentHash"],
        },
        "machinePolicy": {
            "path": MACHINE_POLICY,
            "fileSha256": EXPECTED_POLICY_FILE_SHA,
            "artifactContentHash": EXPECTED_POLICY_CONTENT_HASH,
        },
        "windowRules": {
            "currentWindowMaximumAgeDays": FRESHNESS_DAYS,
            "acceptedCurrentOnlyProviderFields": [
                "Highlights.DilutedEpsTTM",
                "Highlights.RevenueTTM",
                "Highlights.GrossProfitTTM",
            ],
            "rejectedFormulaSubstitutes": [
                "Highlights.OperatingMarginTTM",
            ],
        },
        "securityCount": len(records),
        "currentQcInputReadyCount": qc_ready,
        "currentQcInputReadySymbols": ready_symbols,
        "currentQcMinimum": 20,
        "additionalRequiredToReachMinimum": max(0, 20 - qc_ready),
        "factorStatusCounts": {
            factor: dict(sorted(counts.items()))
            for factor, counts in sorted(factor_counts.items())
        },
        "securities": records,
        "licensedValuesIncluded": False,
        "networkRequestsExecuted": False,
        "scoresOrRanksIncluded": False,
        "forwardValidationExecuted": False,
        "formulaOrThresholdChanges": False,
    }
    manifest["artifactContentHash"] = canonical_hash(manifest)
    write_immutable_json(output_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-7.json"
        ),
    )
    args = parser.parse_args()
    root = args.repository_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    manifest = build_reassembled_manifest(
        repository_root=root,
        output_path=output,
        storage_root=root
        / "storage/provider-validation/current-factor-input-snapshots-v1-7",
    )
    print(
        json.dumps(
            {
                "artifactContentHash": manifest["artifactContentHash"],
                "currentQcInputReadyCount": manifest["currentQcInputReadyCount"],
                "currentQcInputReadySymbols": manifest[
                    "currentQcInputReadySymbols"
                ],
                "additionalRequiredToReachMinimum": manifest[
                    "additionalRequiredToReachMinimum"
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
