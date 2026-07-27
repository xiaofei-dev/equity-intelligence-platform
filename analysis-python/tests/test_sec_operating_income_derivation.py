import json
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.provider_validation.sec_edgar import (
    OPERATING_INCOME_DERIVATION_VERSION,
    SecEdgarError,
    derive_issuer_operating_income,
)

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "sec_operating_income_derivations_2026-07-26.json"
)


def _payload(case: dict) -> dict:
    return {
        "facts": {
            "us-gaap": {
                tag: {
                    "units": {
                        case["unit"]: [
                            {
                                "accn": case["accessionNumber"],
                                "start": case["periodStart"],
                                "end": case["periodEnd"],
                                "val": value,
                            }
                        ]
                    }
                }
                for tag, value in case["facts"].items()
            }
        }
    }


@pytest.mark.parametrize("case_index", range(5))
def test_reviewed_issuer_operating_income_derivations_agree(
    case_index: int,
) -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    case = fixture["cases"][case_index]

    derived = derive_issuer_operating_income(
        _payload(case),
        cik=case["cik"],
        accession_number=case["accessionNumber"],
        period_start=date.fromisoformat(case["periodStart"]),
        period_end=date.fromisoformat(case["periodEnd"]),
        unit=case["unit"],
    )

    assert derived.value == Decimal(str(case["expectedOperatingIncome"]))
    assert derived.derivation_version == OPERATING_INCOME_DERIVATION_VERSION
    assert len(derived.primary_components) == 3
    assert len(derived.crosscheck_components) == 3


def test_derivation_rejects_disagreement_between_accounting_paths() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    case = deepcopy(fixture["cases"][0])
    case["facts"]["InterestExpense"] += 1

    with pytest.raises(SecEdgarError, match="paths disagree"):
        derive_issuer_operating_income(
            _payload(case),
            cik=case["cik"],
            accession_number=case["accessionNumber"],
            period_start=date.fromisoformat(case["periodStart"]),
            period_end=date.fromisoformat(case["periodEnd"]),
        )


def test_derivation_rejects_unreviewed_issuer_and_mixed_periods() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    case = fixture["cases"][0]

    with pytest.raises(SecEdgarError, match="No reviewed"):
        derive_issuer_operating_income(
            _payload(case),
            cik="0000320193",
            accession_number=case["accessionNumber"],
            period_start=date.fromisoformat(case["periodStart"]),
            period_end=date.fromisoformat(case["periodEnd"]),
        )

    with pytest.raises(SecEdgarError, match="Expected one same-period"):
        derive_issuer_operating_income(
            _payload(case),
            cik=case["cik"],
            accession_number=case["accessionNumber"],
            period_start=date(2025, 7, 1),
            period_end=date.fromisoformat(case["periodEnd"]),
        )
