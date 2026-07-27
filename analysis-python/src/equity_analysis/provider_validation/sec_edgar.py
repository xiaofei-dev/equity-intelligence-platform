import gzip
import json
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from equity_analysis.provider_validation.models import (
    SecDerivedFactObservation,
    SecFactObservation,
    SecFactsSummary,
    SecFilingSummary,
)

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
        "PaymentsToAcquireOtherPropertyPlantAndEquipment",
        "PaymentsForProceedsFromOtherPropertyPlantAndEquipment",
    ),
}
NEW_YORK = ZoneInfo("America/New_York")
OPERATING_INCOME_DERIVATION_VERSION = "operating-income-issuer-v1.0.0"
PRETAX_INCOME_TAG = (
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
    "ExtraordinaryItemsNoncontrollingInterest"
)
OPERATING_INCOME_DERIVATIONS: dict[
    str,
    tuple[tuple[tuple[str, Decimal], ...], tuple[tuple[str, Decimal], ...]],
] = {
    "0000008670": (
        (
            ("RevenueFromContractWithCustomerExcludingAssessedTax", Decimal("1")),
            ("CostOfGoodsAndServicesSold", Decimal("-1")),
            ("SellingGeneralAndAdministrativeExpense", Decimal("-1")),
        ),
        (
            (PRETAX_INCOME_TAG, Decimal("1")),
            ("InterestExpense", Decimal("1")),
            ("NonoperatingIncomeExpense", Decimal("-1")),
        ),
    ),
    "0000320187": (
        (
            ("RevenueFromContractWithCustomerExcludingAssessedTax", Decimal("1")),
            ("CostOfGoodsAndServicesSold", Decimal("-1")),
            ("SellingGeneralAndAdministrativeExpense", Decimal("-1")),
        ),
        (
            (PRETAX_INCOME_TAG, Decimal("1")),
            ("InterestIncomeExpenseNonoperatingNet", Decimal("-1")),
            ("OtherNonoperatingIncomeExpense", Decimal("-1")),
        ),
    ),
}


class SecEdgarError(RuntimeError):
    """Raised when SEC EDGAR cannot return a usable validation response."""


def availability_after_full_trading_session(
    acceptance_datetime: datetime,
    trading_dates: tuple[date, ...],
) -> datetime:
    if acceptance_datetime.tzinfo is None or acceptance_datetime.utcoffset() is None:
        raise ValueError("SEC acceptance timestamp must include a timezone")

    accepted_new_york = acceptance_datetime.astimezone(NEW_YORK)
    for trading_date in sorted(set(trading_dates)):
        session_open = datetime.combine(
            trading_date,
            datetime_time(9, 30),
            tzinfo=NEW_YORK,
        )
        if accepted_new_york <= session_open:
            return datetime.combine(
                trading_date,
                datetime_time(16, 0),
                tzinfo=NEW_YORK,
            ).astimezone(UTC)

    raise SecEdgarError(
        "No complete trading session is available after the filing acceptance"
    )


