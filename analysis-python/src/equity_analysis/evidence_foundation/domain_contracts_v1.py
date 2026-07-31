from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from equity_analysis.dual_system_contract import (
    finite_decimal_string,
    required_date,
    required_string,
    required_timestamp,
)


class EvidenceDomain(StrEnum):
    DAILY_PRICE = "DAILY_PRICE"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    FUNDAMENTAL = "FUNDAMENTAL"
    CLASSIFICATION = "CLASSIFICATION"
    MARKET_BENCHMARK = "MARKET_BENCHMARK"
    SECTOR_BENCHMARK = "SECTOR_BENCHMARK"
    LIQUIDITY = "LIQUIDITY"


class DomainContractViolation(ValueError):
    """Raised when canonical domain data is incomplete or semantically invalid."""


ADJUSTMENT_MODES = {
    "UNADJUSTED",
    "SPLIT_ADJUSTED",
    "TOTAL_RETURN_ADJUSTED",
}
CORPORATE_ACTION_TYPES = {
    "DIVIDEND",
    "SPLIT",
    "SYMBOL_CHANGE",
    "LISTING",
    "DELISTING",
    "SPIN_OFF",
}
BENCHMARK_KINDS = {"MARKET", "SECTOR", "CASH"}
SUPPORTED_FIELD_CODES = {
    EvidenceDomain.DAILY_PRICE: {
        "OPEN_PRICE",
        "HIGH_PRICE",
        "LOW_PRICE",
        "CLOSE_PRICE",
        "ADJUSTED_CLOSE",
        "VOLUME",
    },
    EvidenceDomain.CORPORATE_ACTION: {"CORPORATE_ACTION"},
    EvidenceDomain.FUNDAMENTAL: {
        "REVENUE",
        "OPERATING_INCOME",
        "NET_INCOME",
        "TOTAL_ASSETS",
        "TOTAL_EQUITY",
        "OPERATING_CASH_FLOW",
        "CAPITAL_EXPENDITURE",
        "FREE_CASH_FLOW",
        "DILUTED_SHARES",
        "CURRENT_ASSETS",
        "CURRENT_LIABILITIES",
        "CASH_AND_EQUIVALENTS",
        "TOTAL_DEBT",
        "INTEREST_EXPENSE",
    },
    EvidenceDomain.CLASSIFICATION: {
        "SECTOR_CODE",
        "INDUSTRY_CODE",
        "COMPANY_TYPE",
    },
    EvidenceDomain.MARKET_BENCHMARK: {"BENCHMARK_MAPPING"},
    EvidenceDomain.SECTOR_BENCHMARK: {"BENCHMARK_MAPPING"},
    EvidenceDomain.LIQUIDITY: {
        "AVERAGE_DAILY_DOLLAR_VOLUME",
        "AVERAGE_DAILY_SHARE_VOLUME",
    },
}
DAILY_PRICE_FIELD_KEYS = {
    "OPEN_PRICE": "open",
    "HIGH_PRICE": "high",
    "LOW_PRICE": "low",
    "CLOSE_PRICE": "close",
    "ADJUSTED_CLOSE": "adjustedClose",
    "VOLUME": "volume",
}


