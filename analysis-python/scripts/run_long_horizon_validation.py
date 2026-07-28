from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "analysis-python" / "src"))

from equity_analysis.research_rating.long_horizon_v1 import (  # noqa: E402
    CompanyModel,
    LongHorizonInputs,
    evaluate_long_horizon,
)

SYMBOLS = ("AAPL", "AMZN", "TSLA", "SPCX", "UNH", "GE", "NBN")
COMPARISON_SET_2 = ("NFLX", "RBLX", "MSFT")


def load_environment() -> None:
    for raw_line in (REPOSITORY_ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def fetch_fundamentals(symbol: str, api_key: str) -> dict[str, object]:
    query = urlencode({"api_token": api_key, "fmt": "json"})
    request = Request(
        f"https://eodhd.com/api/fundamentals/{symbol}.US?{query}",
        headers={"User-Agent": "equity-intelligence-platform/0.1"},
    )
    with urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected fundamentals response for {symbol}")
    return payload


def number(mapping: object, key: str) -> float | None:
    if not isinstance(mapping, dict):
        return None
    raw = mapping.get(key)
    if raw in (None, "", "NA", "None"):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def latest_quarter(payload: dict[str, object], statement: str) -> dict[str, object]:
    financials = payload.get("Financials")
    if not isinstance(financials, dict):
        return {}
    statement_payload = financials.get(statement)
    if not isinstance(statement_payload, dict):
        return {}
    quarterly = statement_payload.get("quarterly")
    if not isinstance(quarterly, dict) or not quarterly:
        return {}
    latest_key = max(quarterly)
    latest = quarterly.get(latest_key)
    return latest if isinstance(latest, dict) else {}


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def build_inputs(symbol: str, payload: dict[str, object]) -> LongHorizonInputs:
    highlights = payload.get("Highlights", {})
    valuation = payload.get("Valuation", {})
    balance = latest_quarter(payload, "Balance_Sheet")
    current_ratio = safe_ratio(
        number(balance, "totalCurrentAssets"),
        number(balance, "totalCurrentLiabilities"),
    )
    debt_to_equity = safe_ratio(
        number(balance, "shortLongTermDebtTotal"),
        number(balance, "totalStockholderEquity"),
    )
    if symbol == "SPCX":
        return LongHorizonInputs(
            symbol=symbol,
            company_model=CompanyModel.RECENT_IPO,
            recent_public_trading_days=33,
            evidence_confidence=0.55,
        )
    common = {
        "symbol": symbol,
        "price_earnings": number(highlights, "PERatio"),
        "price_book": number(valuation, "PriceBookMRQ"),
        "enterprise_value_ebitda": number(valuation, "EnterpriseValueEbitda"),
        "peg": number(highlights, "PEGRatio"),
        "operating_margin": number(highlights, "OperatingMarginTTM"),
        "net_margin": number(highlights, "ProfitMargin"),
        "return_on_equity": number(highlights, "ReturnOnEquityTTM"),
        "revenue_growth_yoy": number(highlights, "QuarterlyRevenueGrowthYOY"),
        "earnings_growth_yoy": number(highlights, "QuarterlyEarningsGrowthYOY"),
        "current_ratio": current_ratio,
        "debt_to_equity": debt_to_equity,
    }
    if symbol == "NBN":
        return LongHorizonInputs(
            **common,
            company_model=CompanyModel.BANK,
            nonperforming_assets=0.007,
            tier_one_leverage=0.119,
            evidence_confidence=0.85,
        )
    return LongHorizonInputs(
        **common,
        company_model=CompanyModel.GENERAL,
        evidence_confidence=0.90,
    )


def main() -> None:
    load_environment()
    api_key = os.environ.get("EODHD_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("EODHD_API_KEY is required")
    symbols = COMPARISON_SET_2 if "--comparison-set-2" in sys.argv else SYMBOLS
    validation_root = REPOSITORY_ROOT / "storage" / "long-horizon-validation"
    existing_roots = sorted(
        path
        for path in validation_root.glob("*")
        if path.is_dir()
        and all((path / f"{symbol}-fundamentals.json").exists() for symbol in symbols)
        and not (path / "long-horizon-validation.json").exists()
    )
    if existing_roots:
        root = existing_roots[-1]
    else:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        root = validation_root / run_id
        root.mkdir(parents=True, exist_ok=False)
    results: dict[str, object] = {}
    for symbol in symbols:
        raw_path = root / f"{symbol}-fundamentals.json"
        if raw_path.exists():
            raw = raw_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        else:
            payload = fetch_fundamentals(symbol, api_key)
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            raw_path.write_text(raw, encoding="utf-8")
        raw_hash = hashlib.sha256(raw.encode()).hexdigest().upper()
        inputs = build_inputs(symbol, payload)
        assessment = evaluate_long_horizon(inputs)
        results[symbol] = {
            "rawFundamentalsHash": raw_hash,
            "inputs": inputs.__dict__,
            "assessment": {
                "version": assessment.version,
                "status": assessment.status,
                "score": assessment.score,
                "label": assessment.label,
                "confidence": assessment.confidence,
                "categories": [item.__dict__ for item in assessment.categories],
                "missingFields": assessment.missing_fields,
                "limitations": assessment.limitations,
            },
        }
    output = root / "long-horizon-validation.json"
    output.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