def select_point_in_time_facts(
    company_facts_payload: dict[str, Any],
    filings: tuple[SecFilingSummary, ...],
    trading_dates: tuple[date, ...],
    as_of_time: datetime,
) -> tuple[SecFactObservation, ...]:
    if as_of_time.tzinfo is None or as_of_time.utcoffset() is None:
        raise ValueError("Point-in-time cutoff must include a timezone")

    filing_by_accession = {filing.accession_number: filing for filing in filings}
    tag_to_metric = {
        tag: metric_code
        for metric_code, alternatives in REQUIRED_TAG_GROUPS.items()
        for tag in alternatives
    }
    tag_priority = {
        tag: priority
        for alternatives in REQUIRED_TAG_GROUPS.values()
        for priority, tag in enumerate(alternatives)
    }
    selected: dict[
        tuple[str, str, date | None, date, str | None],
        SecFactObservation,
    ] = {}
    us_gaap = company_facts_payload.get("facts", {}).get("us-gaap", {})

    for taxonomy_tag, fact in us_gaap.items():
        metric_code = tag_to_metric.get(taxonomy_tag)
        if metric_code is None:
            continue
        for unit, entries in fact.get("units", {}).items():
            for entry in entries:
                accession_number = str(entry.get("accn", ""))
                filing = filing_by_accession.get(accession_number)
                if filing is None:
                    continue
                if filing.acceptance_datetime > as_of_time:
                    continue
                available_at = availability_after_full_trading_session(
                    filing.acceptance_datetime,
                    trading_dates,
                )
                if available_at > as_of_time:
                    continue
                try:
                    period_start = (
                        date.fromisoformat(str(entry["start"]))
                        if entry.get("start")
                        else None
                    )
                    period_end = date.fromisoformat(str(entry["end"]))
                    filed_at = date.fromisoformat(str(entry["filed"]))
                    value = Decimal(str(entry["val"]))
                    fiscal_year = (
                        int(entry["fy"]) if entry.get("fy") is not None else None
                    )
                except (InvalidOperation, KeyError, TypeError, ValueError) as error:
                    raise SecEdgarError(
                        f"SEC EDGAR returned a malformed {taxonomy_tag} fact"
                    ) from error

                observation = SecFactObservation(
                    metric_code=metric_code,
                    taxonomy_tag=taxonomy_tag,
                    unit=str(unit),
                    value=value,
                    period_start=period_start,
                    period_end=period_end,
                    fiscal_year=fiscal_year,
                    fiscal_period=(
                        str(entry["fp"]) if entry.get("fp") is not None else None
                    ),
                    form=filing.form,
                    filed_at=filed_at,
                    accession_number=accession_number,
                    acceptance_datetime=filing.acceptance_datetime,
                    available_at=available_at,
                    frame=str(entry["frame"]) if entry.get("frame") else None,
                )
                key = (
                    metric_code,
                    str(unit),
                    period_start,
                    period_end,
                    observation.fiscal_period,
                )
                current = selected.get(key)
                if current is None or (
                    observation.available_at,
                    -tag_priority[observation.taxonomy_tag],
                    observation.accession_number,
                ) > (
                    current.available_at,
                    -tag_priority[current.taxonomy_tag],
                    current.accession_number,
                ):
                    selected[key] = observation

    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (
                item.metric_code,
                item.period_end,
                item.period_start or date.min,
                item.unit,
            ),
        )
    )


def derive_issuer_operating_income(
    company_facts_payload: dict[str, Any],
    cik: str,
    accession_number: str,
    period_start: date,
    period_end: date,
    unit: str = "USD",
) -> SecDerivedFactObservation:
    normalized_cik = cik.zfill(10)
    specification = OPERATING_INCOME_DERIVATIONS.get(normalized_cik)
    if specification is None:
        raise SecEdgarError(
            f"No reviewed operating-income derivation exists for CIK {normalized_cik}"
        )

    primary_terms, crosscheck_terms = specification
    primary_components = _same_period_components(
        company_facts_payload,
        primary_terms,
        accession_number,
        period_start,
        period_end,
        unit,
    )
    crosscheck_components = _same_period_components(
        company_facts_payload,
        crosscheck_terms,
        accession_number,
        period_start,
        period_end,
        unit,
    )
    primary_value = sum(
        primary_components[tag] * multiplier for tag, multiplier in primary_terms
    )
    crosscheck_value = sum(
        crosscheck_components[tag] * multiplier
        for tag, multiplier in crosscheck_terms
    )
    if primary_value != crosscheck_value:
        raise SecEdgarError(
            "Operating-income derivation paths disagree for "
            f"{normalized_cik} {period_start} through {period_end}: "
            f"{primary_value} != {crosscheck_value}"
        )

    return SecDerivedFactObservation(
        metric_code="operating_income",
        value=primary_value,
        unit=unit,
        period_start=period_start,
        period_end=period_end,
        accession_number=accession_number,
        derivation_version=OPERATING_INCOME_DERIVATION_VERSION,
        primary_components=primary_components,
        crosscheck_components=crosscheck_components,
    )


