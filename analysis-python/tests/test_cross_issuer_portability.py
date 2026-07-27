import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from equity_analysis.provider_validation.fundamentals import (
    derive_ttm_from_annual_and_ytd,
)
from equity_analysis.provider_validation.models import SecFactObservation

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "cross_issuer_ttm_portability_2024-06-30.json"
)


def _fact(metric: dict, period: dict, value_field: str, form: str):
    return SecFactObservation(
        metric_code=metric["metricCode"],
        taxonomy_tag=metric["metricCode"],
        unit="USD",
        value=Decimal(metric[value_field]),
        period_start=date.fromisoformat(period["start"]),
        period_end=date.fromisoformat(period["end"]),
        fiscal_year=None,
        fiscal_period="FY" if form == "10-K" else "YTD",
        form=form,
        filed_at=date.fromisoformat(period["availableAt"][:10]),
        accession_number=period["accession"],
        acceptance_datetime=datetime.fromisoformat(
            period["availableAt"].replace("Z", "+00:00")
        ),
        available_at=datetime.fromisoformat(
            period["availableAt"].replace("Z", "+00:00")
        ),
    )


def test_cross_issuer_ttm_bridge_is_hashed_and_reproducible() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    rows = []
    cutoff = datetime.fromisoformat(fixture["asOfTime"].replace("Z", "+00:00"))

    for issuer in fixture["issuers"]:
        for metric in issuer["metrics"]:
            rows.append(
                "|".join(
                    (
                        issuer["symbol"],
                        metric["metricCode"],
                        metric["annual"],
                        metric["currentYtd"],
                        metric["priorYtd"],
                        metric["expectedTtm"],
                        issuer["annualPeriod"]["accession"],
                        issuer["currentYtdPeriod"]["accession"],
                    )
                )
            )
            result = derive_ttm_from_annual_and_ytd(
                _fact(metric, issuer["annualPeriod"], "annual", "10-K"),
                _fact(metric, issuer["currentYtdPeriod"], "currentYtd", "10-Q"),
                _fact(metric, issuer["priorYtdPeriod"], "priorYtd", "10-Q"),
                cutoff,
            )
            assert result.value == Decimal(metric["expectedTtm"])
            assert result.available_at <= cutoff

    assert (
        hashlib.sha256("\n".join(rows).encode()).hexdigest()
        == fixture["derivedRowsHash"]
    )


def test_tgt_missing_gross_profit_remains_explicit() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    target = next(item for item in fixture["issuers"] if item["symbol"] == "TGT")

    assert {item["metricCode"] for item in target["metrics"]}.isdisjoint(
        {"gross_profit"}
    )
    assert target["missingFields"] == [
        {
            "field": "gross_profit",
            "reason": (
                "No compatible standard GrossProfit fact was available for the "
                "tested periods."
            ),
        }
    ]
