from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime

from equity_analysis.provider_validation.market_data import MarketDataValidationClient
from equity_analysis.provider_validation.models import (
    AcceptanceSecurity,
    AcceptanceUniverse,
    CheckCategory,
    CheckStatus,
    ProviderAcceptanceReport,
    SecurityValidationResult,
    ValidationCheck,
    ValidationSummary,
)
from equity_analysis.provider_validation.sec_edgar import SecEdgarClient, SecEdgarError
from equity_analysis.provider_validation.twelve_data import (
    TwelveDataValidationClient,
    TwelveDataValidationError,
)

REPORT_VERSION = "provider-acceptance-report-v1.0.0"


class ProviderAcceptanceService:
    def __init__(
        self,
        sec_client: SecEdgarClient | None,
        twelve_data_client: TwelveDataValidationClient | None,
        market_data_clients: tuple[MarketDataValidationClient, ...] = (),
        unavailable_market_providers: tuple[str, ...] = (),
        validate_twelve_data: bool = True,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sec_client = sec_client
        self._twelve_data_client = twelve_data_client
        self._market_data_clients = market_data_clients
        self._unavailable_market_providers = unavailable_market_providers
        self._validate_twelve_data_enabled = validate_twelve_data
        self._clock = clock

    def validate(
        self,
        universe: AcceptanceUniverse,
        start_date: date,
        end_date: date,
        symbols: Iterable[str] | None = None,
    ) -> ProviderAcceptanceReport:
        requested = {symbol.upper() for symbol in symbols} if symbols is not None else None
        securities = tuple(
            security
            for security in universe.securities
            if requested is None or security.symbol.upper() in requested
        )
        if not securities:
            raise ValueError("No securities matched the requested validation symbols")
        results = tuple(
            self._validate_security(security, start_date, end_date) for security in securities
        )
        checks = tuple(check for result in results for check in result.checks)
        summary = ValidationSummary(
            security_count=len(results),
            pass_count=sum(check.status == CheckStatus.PASS for check in checks),
            fail_count=sum(check.status == CheckStatus.FAIL for check in checks),
            not_verified_count=sum(check.status == CheckStatus.NOT_VERIFIED for check in checks),
            not_applicable_count=sum(
                check.status == CheckStatus.NOT_APPLICABLE for check in checks
            ),
        )
        production_status = (
            CheckStatus.PASS
            if summary.fail_count == 0 and summary.not_verified_count == 0
            else CheckStatus.NOT_VERIFIED
        )
        return ProviderAcceptanceReport(
            report_version=REPORT_VERSION,
            generated_at=self._clock(),
            universe_version=universe.universe_version,
            price_start_date=start_date,
            price_end_date=end_date,
            results=results,
            summary=summary,
            production_backtest_status=production_status,
            conclusion=(
                "The tested providers satisfy every requested acceptance check."
                if production_status == CheckStatus.PASS
                else "The tested providers do not yet establish a survivorship-safe "
                "point-in-time production backtest dataset."
            ),
        )

    def _validate_security(
        self,
        security: AcceptanceSecurity,
        start_date: date,
        end_date: date,
    ) -> SecurityValidationResult:
        checks: list[ValidationCheck] = []
        cik = security.cik
        if security.expected_company_type == "BENCHMARK" and cik is None:
            checks.append(
                self._check(
                    "sec_edgar",
                    CheckCategory.SECURITY_IDENTITY,
                    CheckStatus.NOT_APPLICABLE,
                    "An SEC operating-company CIK is not required for a benchmark.",
                )
            )
        elif cik is None and self._sec_client is None:
            checks.append(
                self._check(
                    "sec_edgar",
                    CheckCategory.SECURITY_IDENTITY,
                    CheckStatus.NOT_VERIFIED,
                    "SEC_USER_AGENT is not configured, so SEC lookup was not attempted.",
                )
            )
        elif cik is None:
            assert self._sec_client is not None
            try:
                cik, entity_name = self._sec_client.lookup_cik(security.symbol)
                checks.append(
                    self._check(
                        "sec_edgar",
                        CheckCategory.SECURITY_IDENTITY,
                        CheckStatus.PASS,
                        "SEC resolved the current ticker to a CIK.",
                        {"cik": cik, "entityName": entity_name},
                    )
                )
            except SecEdgarError as error:
                checks.append(
                    self._check(
                        "sec_edgar",
                        CheckCategory.SECURITY_IDENTITY,
                        CheckStatus.NOT_VERIFIED,
                        str(error),
                    )
                )
        else:
            checks.append(
                self._check(
                    "validation_fixture",
                    CheckCategory.SECURITY_IDENTITY,
                    CheckStatus.PASS,
                    "The acceptance fixture supplies the historical CIK.",
                    {"cik": cik},
                )
            )

        if security.expected_company_type == "BENCHMARK":
            checks.extend(
                (
                    self._check(
                        "sec_edgar",
                        CheckCategory.FUNDAMENTAL_LINEAGE,
                        CheckStatus.NOT_APPLICABLE,
                        "Operating-company filing lineage is not required for a benchmark.",
                    ),
                    self._check(
                        "sec_edgar",
                        CheckCategory.FUNDAMENTAL_FIELDS,
                        CheckStatus.NOT_APPLICABLE,
                        "Operating-company factors are not calculated for a benchmark.",
                    ),
                )
            )
        elif cik is None or self._sec_client is None:
            checks.extend(
                (
                    self._check(
                        "sec_edgar",
                        CheckCategory.FUNDAMENTAL_LINEAGE,
                        CheckStatus.NOT_VERIFIED,
                        (
                            "A CIK is required before filing lineage can be tested."
                            if cik is None
                            else "SEC_USER_AGENT is not configured, so SEC was not queried."
                        ),
                    ),
                    self._check(
                        "sec_edgar",
                        CheckCategory.FUNDAMENTAL_FIELDS,
                        CheckStatus.NOT_VERIFIED,
                        (
                            "A CIK is required before XBRL field coverage can be tested."
                            if cik is None
                            else "SEC_USER_AGENT is not configured, so SEC was not queried."
                        ),
                    ),
                )
            )
        else:
            checks.extend(self._validate_sec_fundamentals(security, cik))

        if self._validate_twelve_data_enabled:
            checks.extend(self._validate_twelve_data(security, start_date, end_date))
        for client in self._market_data_clients:
            checks.extend(
                self._validate_market_data_client(
                    client, security, start_date, end_date
                )
            )
        for provider_code in self._unavailable_market_providers:
            checks.append(
                self._check(
                    provider_code,
                    CheckCategory.DAILY_PRICE,
                    CheckStatus.NOT_VERIFIED,
                    f"{provider_code} is selected but not configured.",
                )
            )
        checks.append(
            self._check(
                "validation_fixture",
                CheckCategory.COMPANY_TYPE_GATE,
                CheckStatus.PASS,
                (
                    "The fixture admits the security to the mature-company model."
                    if security.expected_company_type == "MATURE_OPERATING_COMPANY"
                    else "The fixture prevents this company type from entering the "
                    "general-company rating."
                ),
                {"expectedCompanyType": security.expected_company_type},
            )
        )
        return SecurityValidationResult(
            symbol=security.symbol,
            cik=cik,
            expected_company_type=security.expected_company_type,
            checks=tuple(checks),
        )

    def _validate_market_data_client(
        self,
        client: MarketDataValidationClient,
        security: AcceptanceSecurity,
        start_date: date,
        end_date: date,
    ) -> tuple[ValidationCheck, ...]:
        checks: list[ValidationCheck] = []
        try:
            price = client.fetch_price_summary(
                security.symbol, start_date, end_date
            )
            checks.append(
                self._check(
                    client.provider_code,
                    CheckCategory.DAILY_PRICE,
                    CheckStatus.PASS,
                    f"{client.provider_name} returned normalized daily price history.",
                    {
                        "adjustmentMode": price.adjustment_mode,
                        "observationCount": price.observation_count,
                        "firstDate": price.first_date.isoformat(),
                        "lastDate": price.last_date.isoformat(),
                        "exchange": price.exchange,
                        "instrumentType": price.instrument_type,
                        "currency": price.currency,
                        "sourceReference": price.source_reference,
                        "availableAt": (
                            price.available_at.isoformat()
                            if price.available_at
                            else None
                        ),
                        "ingestedAt": (
                            price.ingested_at.isoformat()
                            if price.ingested_at
                            else None
                        ),
                        "contentHash": price.content_hash,
                        "providerSchemaVersion": price.provider_schema_version,
                        "parserVersion": price.parser_version,
                        "rejectedObservationCount": price.rejected_observation_count,
                    },
                )
            )
            checks.extend(
                (
                    self._check(
                        client.provider_code,
                        CheckCategory.ADJUSTMENT_SEMANTICS,
                        CheckStatus.NOT_VERIFIED,
                        "Normalized adjustment fields were returned, but live "
                        "cross-provider economic equivalence is not accepted.",
                        {"adjustmentMode": price.adjustment_mode},
                    ),
                    self._check(
                        client.provider_code,
                        CheckCategory.SOURCE_LINEAGE,
                        CheckStatus.NOT_VERIFIED,
                        "Source reference, retrieval timestamps, and content hash "
                        "were recorded; historical effective and availability "
                        "semantics remain unverified.",
                        {
                            "sourceReference": price.source_reference,
                            "availableAt": (
                                price.available_at.isoformat()
                                if price.available_at
                                else None
                            ),
                            "ingestedAt": (
                                price.ingested_at.isoformat()
                                if price.ingested_at
                                else None
                            ),
                            "contentHash": price.content_hash,
                        },
                    ),
                )
            )
        except Exception as error:
            from equity_analysis.market_data.provider import MarketDataProviderError

            if not isinstance(error, MarketDataProviderError):
                raise
            checks.append(
                self._check(
                    client.provider_code,
                    CheckCategory.DAILY_PRICE,
                    CheckStatus.NOT_VERIFIED,
                    str(error),
                )
            )
        for test_name, action_type, category in (
            ("split", "split", CheckCategory.SPLIT_HISTORY),
            ("reverse_split", "split", CheckCategory.SPLIT_HISTORY),
            ("dividend", "dividend", CheckCategory.DIVIDEND_HISTORY),
        ):
            if test_name not in security.tests:
                continue
            if action_type == "split" and any(
                check.category == CheckCategory.SPLIT_HISTORY for check in checks
            ):
                continue
            try:
                action = client.fetch_action_summary(
                    security.symbol, action_type, start_date, end_date
                )
                action_status = (
                    CheckStatus.PASS
                    if action.observation_count > 0
                    else CheckStatus.NOT_VERIFIED
                )
                checks.append(
                    self._check(
                        client.provider_code,
                        category,
                        action_status,
                        (
                            f"{client.provider_name} returned {action_type} history."
                            if action_status == CheckStatus.PASS
                            else f"{client.provider_name} returned no {action_type} history."
                        ),
                        {"observationCount": action.observation_count},
                    )
                )
            except Exception as error:
                from equity_analysis.market_data.provider import MarketDataProviderError

                if not isinstance(error, MarketDataProviderError):
                    raise
                checks.append(
                    self._check(
                        client.provider_code,
                        category,
                        CheckStatus.NOT_VERIFIED,
                        str(error),
                    )
                )
        if "symbol_change" in security.tests:
            checks.append(
                self._check(
                    client.provider_code,
                    CheckCategory.SYMBOL_HISTORY,
                    CheckStatus.NOT_VERIFIED,
                    f"{client.provider_name} dated ticker history is not accepted.",
                )
            )
        if "delisted" in security.tests:
            checks.append(
                self._check(
                    client.provider_code,
                    CheckCategory.DELISTING_HISTORY,
                    CheckStatus.NOT_VERIFIED,
                    f"{client.provider_name} delisting proceeds are not accepted.",
                )
            )
        if security.expected_company_type == "MATURE_OPERATING_COMPANY":
            checks.extend(
                (
                    self._check(
                        client.provider_code,
                        CheckCategory.FUNDAMENTAL_FIELDS,
                        CheckStatus.NOT_VERIFIED,
                        f"{client.provider_name} quarterly and annual fundamentals "
                        "are outside the implemented acceptance adapter.",
                    ),
                    self._check(
                        client.provider_code,
                        CheckCategory.HISTORICAL_MARKET_VALUE,
                        CheckStatus.NOT_VERIFIED,
                        f"{client.provider_name} historical shares and market "
                        "capitalization are outside the implemented adapter.",
                    ),
                )
            )
        checks.extend(
            (
                self._check(
                    client.provider_code,
                    CheckCategory.MISSING_DATA_BEHAVIOR,
                    CheckStatus.NOT_VERIFIED,
                    "Offline tests preserve missing values, but live null behavior "
                    "has not completed the acceptance fixture.",
                ),
                self._check(
                    client.provider_code,
                    CheckCategory.RATE_LIMITING,
                    CheckStatus.NOT_VERIFIED,
                    "Offline retry behavior is tested, but live entitlement limits "
                    "and reproducible reruns are not accepted.",
                ),
            )
        )
        return tuple(checks)

    def _validate_sec_fundamentals(
        self,
        security: AcceptanceSecurity,
        cik: str,
    ) -> tuple[ValidationCheck, ...]:
        assert self._sec_client is not None
        try:
            filing = self._sec_client.fetch_latest_filing(cik, security.symbol)
            facts = self._sec_client.fetch_facts_summary(cik, filing.accession_number)
        except SecEdgarError as error:
            return (
                self._check(
                    "sec_edgar",
                    CheckCategory.FUNDAMENTAL_LINEAGE,
                    CheckStatus.NOT_VERIFIED,
                    str(error),
                ),
                self._check(
                    "sec_edgar",
                    CheckCategory.FUNDAMENTAL_FIELDS,
                    CheckStatus.NOT_VERIFIED,
                    "SEC XBRL coverage could not be evaluated.",
                ),
            )
        lineage_status = (
            CheckStatus.PASS if facts.matching_accession_fact_count > 0 else CheckStatus.FAIL
        )
        missing_groups = tuple(
            group for group, present in facts.required_tag_groups_present.items() if not present
        )
        field_status = CheckStatus.PASS if not missing_groups else CheckStatus.NOT_VERIFIED
        return (
            self._check(
                "sec_edgar",
                CheckCategory.FUNDAMENTAL_LINEAGE,
                lineage_status,
                (
                    "The latest filing acceptance timestamp and accession match XBRL facts."
                    if lineage_status == CheckStatus.PASS
                    else "No XBRL fact matched the latest filing accession."
                ),
                {
                    "form": filing.form,
                    "filingDate": filing.filing_date.isoformat(),
                    "acceptanceDatetime": filing.acceptance_datetime.isoformat(),
                    "accessionNumber": filing.accession_number,
                    "reportDate": (filing.report_date.isoformat() if filing.report_date else None),
                    "matchingAccessionFactCount": facts.matching_accession_fact_count,
                },
            ),
            self._check(
                "sec_edgar",
                CheckCategory.FUNDAMENTAL_FIELDS,
                field_status,
                (
                    "Every required v1 XBRL tag group has a supported SEC tag."
                    if not missing_groups
                    else "Some required tag groups need issuer-specific mapping."
                ),
                {
                    "requiredTagGroupsPresent": facts.required_tag_groups_present,
                    "missingTagGroups": missing_groups,
                },
            ),
        )

    def _validate_twelve_data(
        self,
        security: AcceptanceSecurity,
        start_date: date,
        end_date: date,
    ) -> tuple[ValidationCheck, ...]:
        if self._twelve_data_client is None:
            return (
                self._check(
                    "twelve_data",
                    CheckCategory.DAILY_PRICE,
                    CheckStatus.NOT_VERIFIED,
                    "Twelve Data is not configured.",
                ),
            )
        checks: list[ValidationCheck] = []
        try:
            price = self._twelve_data_client.fetch_price_summary(
                security.symbol,
                start_date,
                end_date,
            )
            checks.append(
                self._check(
                    "twelve_data",
                    CheckCategory.DAILY_PRICE,
                    CheckStatus.PASS,
                    "Twelve Data returned adjusted daily price history.",
                    {
                        "adjustmentMode": price.adjustment_mode,
                        "observationCount": price.observation_count,
                        "firstDate": price.first_date.isoformat(),
                        "lastDate": price.last_date.isoformat(),
                        "exchange": price.exchange,
                        "instrumentType": price.instrument_type,
                        "currency": price.currency,
                    },
                )
            )
        except TwelveDataValidationError as error:
            checks.append(
                self._check(
                    "twelve_data",
                    CheckCategory.DAILY_PRICE,
                    CheckStatus.NOT_VERIFIED,
                    str(error),
                )
            )

        if "split" in security.tests or "reverse_split" in security.tests:
            checks.append(self._validate_action(security.symbol, "split"))
        if "dividend" in security.tests:
            checks.append(self._validate_action(security.symbol, "dividend"))
        if "symbol_change" in security.tests:
            checks.append(
                self._check(
                    "twelve_data",
                    CheckCategory.SYMBOL_HISTORY,
                    CheckStatus.NOT_VERIFIED,
                    "The tested Twelve Data contract does not expose a dated ticker event.",
                    {"historicalSymbol": security.historical_symbol},
                )
            )
        if "delisted" in security.tests:
            checks.append(
                self._check(
                    "twelve_data",
                    CheckCategory.DELISTING_HISTORY,
                    CheckStatus.NOT_VERIFIED,
                    "Historical bars alone do not prove delisting proceeds or final return.",
                )
            )
        return tuple(checks)

    def _validate_action(self, symbol: str, action_type: str) -> ValidationCheck:
        assert self._twelve_data_client is not None
        try:
            action = (
                self._twelve_data_client.fetch_splits_summary(symbol)
                if action_type == "split"
                else self._twelve_data_client.fetch_dividends_summary(symbol)
            )
        except TwelveDataValidationError as error:
            return self._check(
                "twelve_data",
                (
                    CheckCategory.SPLIT_HISTORY
                    if action_type == "split"
                    else CheckCategory.DIVIDEND_HISTORY
                ),
                CheckStatus.NOT_VERIFIED,
                str(error),
            )
        status = CheckStatus.PASS if action.observation_count > 0 else CheckStatus.FAIL
        return self._check(
            "twelve_data",
            (
                CheckCategory.SPLIT_HISTORY
                if action_type == "split"
                else CheckCategory.DIVIDEND_HISTORY
            ),
            status,
            (
                f"Twelve Data returned {action_type} history."
                if status == CheckStatus.PASS
                else f"Twelve Data returned no expected {action_type} history."
            ),
            {
                "observationCount": action.observation_count,
                "firstDate": action.first_date.isoformat() if action.first_date else None,
                "lastDate": action.last_date.isoformat() if action.last_date else None,
            },
        )

    @staticmethod
    def _check(
        provider: str,
        category: CheckCategory,
        status: CheckStatus,
        reason: str,
        evidence: dict[str, object] | None = None,
    ) -> ValidationCheck:
        return ValidationCheck(
            provider=provider,
            category=category,
            status=status,
            reason=reason,
            evidence=evidence or {},
        )
