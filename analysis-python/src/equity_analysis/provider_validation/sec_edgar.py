import gzip
import json
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from equity_analysis.provider_validation.models import SecFactsSummary, SecFilingSummary

SEC_DATA_BASE_URL = "https://data.sec.gov"
SEC_FILES_BASE_URL = "https://www.sec.gov/files"
SUPPORTED_FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A"})
REQUIRED_TAG_GROUPS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "diluted_shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "assets": ("Assets",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditure": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForProceedsFromOtherPropertyPlantAndEquipment",
    ),
}


class SecEdgarError(RuntimeError):
    """Raised when SEC EDGAR cannot return a usable validation response."""


class SecEdgarClient:
    def __init__(
        self,
        user_agent: str,
        opener: Callable[..., Any] = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
        request_delay_seconds: float = 0.12,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("SEC EDGAR user agent is required")
        self._user_agent = user_agent
        self._opener = opener
        self._sleeper = sleeper
        self._request_delay_seconds = request_delay_seconds
        self._timeout_seconds = timeout_seconds

    def lookup_cik(self, symbol: str) -> tuple[str, str]:
        payload = self._fetch_json(f"{SEC_FILES_BASE_URL}/company_tickers.json")
        normalized_symbol = symbol.strip().upper()
        for item in payload.values():
            if str(item.get("ticker", "")).upper() == normalized_symbol:
                return str(item["cik_str"]).zfill(10), str(item["title"])
        raise SecEdgarError(f"SEC EDGAR did not list a CIK for {normalized_symbol}")

    def fetch_latest_filing(self, cik: str, symbol: str) -> SecFilingSummary:
        normalized_cik = cik.zfill(10)
        payload = self._fetch_json(
            f"{SEC_DATA_BASE_URL}/submissions/CIK{normalized_cik}.json"
        )
        recent = payload.get("filings", {}).get("recent", {})
        forms = tuple(recent.get("form", ()))
        for index, form in enumerate(forms):
            if form not in SUPPORTED_FORMS:
                continue
            try:
                acceptance = datetime.fromisoformat(
                    str(recent["acceptanceDateTime"][index]).replace("Z", "+00:00")
                )
                report_value = str(recent["reportDate"][index])
                return SecFilingSummary(
                    cik=normalized_cik,
                    entity_name=str(payload["name"]),
                    symbol=symbol.upper(),
                    form=str(form),
                    filing_date=date.fromisoformat(str(recent["filingDate"][index])),
                    acceptance_datetime=acceptance,
                    accession_number=str(recent["accessionNumber"][index]),
                    report_date=date.fromisoformat(report_value) if report_value else None,
                )
            except (IndexError, KeyError, TypeError, ValueError) as error:
                raise SecEdgarError(
                    f"SEC EDGAR returned malformed filing metadata for {symbol}"
                ) from error
        raise SecEdgarError(f"SEC EDGAR returned no supported filing for {symbol}")

    def fetch_facts_summary(self, cik: str, accession_number: str) -> SecFactsSummary:
        normalized_cik = cik.zfill(10)
        payload = self._fetch_json(
            f"{SEC_DATA_BASE_URL}/api/xbrl/companyfacts/CIK{normalized_cik}.json"
        )
        us_gaap = payload.get("facts", {}).get("us-gaap", {})
        available_tags = tuple(sorted(us_gaap))
        tag_group_presence = {
            group: any(tag in us_gaap for tag in alternatives)
            for group, alternatives in REQUIRED_TAG_GROUPS.items()
        }
        matching_count = 0
        for fact in us_gaap.values():
            for unit_values in fact.get("units", {}).values():
                matching_count += sum(
                    str(item.get("accn")) == accession_number for item in unit_values
                )
        return SecFactsSummary(
            cik=normalized_cik,
            entity_name=str(payload.get("entityName", "")),
            available_tags=available_tags,
            required_tag_groups_present=tag_group_presence,
            matching_accession_fact_count=matching_count,
        )

    def _fetch_json(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "User-Agent": self._user_agent,
            },
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
                headers = getattr(response, "headers", None)
                content_encoding = headers.get("Content-Encoding", "") if headers else ""
                if content_encoding.lower() == "gzip":
                    raw = gzip.decompress(raw)
                payload = json.loads(raw.decode("utf-8"))
        except HTTPError as error:
            raise SecEdgarError(f"SEC EDGAR returned HTTP {error.code}") from error
        except (OSError, TimeoutError, json.JSONDecodeError) as error:
            raise SecEdgarError("SEC EDGAR request failed") from error
        finally:
            self._sleeper(self._request_delay_seconds)
        if not isinstance(payload, dict):
            raise SecEdgarError("SEC EDGAR returned a non-object response")
        return payload
