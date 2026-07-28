import gzip
import hashlib
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
    ProviderRequestMetric,
    SecAvailabilityExclusion,
    SecDerivedFactObservation,
    SecFactObservation,
    SecFactSelectionResult,
    SecFactsSummary,
    SecFilingSummary,
)
from equity_analysis.provider_validation.sec_authoritative_overrides import (
    SecAuthoritativeTickerOverride,
    canonical_sec_ticker,
    load_authoritative_ticker_overrides,
)

SEC_DATA_BASE_URL = "https://data.sec.gov"
SEC_FILES_BASE_URL = "https://www.sec.gov/files"
SUPPORTED_FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A"})
SEC_CONCEPT_MAPPING_VERSION = "sec-concept-mapping-v1.0.0"
REQUIRED_TAG_GROUPS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "diluted_shares": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    ),
    "interest_expense": (
        "InterestExpenseNonOperating",
        "InterestExpense",
        "InterestAndDebtExpense",
    ),
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
SEC_METRIC_SEMANTICS = {
    "diluted_shares": "DURATION_WEIGHTED_AVERAGE_DILUTED_SHARES",
    "interest_expense": "DURATION_GROSS_INTEREST_EXPENSE",
}
SEC_METRIC_ALLOWED_UNITS = {
    "diluted_shares": frozenset({"shares"}),
    "interest_expense": frozenset({"USD"}),
}
NEW_YORK = ZoneInfo("America/New_York")
OPERATING_INCOME_DERIVATION_VERSION = "operating-income-issuer-v1.0.0"
PRETAX_INCOME_TAG = (
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
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

    def __init__(
        self,
        message: str,
        code: str = "SEC_REQUEST_FAILED",
        endpoint_category: str = "unknown",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.endpoint_category = endpoint_category


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
        "No complete trading session is available after the filing acceptance",
        "SEC_NO_COMPLETE_TRADING_SESSION_AFTER_ACCEPTANCE",
        "local_pit",
    )


def select_point_in_time_facts(
    company_facts_payload: dict[str, Any],
    filings: tuple[SecFilingSummary, ...],
    trading_dates: tuple[date, ...],
    as_of_time: datetime,
) -> tuple[SecFactObservation, ...]:
    return select_point_in_time_facts_with_diagnostics(
        company_facts_payload,
        filings,
        trading_dates,
        as_of_time,
    ).facts


def select_point_in_time_facts_with_diagnostics(
    company_facts_payload: dict[str, Any],
    filings: tuple[SecFilingSummary, ...],
    trading_dates: tuple[date, ...],
    as_of_time: datetime,
) -> SecFactSelectionResult:
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
    availability_exclusions: dict[str, SecAvailabilityExclusion] = {}
    us_gaap = company_facts_payload.get("facts", {}).get("us-gaap", {})
    source_content_hash = hashlib.sha256(
        json.dumps(
            company_facts_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest().upper()

    for taxonomy_tag, fact in us_gaap.items():
        metric_code = tag_to_metric.get(taxonomy_tag)
        if metric_code is None:
            continue
        for unit, entries in fact.get("units", {}).items():
            allowed_units = SEC_METRIC_ALLOWED_UNITS.get(metric_code)
            if allowed_units is not None and unit not in allowed_units:
                continue
            for entry in entries:
                accession_number = str(entry.get("accn", ""))
                filing = filing_by_accession.get(accession_number)
                if filing is None:
                    continue
                if filing.acceptance_datetime > as_of_time:
                    continue
                try:
                    available_at = availability_after_full_trading_session(
                        filing.acceptance_datetime,
                        trading_dates,
                    )
                except SecEdgarError as error:
                    if error.code != "SEC_NO_COMPLETE_TRADING_SESSION_AFTER_ACCEPTANCE":
                        raise
                    availability_exclusions[accession_number] = (
                        SecAvailabilityExclusion(
                            accession_number=accession_number,
                            form=filing.form,
                            acceptance_timestamp=filing.acceptance_datetime,
                            latest_trading_date=(
                                max(trading_dates) if trading_dates else None
                            ),
                            as_of_time=as_of_time,
                            reason_code=error.code,
                        )
                    )
                    continue
                if available_at > as_of_time:
                    continue
                try:
                    period_start = (
                        date.fromisoformat(str(entry["start"])) if entry.get("start") else None
                    )
                    period_end = date.fromisoformat(str(entry["end"]))
                    filed_at = date.fromisoformat(str(entry["filed"]))
                    value = Decimal(str(entry["val"]))
                    fiscal_year = int(entry["fy"]) if entry.get("fy") is not None else None
                except (InvalidOperation, KeyError, TypeError, ValueError) as error:
                    raise SecEdgarError(
                        f"SEC EDGAR returned a malformed {taxonomy_tag} fact",
                        "SEC_COMPANY_FACTS_NORMALIZATION_FAILED",
                        "local_pit",
                    ) from error

                observation = SecFactObservation(
                    metric_code=metric_code,
                    taxonomy_tag=taxonomy_tag,
                    unit=str(unit),
                    value=value,
                    period_start=period_start,
                    period_end=period_end,
                    fiscal_year=fiscal_year,
                    fiscal_period=(str(entry["fp"]) if entry.get("fp") is not None else None),
                    form=filing.form,
                    filed_at=filed_at,
                    accession_number=accession_number,
                    acceptance_datetime=filing.acceptance_datetime,
                    available_at=available_at,
                    frame=str(entry["frame"]) if entry.get("frame") else None,
                    concept_mapping_version=SEC_CONCEPT_MAPPING_VERSION,
                    semantic_classification=SEC_METRIC_SEMANTICS.get(
                        metric_code,
                        "DIRECT_US_GAAP_CONCEPT",
                    ),
                    concept_priority=tag_priority[taxonomy_tag],
                    source_content_hash=source_content_hash,
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
                    -tag_priority[observation.taxonomy_tag],
                    observation.available_at,
                    observation.accession_number,
                ) > (
                    -tag_priority[current.taxonomy_tag],
                    current.available_at,
                    current.accession_number,
                ):
                    selected[key] = observation

    return SecFactSelectionResult(
        facts=tuple(
            sorted(
                selected.values(),
                key=lambda item: (
                    item.metric_code,
                    item.period_end,
                    item.period_start or date.min,
                    item.unit,
                ),
            )
        ),
        availability_exclusions=tuple(
            sorted(
                availability_exclusions.values(),
                key=lambda item: (
                    item.acceptance_timestamp,
                    item.accession_number,
                ),
            )
        ),
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
    primary_value = sum(primary_components[tag] * multiplier for tag, multiplier in primary_terms)
    crosscheck_value = sum(
        crosscheck_components[tag] * multiplier for tag, multiplier in crosscheck_terms
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
                f"Expected one same-period {tag} fact for {accession_number}; found {len(matches)}"
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
        request_observer: Callable[[ProviderRequestMetric], None] | None = None,
        authoritative_ticker_overrides: (
            dict[str, SecAuthoritativeTickerOverride] | None
        ) = None,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("SEC EDGAR user agent is required")
        self._user_agent = user_agent
        self._opener = opener
        self._sleeper = sleeper
        self._request_delay_seconds = request_delay_seconds
        self._timeout_seconds = timeout_seconds
        self._request_observer = request_observer
        self._authoritative_ticker_overrides = (
            load_authoritative_ticker_overrides()
            if authoritative_ticker_overrides is None
            else authoritative_ticker_overrides
        )
        self._last_unsupported_forms: tuple[str, ...] = ()

    @property
    def last_unsupported_forms(self) -> tuple[str, ...]:
        return self._last_unsupported_forms

    def lookup_cik(self, symbol: str) -> tuple[str, str]:
        payload = self._fetch_json(f"{SEC_FILES_BASE_URL}/company_tickers.json")
        normalized_symbol = self._canonical_sec_ticker(symbol)
        official_match: tuple[str, str] | None = None
        for item in payload.values():
            if (
                self._canonical_sec_ticker(str(item.get("ticker", "")))
                == normalized_symbol
            ):
                official_match = (
                    str(item["cik_str"]).zfill(10),
                    str(item["title"]),
                )
                break
        authoritative_override = self._authoritative_ticker_overrides.get(
            normalized_symbol
        )
        if official_match is not None:
            if (
                authoritative_override is not None
                and official_match[0] != authoritative_override.cik
            ):
                raise SecEdgarError(
                    f"SEC ticker mapping conflicts with authoritative evidence for "
                    f"{normalized_symbol}",
                    "SEC_TICKER_CIK_CONFLICT",
                    "ticker_mapping",
                )
            return official_match
        if authoritative_override is not None:
            return (
                authoritative_override.cik,
                authoritative_override.issuer_legal_name,
            )
        raise SecEdgarError(
            f"SEC EDGAR did not list a CIK for {normalized_symbol}",
            "SEC_TICKER_CIK_NOT_FOUND",
            "ticker_mapping",
        )

    @staticmethod
    def _canonical_sec_ticker(symbol: str) -> str:
        return canonical_sec_ticker(symbol)

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
        payload = self._fetch_json(f"{SEC_DATA_BASE_URL}/submissions/CIK{normalized_cik}.json")
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
                historical = self._fetch_json(f"{SEC_DATA_BASE_URL}/submissions/{item['name']}")
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
                f"SEC EDGAR returned no supported filing available by the cutoff for {symbol}",
                "SEC_NO_ELIGIBLE_FILING_BEFORE_AS_OF",
                "submissions",
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
                        filing_date=date.fromisoformat(str(records["filingDate"][index])),
                        acceptance_datetime=acceptance,
                        accession_number=str(records["accessionNumber"][index]),
                        report_date=(date.fromisoformat(report_value) if report_value else None),
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

    def fetch_recent_filings(
        self,
        cik: str,
        symbol: str,
        as_of_time: datetime,
    ) -> tuple[SecFilingSummary, ...]:
        if as_of_time.tzinfo is None or as_of_time.utcoffset() is None:
            raise ValueError("SEC filing cutoff must include a timezone")
        normalized_cik = cik.zfill(10)
        payload = self._fetch_json(f"{SEC_DATA_BASE_URL}/submissions/CIK{normalized_cik}.json")
        forms = tuple(payload.get("filings", {}).get("recent", {}).get("form", ()))
        self._last_unsupported_forms = tuple(
            sorted({str(form) for form in forms if form not in SUPPORTED_FORMS})
        )
        filings = self._eligible_filings(
            payload.get("filings", {}).get("recent", {}),
            normalized_cik,
            str(payload["name"]),
            symbol,
            as_of_time,
        )
        return tuple(sorted(filings, key=lambda item: item.acceptance_datetime))

    def fetch_company_facts(self, cik: str) -> dict[str, Any]:
        normalized_cik = cik.zfill(10)
        return self._fetch_json(
            f"{SEC_DATA_BASE_URL}/api/xbrl/companyfacts/CIK{normalized_cik}.json"
        )

    def _fetch_json(self, url: str) -> dict[str, Any]:
        endpoint_category = self._endpoint_category(url)
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "User-Agent": self._user_agent,
            },
        )
        started_at = time.monotonic()
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
                headers = getattr(response, "headers", None)
                content_encoding = headers.get("Content-Encoding", "") if headers else ""
                if content_encoding.lower() == "gzip":
                    raw = gzip.decompress(raw)
                payload = json.loads(raw.decode("utf-8"))
        except HTTPError as error:
            self._observe_request(url, "FAILED", started_at, f"HTTP_{error.code}")
            raise SecEdgarError(
                f"SEC EDGAR returned HTTP {error.code}",
                self._request_failure_code(endpoint_category),
                endpoint_category,
            ) from error
        except (OSError, TimeoutError, json.JSONDecodeError) as error:
            self._observe_request(url, "FAILED", started_at, "SEC_REQUEST_FAILED")
            raise SecEdgarError(
                "SEC EDGAR request failed",
                self._request_failure_code(endpoint_category),
                endpoint_category,
            ) from error
        else:
            self._observe_request(url, "SUCCESS", started_at)
        finally:
            self._sleeper(self._request_delay_seconds)
        if not isinstance(payload, dict):
            raise SecEdgarError(
                "SEC EDGAR returned a non-object response",
                self._request_failure_code(endpoint_category),
                endpoint_category,
            )
        return payload

    @staticmethod
    def _endpoint_category(url: str) -> str:
        if "/companyfacts/" in url:
            return "company_facts"
        if "/submissions/" in url:
            return "submissions"
        return "ticker_mapping"

    @staticmethod
    def _request_failure_code(endpoint_category: str) -> str:
        return {
            "ticker_mapping": "SEC_TICKER_MAPPING_REQUEST_FAILED",
            "submissions": "SEC_SUBMISSIONS_REQUEST_FAILED",
            "company_facts": "SEC_COMPANY_FACTS_REQUEST_FAILED",
        }[endpoint_category]

    def _observe_request(
        self,
        url: str,
        status: str,
        started_at: float,
        error_code: str | None = None,
    ) -> None:
        if self._request_observer is None:
            return
        endpoint_category = self._endpoint_category(url)
        self._request_observer(
            ProviderRequestMetric(
                provider="sec_edgar",
                endpoint_category=endpoint_category,
                attempt=1,
                status=status,
                duration_ms=max(int((time.monotonic() - started_at) * 1000), 0),
                weighted_calls=1,
                error_code=error_code,
            )
        )