def validate_canonical_data(
    domain: EvidenceDomain,
    value: Any,
    *,
    layer: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DomainContractViolation("canonicalData must be an object")
    _reject_decision_leakage(value)
    validators = {
        EvidenceDomain.DAILY_PRICE: _daily_price,
        EvidenceDomain.CORPORATE_ACTION: _corporate_action,
        EvidenceDomain.FUNDAMENTAL: _fundamental,
        EvidenceDomain.CLASSIFICATION: _classification,
        EvidenceDomain.MARKET_BENCHMARK: _benchmark,
        EvidenceDomain.SECTOR_BENCHMARK: _benchmark,
        EvidenceDomain.LIQUIDITY: _liquidity,
    }
    validators[domain](value, layer=layer, domain=domain)
    return value


def validate_selector_field(domain: EvidenceDomain, field_code: str) -> None:
    if field_code not in SUPPORTED_FIELD_CODES[domain]:
        raise DomainContractViolation(
            f"{field_code} is not a supported selector field for {domain.value}"
        )


def validate_domain_constraints(
    domain: EvidenceDomain,
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DomainContractViolation("domainConstraints must be an object")
    _reject_decision_leakage(value)
    expected = {
        EvidenceDomain.DAILY_PRICE: {
            "sessionDate",
            "adjustmentMode",
            "currency",
            "mic",
            "listingId",
        },
        EvidenceDomain.CORPORATE_ACTION: {"actionType", "effectiveDate"},
        EvidenceDomain.FUNDAMENTAL: {
            "metricCode",
            "periodEnd",
            "unit",
            "currency",
        },
        EvidenceDomain.CLASSIFICATION: {"taxonomyVersion", "effectiveOn"},
        EvidenceDomain.MARKET_BENCHMARK: {
            "benchmarkCode",
            "effectiveOn",
            "sectorCode",
        },
        EvidenceDomain.SECTOR_BENCHMARK: {
            "benchmarkCode",
            "effectiveOn",
            "sectorCode",
        },
        EvidenceDomain.LIQUIDITY: {
            "windowEndSessionDate",
            "windowCompletedSessions",
            "currency",
        },
    }[domain]
    _require_exact_keys(value, expected, domain)
    if domain == EvidenceDomain.DAILY_PRICE:
        required_date(value, "sessionDate")
        if required_string(value, "adjustmentMode") not in ADJUSTMENT_MODES:
            raise DomainContractViolation("Unknown requested adjustment mode")
        for name in ("currency", "mic", "listingId"):
            required_string(value, name)
        _uuid_string(value, "listingId")
    elif domain == EvidenceDomain.CORPORATE_ACTION:
        if required_string(value, "actionType") not in CORPORATE_ACTION_TYPES:
            raise DomainContractViolation("Unknown requested corporate-action type")
        required_date(value, "effectiveDate")
    elif domain == EvidenceDomain.FUNDAMENTAL:
        required_string(value, "metricCode")
        required_date(value, "periodEnd")
        required_string(value, "unit")
        _optional_nonblank_string(value, "currency")
    elif domain == EvidenceDomain.CLASSIFICATION:
        required_string(value, "taxonomyVersion")
        required_date(value, "effectiveOn")
    elif domain in {
        EvidenceDomain.MARKET_BENCHMARK,
        EvidenceDomain.SECTOR_BENCHMARK,
    }:
        required_string(value, "benchmarkCode")
        required_date(value, "effectiveOn")
        sector_code = value.get("sectorCode")
        if domain == EvidenceDomain.SECTOR_BENCHMARK:
            required_string(value, "sectorCode")
        elif sector_code is not None:
            raise DomainContractViolation(
                "Market benchmark request cannot declare a sector"
            )
    else:
        required_date(value, "windowEndSessionDate")
        window = value.get("windowCompletedSessions")
        if not isinstance(window, int) or isinstance(window, bool) or window < 1:
            raise DomainContractViolation(
                "Requested liquidity window must be a positive integer"
            )
        required_string(value, "currency")
    return value


def canonical_data_matches_request(
    domain: EvidenceDomain,
    field_code: str,
    canonical_data: dict[str, Any],
    constraints: dict[str, Any],
) -> bool:
    if domain == EvidenceDomain.DAILY_PRICE:
        field_key = DAILY_PRICE_FIELD_KEYS[field_code]
        return (
            canonical_data.get(field_key) is not None
            and canonical_data["sessionDate"] == constraints["sessionDate"]
            and canonical_data["adjustmentMode"] == constraints["adjustmentMode"]
            and canonical_data["currency"] == constraints["currency"]
        )
    if domain == EvidenceDomain.CORPORATE_ACTION:
        return (
            canonical_data["actionType"] == constraints["actionType"]
            and canonical_data["effectiveDate"] == constraints["effectiveDate"]
        )
    if domain == EvidenceDomain.FUNDAMENTAL:
        return (
            field_code == constraints["metricCode"]
            and canonical_data["metricCode"] == constraints["metricCode"]
            and canonical_data["periodEnd"] == constraints["periodEnd"]
            and canonical_data["unit"] == constraints["unit"]
            and canonical_data["currency"] == constraints["currency"]
        )
    if domain == EvidenceDomain.CLASSIFICATION:
        return (
            canonical_data["taxonomyVersion"] == constraints["taxonomyVersion"]
            and canonical_data["effectiveFrom"] <= constraints["effectiveOn"]
        )
    if domain in {
        EvidenceDomain.MARKET_BENCHMARK,
        EvidenceDomain.SECTOR_BENCHMARK,
    }:
        effective_to = canonical_data["effectiveTo"]
        return (
            canonical_data["benchmarkCode"] == constraints["benchmarkCode"]
            and canonical_data["sectorCode"] == constraints["sectorCode"]
            and canonical_data["effectiveFrom"] <= constraints["effectiveOn"]
            and (
                effective_to is None
                or constraints["effectiveOn"] < effective_to
            )
        )
    return (
        canonical_data["windowEndSessionDate"]
        == constraints["windowEndSessionDate"]
        and canonical_data["windowCompletedSessions"]
        == constraints["windowCompletedSessions"]
        and canonical_data["currency"] == constraints["currency"]
    )


def _daily_price(
    value: dict[str, Any],
    *,
    layer: str,
    domain: EvidenceDomain,
) -> None:
    _require_exact_keys(
        value,
        {
            "sessionDate",
            "adjustmentMode",
            "currency",
            "open",
            "high",
            "low",
            "close",
            "adjustedClose",
            "volume",
        },
        domain,
    )
    _require_layer(layer, "NORMALIZED_OBSERVATION", domain)
    required_date(value, "sessionDate")
    if required_string(value, "adjustmentMode") not in ADJUSTMENT_MODES:
        raise DomainContractViolation("Unknown daily-price adjustment mode")
    required_string(value, "currency")
    for name in ("open", "high", "low", "close"):
        _decimal(value, name)
    adjusted_close = value.get("adjustedClose")
    if adjusted_close is not None:
        if not isinstance(adjusted_close, str):
            raise DomainContractViolation(
                "adjustedClose must be a decimal string or null"
            )
        finite_decimal_string(adjusted_close, "adjustedClose")
    volume = value.get("volume")
    if not isinstance(volume, int) or isinstance(volume, bool) or volume < 0:
        raise DomainContractViolation("volume must be a nonnegative integer")


def _corporate_action(
    value: dict[str, Any],
    *,
    layer: str,
    domain: EvidenceDomain,
) -> None:
    _require_layer(layer, "NORMALIZED_OBSERVATION", domain)
    action_type = required_string(value, "actionType")
    if action_type not in CORPORATE_ACTION_TYPES:
        raise DomainContractViolation("Unknown corporate-action type")
    common = {"actionId", "actionType", "effectiveDate"}
    type_specific = {
        "DIVIDEND": {"amount", "currency"},
        "SPLIT": {"splitFrom", "splitTo"},
        "SYMBOL_CHANGE": {"newTicker"},
        "LISTING": set(),
        "DELISTING": set(),
        "SPIN_OFF": set(),
    }[action_type]
    _require_exact_keys(value, common | type_specific, domain)
    required_date(value, "effectiveDate")
    required_string(value, "actionId")
    if action_type == "DIVIDEND":
        _decimal(value, "amount")
        required_string(value, "currency")
    elif action_type == "SPLIT":
        if _decimal(value, "splitFrom") <= 0 or _decimal(value, "splitTo") <= 0:
            raise DomainContractViolation("Split terms must be positive")
    elif action_type == "SYMBOL_CHANGE":
        required_string(value, "newTicker")


def _fundamental(
    value: dict[str, Any],
    *,
    layer: str,
    domain: EvidenceDomain,
) -> None:
    _require_exact_keys(
        value,
        {
            "metricCode",
            "numericValue",
            "unit",
            "currency",
            "periodStart",
            "periodEnd",
            "fiscalPeriod",
            "formType",
            "accessionNumber",
            "filedAt",
            "mappingVersion",
        },
        domain,
    )
    _require_layer(layer, "NORMALIZED_OBSERVATION", domain)
    required_string(value, "metricCode")
    _decimal(value, "numericValue")
    required_string(value, "unit")
    currency = value.get("currency")
    if currency is not None and (
        not isinstance(currency, str) or not currency.strip()
    ):
        raise DomainContractViolation("currency must be nonblank or null")
    period_start = value.get("periodStart")
    parsed_start = None
    if period_start is not None:
        if not isinstance(period_start, str):
            raise DomainContractViolation("periodStart must be an ISO date or null")
        parsed_start = required_date(value, "periodStart")
    period_end = required_date(value, "periodEnd")
    if parsed_start is not None and parsed_start > period_end:
        raise DomainContractViolation("Fundamental period start cannot exceed end")
    required_string(value, "fiscalPeriod")
    required_string(value, "formType")
    required_string(value, "accessionNumber")
    required_timestamp(value, "filedAt")
    required_string(value, "mappingVersion")


def _classification(
    value: dict[str, Any],
    *,
    layer: str,
    domain: EvidenceDomain,
) -> None:
    _require_exact_keys(
        value,
        {
            "taxonomyCode",
            "taxonomyVersion",
            "sectorCode",
            "industryCode",
            "companyType",
            "effectiveFrom",
        },
        domain,
    )
    _require_layer(layer, "NORMALIZED_OBSERVATION", domain)
    for name in (
        "taxonomyCode",
        "taxonomyVersion",
        "sectorCode",
        "industryCode",
        "companyType",
    ):
        required_string(value, name)
    required_date(value, "effectiveFrom")


def _benchmark(
    value: dict[str, Any],
    *,
    layer: str,
    domain: EvidenceDomain,
) -> None:
    _require_exact_keys(
        value,
        {
            "benchmarkKind",
            "benchmarkCode",
            "benchmarkSecurityId",
            "sectorCode",
            "mappingVersion",
            "effectiveFrom",
            "effectiveTo",
        },
        domain,
    )
    _require_layer(layer, "NORMALIZED_OBSERVATION", domain)
    kind = required_string(value, "benchmarkKind")
    if kind not in BENCHMARK_KINDS:
        raise DomainContractViolation("Unknown benchmark kind")
    expected_kind = (
        "MARKET" if domain == EvidenceDomain.MARKET_BENCHMARK else "SECTOR"
    )
    if kind != expected_kind:
        raise DomainContractViolation(
            f"{domain.value} requires benchmarkKind={expected_kind}"
        )
    required_string(value, "benchmarkCode")
    _uuid_string(value, "benchmarkSecurityId")
    sector_code = value.get("sectorCode")
    if kind == "SECTOR":
        required_string(value, "sectorCode")
    elif sector_code is not None:
        raise DomainContractViolation("Market benchmark cannot declare a sector")
    required_string(value, "mappingVersion")
    effective_from = required_date(value, "effectiveFrom")
    effective_to = value.get("effectiveTo")
    if effective_to is not None:
        if not isinstance(effective_to, str):
            raise DomainContractViolation("effectiveTo must be an ISO date or null")
        if required_date(value, "effectiveTo") <= effective_from:
            raise DomainContractViolation(
                "Benchmark effectiveTo must be after effectiveFrom"
            )


def _liquidity(
    value: dict[str, Any],
    *,
    layer: str,
    domain: EvidenceDomain,
) -> None:
    _require_exact_keys(
        value,
        {
            "windowCompletedSessions",
            "windowEndSessionDate",
            "validObservationCount",
            "averageDailyDollarVolume",
            "averageDailyShareVolume",
            "currency",
            "liquidityPolicyVersion",
        },
        domain,
    )
    _require_layer(layer, "ENGINE_DERIVED", domain)
    window = value.get("windowCompletedSessions")
    count = value.get("validObservationCount")
    if (
        not isinstance(window, int)
        or isinstance(window, bool)
        or window < 1
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 1
        or count > window
    ):
        raise DomainContractViolation(
            "Liquidity window and observation count are invalid"
        )
    required_date(value, "windowEndSessionDate")
    _decimal(value, "averageDailyDollarVolume")
    _decimal(value, "averageDailyShareVolume")
    required_string(value, "currency")
    required_string(value, "liquidityPolicyVersion")


def _decimal(value: dict[str, Any], name: str):
    raw = required_string(value, name)
    return finite_decimal_string(raw, name)


def _require_layer(
    actual: str,
    expected: str,
    domain: EvidenceDomain,
) -> None:
    if actual != expected:
        raise DomainContractViolation(
            f"{domain.value} requires evidence layer {expected}"
        )


def _require_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    domain: EvidenceDomain,
) -> None:
    if set(value) != expected:
        raise DomainContractViolation(
            f"{domain.value} canonicalData must match its exact field contract"
        )


def _optional_nonblank_string(value: dict[str, Any], name: str) -> None:
    item = value.get(name)
    if item is not None and (not isinstance(item, str) or not item.strip()):
        raise DomainContractViolation(f"{name} must be nonblank or null")


def _uuid_string(value: dict[str, Any], name: str) -> str:
    item = required_string(value, name)
    try:
        UUID(item)
    except ValueError as exc:
        raise DomainContractViolation(f"{name} must be a UUID") from exc
    return item


def _reject_decision_leakage(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("_", "").replace("-", "")
            if normalized in {
                "score",
                "deterministicscore",
                "providerscore",
                "rank",
                "ranking",
                "providerrank",
                "providerranking",
                "recommendation",
                "providerrecommendation",
                "providernativevalue",
            }:
                raise DomainContractViolation(
                    "Canonical and selector data cannot contain provider-native "
                    "score, rank, or recommendation fields"
                )
            _reject_decision_leakage(child)
    elif isinstance(value, list):
        for child in value:
            _reject_decision_leakage(child)