def _same_period_components(
    company_facts_payload: dict[str, Any],
    terms: tuple[tuple[str, Decimal], ...],
    accession_number: str,
    period_start: date,
    period_end: date,
    unit: str,
) -> dict[str, Decimal]:
    us_gaap = company_facts_payload.get("facts", {}).get("us-gaap", {})
    components: dict[str, Decimal] = {}
    for tag, _multiplier in terms:
        entries = us_gaap.get(tag, {}).get("units", {}).get(unit, ())
        matches = [
            entry
            for entry in entries
            if str(entry.get("accn")) == accession_number
            and str(entry.get("start")) == period_start.isoformat()
            and str(entry.get("end")) == period_end.isoformat()
        ]
        if len(matches) != 1:
            raise SecEdgarError(
                f"Expected one same-period {tag} fact for {accession_number}; "
                f"found {len(matches)}"
            )
        try:
            components[tag] = Decimal(str(matches[0]["val"]))
        except (InvalidOperation, KeyError, TypeError) as error:
            raise SecEdgarError(
                f"SEC EDGAR returned an invalid {tag} derivation component"
            ) from error
    return components


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
        return self.fetch_filing_as_of(
            cik,
            symbol,
            as_of_time=datetime.max.replace(tzinfo=UTC),
        )

    def fetch_filing_as_of(
        self,
        cik: str,
        symbol: str,
        as_of_time: datetime,
    ) -> SecFilingSummary:
        if as_of_time.tzinfo is None or as_of_time.utcoffset() is None:
            raise ValueError("SEC filing cutoff must include a timezone")
        normalized_cik = cik.zfill(10)
        payload = self._fetch_json(
            f"{SEC_DATA_BASE_URL}/submissions/CIK{normalized_cik}.json"
        )
        recent = payload.get("filings", {}).get("recent", {})
        eligible = self._eligible_filings(
            recent,
            normalized_cik,
            str(payload["name"]),
            symbol,
            as_of_time,
        )
        if not eligible:
            files = payload.get("filings", {}).get("files", ())
            dated_files = sorted(
                (
                    item
                    for item in files
                    if date.fromisoformat(str(item["filingFrom"])) <= as_of_time.date()
                ),
                key=lambda item: date.fromisoformat(str(item["filingTo"])),
                reverse=True,
            )
            for item in dated_files:
                historical = self._fetch_json(
                    f"{SEC_DATA_BASE_URL}/submissions/{item['name']}"
                )
                eligible = self._eligible_filings(
                    historical,
                    normalized_cik,
                    str(payload["name"]),
                    symbol,
                    as_of_time,
                )
                if eligible:
                    break
        if not eligible:
            raise SecEdgarError(
                f"SEC EDGAR returned no supported filing available by the cutoff for "
                f"{symbol}"
            )
        return max(eligible, key=lambda filing: filing.acceptance_datetime)

    @staticmethod
    def _eligible_filings(
        records: dict[str, Any],
        normalized_cik: str,
        entity_name: str,
        symbol: str,
        as_of_time: datetime,
    ) -> list[SecFilingSummary]:
        forms = tuple(records.get("form", ()))
        eligible: list[SecFilingSummary] = []
        for index, form in enumerate(forms):
            if form not in SUPPORTED_FORMS:
                continue
            try:
                acceptance = datetime.fromisoformat(
                    str(records["acceptanceDateTime"][index]).replace("Z", "+00:00")
                )
                if acceptance > as_of_time:
                    continue
                report_value = str(records["reportDate"][index])
                eligible.append(
                    SecFilingSummary(
                        cik=normalized_cik,
                        entity_name=entity_name,
                        symbol=symbol.upper(),
                        form=str(form),
                        filing_date=date.fromisoformat(
                            str(records["filingDate"][index])
                        ),
                        acceptance_datetime=acceptance,
                        accession_number=str(records["accessionNumber"][index]),
                        report_date=(
                            date.fromisoformat(report_value) if report_value else None
                        ),
                    )
                )
            except (IndexError, KeyError, TypeError, ValueError) as error:
                raise SecEdgarError(
                    f"SEC EDGAR returned malformed filing metadata for {symbol}"
                ) from error
        return eligible

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
