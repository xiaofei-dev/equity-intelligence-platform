import json
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.historical_quarterly_semantics_support_v1 import (
    FIELD_MAPPINGS,
    ComparableFactV1,
    SupportEvidenceError,
    authorize_empirical_value_read,
    build_frozen_protocol,
    canonical_hash,
    compare_exact_cross_provider,
    compare_quarter_sums_to_annual,
    seal_support_evidence,
    validate_protocol,
)

SCREENSHOT = Path(
    "C:/Users/simon/AppData/Local/Temp/"
    "codex-clipboard-4bbaece8-9610-4759-b5f5-afe2ada80a0f.png")


def _fact(
    provider: str, field: str, end: date, value: str,
    start: date | None = None, fiscal_period_id: str = "FY2020",
) -> ComparableFactV1:
    mapping = FIELD_MAPPINGS[field]
    return ComparableFactV1(
        provider, "SECURITY:1", field,
        mapping[0] if provider == "EODHD" else mapping[1], mapping[1], mapping[2],
        fiscal_period_id, start or (end - timedelta(days=89)), end, end.year, "USD", "USD",
        Decimal(value), ("A" if provider == "EODHD" else "B") * 64)


def test_supplied_hash_is_bound_but_visual_quote_mismatch_blocks_read() -> None:
    evidence = seal_support_evidence(SCREENSHOT)
    assert evidence["fileSha256"].startswith("4F79D7FF")
    assert evidence["quoteVisuallyCorroborated"] is False
    with pytest.raises(SupportEvidenceError, match="NOT_CORROBORATED"):
        authorize_empirical_value_read(evidence, build_frozen_protocol())
    with pytest.raises(SupportEvidenceError, match="CROSS_CONTAMINATION"):
        authorize_empirical_value_read(
            evidence, build_frozen_protocol(), requested_stratum="STRICT_PIT")


def test_evidence_hash_drift_fails(tmp_path: Path) -> None:
    altered = tmp_path / "evidence.png"
    altered.write_bytes(SCREENSHOT.read_bytes() + b"altered")
    with pytest.raises(SupportEvidenceError, match="HASH_DRIFT"):
        seal_support_evidence(altered)


def test_thresholds_are_exactly_prebound() -> None:
    protocol = build_frozen_protocol()
    validate_protocol(protocol)
    with pytest.raises(SupportEvidenceError, match="NOT_PREBOUND"):
        validate_protocol(replace(protocol, relative_tolerance=Decimal("0.02")))


def test_cross_provider_requires_exact_period_unit_and_currency() -> None:
    protocol = build_frozen_protocol()
    eodhd = [_fact("EODHD", "revenue", date(2020, 3, 31), "100")]
    sec = [_fact("SEC", "revenue", date(2020, 3, 31), "100.5")]
    result = compare_exact_cross_provider(eodhd, sec, protocol)
    assert result["matchedCount"] == result["agreementCount"] == 1
    shifted = [replace(sec[0], period_end=date(2020, 4, 1))]
    result = compare_exact_cross_provider(eodhd, shifted, protocol)
    assert result["matchedCount"] == 0
    assert result["missingEodhdCount"] == result["missingSecCount"] == 1


def test_missing_field_is_counted_not_imputed() -> None:
    result = compare_exact_cross_provider(
        [_fact("EODHD", "revenue", date(2020, 3, 31), "100")],
        [_fact("SEC", "net_income", date(2020, 3, 31), "10")],
        build_frozen_protocol())
    assert result["agreementRate"] is None
    assert result["missingEodhdCount"] == result["missingSecCount"] == 1


def test_annual_sum_agreement_and_contradiction_use_frozen_tolerance() -> None:
    ends = (date(2020, 3, 31), date(2020, 6, 30),
            date(2020, 9, 30), date(2020, 12, 31))
    starts = (date(2020, 1, 1), date(2020, 4, 1),
              date(2020, 7, 1), date(2020, 10, 1))
    quarters = [_fact("EODHD", "revenue", end, "25", start)
                for start, end in zip(starts, ends, strict=False)]
    annual = [_fact("EODHD", "revenue", date(2020, 12, 31), "100.9",
                    date(2020, 1, 1))]
    result = compare_quarter_sums_to_annual(
        quarters, annual, build_frozen_protocol())
    assert result["agreementCount"] == 1
    contradictory = [replace(annual[0], value=Decimal("120"))]
    result = compare_quarter_sums_to_annual(
        quarters, contradictory, build_frozen_protocol())
    assert result["contradictionCount"] == 1


def test_incomplete_annual_quarters_do_not_compare() -> None:
    ends = (date(2020, 3, 31), date(2020, 6, 30), date(2020, 9, 30))
    starts = (date(2020, 1, 1), date(2020, 4, 1), date(2020, 7, 1))
    quarters = [_fact("EODHD", "revenue", end, "25", start)
                for start, end in zip(starts, ends, strict=False)]
    annual = [_fact("EODHD", "revenue", date(2020, 12, 31), "75",
                    date(2020, 1, 1))]
    result = compare_quarter_sums_to_annual(
        quarters, annual, build_frozen_protocol())
    assert result["matchedFiscalFieldYears"] == 0
    assert result["incompleteQuarterGroupCount"] == 1


def test_annual_comparison_rejects_wrong_end_duplicate_and_irregular_chain() -> None:
    protocol = build_frozen_protocol()
    starts = (date(2020, 1, 1), date(2020, 4, 1),
              date(2020, 7, 1), date(2020, 10, 1))
    ends = (date(2020, 3, 31), date(2020, 6, 30),
            date(2020, 9, 30), date(2020, 12, 31))
    quarters = [_fact("EODHD", "revenue", end, "25", start)
                for start, end in zip(starts, ends, strict=False)]
    wrong_end = [_fact("EODHD", "revenue", date(2020, 12, 30), "100",
                       date(2020, 1, 1))]
    assert compare_quarter_sums_to_annual(
        quarters, wrong_end, protocol)["matchedFiscalFieldYears"] == 0
    annual = _fact("EODHD", "revenue", date(2020, 12, 31), "100",
                   date(2020, 1, 1))
    with pytest.raises(SupportEvidenceError, match="DUPLICATE_ANNUAL"):
        compare_quarter_sums_to_annual(quarters, [annual, annual], protocol)
    irregular = list(quarters)
    irregular[1] = replace(irregular[1], period_start=date(2020, 1, 2))
    assert compare_quarter_sums_to_annual(
        irregular, [annual], protocol)["matchedFiscalFieldYears"] == 0
    overlap = list(quarters)
    overlap[1] = replace(overlap[1], period_start=date(2020, 3, 10))
    assert compare_quarter_sums_to_annual(
        overlap, [annual], protocol)["matchedFiscalFieldYears"] == 0
    gap = list(quarters)
    gap[2] = replace(gap[2], period_start=date(2020, 7, 21))
    assert compare_quarter_sums_to_annual(
        gap, [annual], protocol)["matchedFiscalFieldYears"] == 0


def test_unmapped_field_and_sign_drift_are_rejected() -> None:
    protocol = build_frozen_protocol()
    fact = _fact("EODHD", "capital_expenditure", date(2020, 3, 31), "10")
    with pytest.raises(SupportEvidenceError, match="MAPPING_MISMATCH"):
        compare_exact_cross_provider(
            [replace(fact, sign_policy="AS_REPORTED")], [], protocol)


def test_checked_c4_artifact_is_self_authenticating_and_stopped() -> None:
    repository = Path(__file__).resolve().parents[2]
    artifact = json.loads((repository
        / "contracts/fundamental-value-historical-validation-v1"
        / "stage7c4-quarterly-semantics-support-gate.json").read_text())
    claimed = artifact.pop("contentHash")
    assert claimed == canonical_hash(artifact)
    assert artifact["controlledFinancialValuesRead"] is False
    assert artifact["empiricalAudit"]["state"] == "NOT_RUN"
    assert artifact["approximationReplay"]["state"] == (
        "NOT_RUN_SEMANTIC_GATE_FAILED")
