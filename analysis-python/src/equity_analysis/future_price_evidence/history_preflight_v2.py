from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.daily_refresh.universe import (
    DEFAULT_UNIVERSE_PATH,
    load_closed_test_universe,
)
from equity_analysis.forward_validation.preregistration_seal_v22 import (
    EXTERNAL_REFERENCE_ARTIFACT_RELATIVE_PATH,
    SEAL_ARTIFACT_V22_RELATIVE_PATH,
)
from equity_analysis.future_price_evidence.history_coverage_v2 import (
    FUTURE_PRICE_HISTORY_COVERAGE_VERSION,
    MOMENTUM_12_1_REQUIRED_SESSIONS,
)
from equity_analysis.future_price_evidence.preflight_v1 import (
    NASDAQ_CALENDAR_ENDPOINT,
    NYSE_CALENDAR_ENDPOINT,
    YAHOO_CHART_ENDPOINT,
    RequestSpec,
)

FUTURE_PRICE_HISTORY_PREFLIGHT_VERSION = "FUTURE-PRICE-HISTORY-PREFLIGHT-v2.0.0"
FUTURE_PRICE_SYMBOL_PLAN_VERSION = "FORWARD-PRICE-SYMBOL-PLAN-v2.0.0"
EXTERNAL_REFERENCE_UNIVERSE_VERSION = (
    "FORWARD-EXTERNAL-BENCHMARK-REFERENCE-UNIVERSE-v2.2.0"
)
PREREGISTRATION_SEAL_VERSION = "FORWARD-PREREGISTRATION-SEAL-v2.2.0"
HISTORY_WINDOW_CALENDAR_DAYS = 420
EXPECTED_BASE_SYMBOLS = 57
EXPECTED_ADDITIONAL_SECTOR_ETFS = 10
EXPECTED_PRICE_SYMBOLS = 67
EXPECTED_TOTAL_HTTP_ATTEMPTS = 69
EXISTING_REFERENCE_SYMBOLS = frozenset({"SPY", "XLK"})
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_V22_SEAL_PATH = REPOSITORY_ROOT / SEAL_ARTIFACT_V22_RELATIVE_PATH
DEFAULT_EXTERNAL_REFERENCE_PATH = (
    REPOSITORY_ROOT / EXTERNAL_REFERENCE_ARTIFACT_RELATIVE_PATH
)
DEFAULT_HISTORY_PREFLIGHT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/generated/future-price-history-preflight-v2.json"
)


@dataclass(frozen=True)
class ExternalReferencePriceTargetV2:
    public_security_id: str
    symbol: str
    sector: str
    reference_role: str
    identity_source: str


@dataclass(frozen=True)
class FuturePriceHistoryPlanV2:
    version: str
    symbol_plan_version: str
    target_session: date
    universe_version: str
    universe_file_sha256: str
    base_symbol_plan_hash: str
    external_reference_universe_hash: str
    external_reference_rows_hash: str
    ordered_symbols_hash: str
    symbol_plan_hash: str
    preregistration_seal_hash: str
    preregistration_cutoff: datetime
    base_symbols: tuple[str, ...]
    additional_reference_targets: tuple[ExternalReferencePriceTargetV2, ...]
    ordered_symbols: tuple[str, ...]
    requests: tuple[RequestSpec, ...]
    plan_hash: str

    @property
    def additional_reference_symbols(self) -> tuple[str, ...]:
        return tuple(item.symbol for item in self.additional_reference_targets)


def build_future_price_history_plan_v2(
    *,
    base_symbols: tuple[str, ...],
    target_session: date,
    universe_version: str,
    universe_file_sha256: str,
    preregistration_seal_path: Path = DEFAULT_V22_SEAL_PATH,
    external_reference_path: Path = DEFAULT_EXTERNAL_REFERENCE_PATH,
    symbol_plan_version: str = FUTURE_PRICE_SYMBOL_PLAN_VERSION,
) -> FuturePriceHistoryPlanV2:
    seal, seal_hash, cutoff = _load_v22_seal(preregistration_seal_path)
    external_artifact, external_hash = _load_external_reference_universe(
        external_reference_path
    )
    _verify_seal_external_binding(
        seal=seal,
        external_artifact=external_artifact,
        external_path=external_reference_path,
        external_hash=external_hash,
    )
    normalized_base = tuple(symbol.strip().upper() for symbol in base_symbols)
    _verify_frozen_base(
        normalized_base,
        universe_version=universe_version,
        universe_file_sha256=universe_file_sha256,
    )
    if target_session <= cutoff.astimezone(
        ZoneInfo("America/New_York")
    ).date():
        raise ValueError(
            "Target session must be strictly after the v2.2 preregistration cutoff"
        )
    first_post_cutoff_session = UnitedStatesMarketCalendar().shift_sessions(
        cutoff.astimezone(ZoneInfo("America/New_York")).date(),
        1,
    )
    if target_session != first_post_cutoff_session:
        raise ValueError(
            "Target session must equal the first completed-session candidate "
            "after the v2.2 cutoff"
        )
    if not symbol_plan_version.strip():
        raise ValueError("Symbol-plan version is required")

    external_targets = _external_targets(external_artifact)
    additional_symbols = tuple(item.symbol for item in external_targets)
    if set(additional_symbols) & set(normalized_base):
        raise ValueError("External reference targets must not duplicate the base plan")
    symbols = (*normalized_base, *additional_symbols)
    if len(symbols) != EXPECTED_PRICE_SYMBOLS or len(set(symbols)) != len(symbols):
        raise ValueError("History v2 requires exactly 67 unique price symbols")

    base_symbol_plan_hash = canonical_hash(
        {
            "universeVersion": universe_version,
            "universeFileSha256": universe_file_sha256.upper(),
            "orderedSymbols": normalized_base,
        }
    )
    external_rows_payload = tuple(
        {
            "publicSecurityId": item.public_security_id,
            "symbol": item.symbol,
            "sector": item.sector,
            "referenceRole": item.reference_role,
            "identitySource": item.identity_source,
        }
        for item in external_targets
    )
    external_reference_rows_hash = canonical_hash(external_rows_payload)
    ordered_symbols_hash = canonical_hash(symbols)
    symbol_plan_hash = canonical_hash(
        {
            "symbolPlanVersion": symbol_plan_version,
            "baseSymbolPlanHash": base_symbol_plan_hash,
            "externalReferenceUniverseHash": external_hash,
            "externalReferenceRowsHash": external_reference_rows_hash,
            "orderedSymbolsHash": ordered_symbols_hash,
        }
    )
    requests = _requests(symbols, target_session)
    body = {
        "version": FUTURE_PRICE_HISTORY_PREFLIGHT_VERSION,
        "coverageContractVersion": FUTURE_PRICE_HISTORY_COVERAGE_VERSION,
        "symbolPlanVersion": symbol_plan_version,
        "targetSession": target_session,
        "universeVersion": universe_version,
        "universeFileSha256": universe_file_sha256.upper(),
        "baseSymbolPlanHash": base_symbol_plan_hash,
        "externalReferenceUniverseHash": external_hash,
        "externalReferenceRowsHash": external_reference_rows_hash,
        "orderedSymbolsHash": ordered_symbols_hash,
        "symbolPlanHash": symbol_plan_hash,
        "preregistrationSealHash": seal_hash,
        "preregistrationCutoff": cutoff,
        "baseSymbols": normalized_base,
        "additionalReferenceTargets": external_rows_payload,
        "orderedSymbols": symbols,
        "requests": tuple(request.__dict__ for request in requests),
        "minimumParsedCompletedSessions": MOMENTUM_12_1_REQUIRED_SESSIONS,
        "historyWindowCalendarDays": HISTORY_WINDOW_CALENDAR_DAYS,
        "providerRetryLimit": 0,
    }
    return FuturePriceHistoryPlanV2(
        version=FUTURE_PRICE_HISTORY_PREFLIGHT_VERSION,
        symbol_plan_version=symbol_plan_version,
        target_session=target_session,
        universe_version=universe_version,
        universe_file_sha256=universe_file_sha256.upper(),
        base_symbol_plan_hash=base_symbol_plan_hash,
        external_reference_universe_hash=external_hash,
        external_reference_rows_hash=external_reference_rows_hash,
        ordered_symbols_hash=ordered_symbols_hash,
        symbol_plan_hash=symbol_plan_hash,
        preregistration_seal_hash=seal_hash,
        preregistration_cutoff=cutoff,
        base_symbols=normalized_base,
        additional_reference_targets=external_targets,
        ordered_symbols=symbols,
        requests=requests,
        plan_hash=canonical_hash(body),
    )


def build_future_price_history_preflight_v2(
    plan: FuturePriceHistoryPlanV2,
) -> dict[str, object]:
    endpoint_counts: dict[str, int] = {}
    for request in plan.requests:
        endpoint_counts[request.endpoint_category] = (
            endpoint_counts.get(request.endpoint_category, 0) + 1
        )
    body: dict[str, object] = {
        "artifactType": "FUTURE_COMPLETED_SESSION_PRICE_HISTORY_PREFLIGHT",
        "schemaVersion": FUTURE_PRICE_HISTORY_PREFLIGHT_VERSION,
        "coverageContractVersion": FUTURE_PRICE_HISTORY_COVERAGE_VERSION,
        "symbolPlanVersion": plan.symbol_plan_version,
        "planHash": plan.plan_hash,
        "status": (
            "BLOCKED_AWAITING_TARGET_SESSION_COMPLETION_AND_LIVE_APPROVAL"
        ),
        "targetSession": plan.target_session.isoformat(),
        "preregistrationCutoff": plan.preregistration_cutoff.isoformat(),
        "preregistrationSealHash": plan.preregistration_seal_hash,
        "universeVersion": plan.universe_version,
        "universeFileSha256": plan.universe_file_sha256,
        "baseSymbolPlanHash": plan.base_symbol_plan_hash,
        "externalReferenceUniverseHash": (
            plan.external_reference_universe_hash
        ),
        "externalReferenceRowsHash": plan.external_reference_rows_hash,
        "orderedSymbolsHash": plan.ordered_symbols_hash,
        "symbolPlanHash": plan.symbol_plan_hash,
        "basePriceSymbolCount": len(plan.base_symbols),
        "additionalReferenceSymbolCount": len(
            plan.additional_reference_targets
        ),
        "priceSymbolCount": len(plan.ordered_symbols),
        "orderedSymbols": list(plan.ordered_symbols),
        "additionalReferenceTargets": [
            {
                "publicSecurityId": item.public_security_id,
                "symbol": item.symbol,
                "sector": item.sector,
                "referenceRole": item.reference_role,
                "identitySource": item.identity_source,
            }
            for item in plan.additional_reference_targets
        ],
        "endpointCounts": dict(sorted(endpoint_counts.items())),
        "expectedPhysicalHttpAttempts": len(plan.requests),
        "physicalHttpAttemptHardCeiling": len(plan.requests),
        "configuredWeightHardCeiling": sum(
            item.configured_weight for item in plan.requests
        ),
        "providerRetryLimit": 0,
        "historyWindowCalendarDays": HISTORY_WINDOW_CALENDAR_DAYS,
        "minimumParsedCompletedSessionsPerSymbol": (
            MOMENTUM_12_1_REQUIRED_SESSIONS
        ),
        "parsedCompletedSessionCountEnforced": True,
        "adjustmentMode": "TOTAL_RETURN_ADJUSTED",
        "networkExecutionAuthorized": False,
        "databaseWritesAuthorized": False,
        "scoresOrRanksComputed": False,
        "rawProviderValuesIncluded": False,
        "stopConditions": [
            "V2_2_PREREGISTRATION_OR_SYMBOL_PLAN_HASH_CHANGED",
            "TARGET_SESSION_NOT_STRICTLY_AFTER_V2_2_CUTOFF",
            "TARGET_SESSION_NOT_COMPLETED",
            "DUAL_AUTHORITY_CALENDAR_EVIDENCE_MISSING_OR_UNREVIEWED",
            "PRICE_SYMBOL_COUNT_NOT_67",
            "PARSED_COMPLETED_SESSIONS_BELOW_253",
            "PHYSICAL_REQUEST_STATE_UNKNOWN",
            "ATTEMPT_OR_WEIGHT_CEILING_EXCEEDED",
            "HTTP_AUTH_LIMIT_FORMAT_OR_SEMANTIC_ANOMALY",
        ],
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_future_price_history_preflight_v2(
    path: Path,
    artifact: dict[str, object],
) -> str:
    claim = artifact.get("artifactContentHash")
    actual = canonical_hash(
        {
            key: value
            for key, value in artifact.items()
            if key != "artifactContentHash"
        }
    )
    if claim != actual:
        raise ValueError("Future price history preflight content hash mismatch")
    encoded = (
        json.dumps(
            artifact,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError("IMMUTABLE_FUTURE_PRICE_HISTORY_PREFLIGHT_CONFLICT")
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest().upper()


def _load_v22_seal(path: Path) -> tuple[dict[str, Any], str, datetime]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if artifact.get("schemaVersion") != PREREGISTRATION_SEAL_VERSION:
        raise ValueError("Formal history preflight requires the v2.2 seal")
    claim = artifact.get("sealContentHash")
    actual = canonical_hash(
        {key: value for key, value in artifact.items() if key != "sealContentHash"}
    )
    if claim != actual:
        raise ValueError("V2.2 preregistration seal content hash mismatch")
    cutoff = datetime.fromisoformat(artifact["futureDecisionMustBeStrictlyAfter"])
    if cutoff.tzinfo is None:
        raise ValueError("V2.2 preregistration cutoff must be timezone-aware")
    return artifact, actual, cutoff


def _load_external_reference_universe(
    path: Path,
) -> tuple[dict[str, Any], str]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if artifact.get("schemaVersion") != EXTERNAL_REFERENCE_UNIVERSE_VERSION:
        raise ValueError("External reference universe version is not supported")
    claim = artifact.get("artifactContentHash")
    actual = canonical_hash(
        {
            key: value
            for key, value in artifact.items()
            if key != "artifactContentHash"
        }
    )
    if claim != actual:
        raise ValueError("External reference universe content hash mismatch")
    return artifact, actual


def _verify_seal_external_binding(
    *,
    seal: dict[str, Any],
    external_artifact: dict[str, Any],
    external_path: Path,
    external_hash: str,
) -> None:
    binding = seal.get("externalReferenceUniverse")
    if not isinstance(binding, dict):
        raise ValueError("V2.2 seal lacks the external reference binding")
    actual_file_hash = (
        f"sha256:{hashlib.sha256(external_path.read_bytes()).hexdigest()}"
    )
    expected_path = EXTERNAL_REFERENCE_ARTIFACT_RELATIVE_PATH.as_posix()
    if binding.get("path") != expected_path:
        raise ValueError("V2.2 seal binds a different external reference path")
    if binding.get("fileSha256") != actual_file_hash:
        raise ValueError("External reference universe file hash mismatch")
    if binding.get("artifactContentHash") != external_hash:
        raise ValueError("External reference universe is not bound by the v2.2 seal")
    if external_artifact.get("priceEvidenceState") != "DATA_PENDING":
        raise ValueError("Formal preflight expects pending external price evidence")


def _external_targets(
    artifact: dict[str, Any],
) -> tuple[ExternalReferencePriceTargetV2, ...]:
    references = artifact.get("references")
    if not isinstance(references, list):
        raise ValueError("External reference universe rows are missing")
    symbols = {str(row.get("symbol")) for row in references}
    if not EXISTING_REFERENCE_SYMBOLS.issubset(symbols):
        raise ValueError("The external universe must retain SPY and XLK")
    rows = tuple(
        ExternalReferencePriceTargetV2(
            public_security_id=str(row["publicSecurityId"]),
            symbol=str(row["symbol"]).strip().upper(),
            sector=str(row["sector"]),
            reference_role=str(row["referenceRole"]),
            identity_source=str(row["identitySource"]),
        )
        for row in references
        if row.get("identitySource") == "EXTERNAL_REFERENCE_NAMESPACE"
    )
    if len(rows) != EXPECTED_ADDITIONAL_SECTOR_ETFS:
        raise ValueError("External reference universe must add exactly ten ETFs")
    if len({item.symbol for item in rows}) != len(rows):
        raise ValueError("External reference symbols must be unique")
    if any(item.reference_role != "SECTOR" or not item.sector for item in rows):
        raise ValueError("External price targets require sector reference mappings")
    if len({item.public_security_id for item in rows}) != len(rows):
        raise ValueError("External reference public security IDs must be unique")
    return rows


def _verify_frozen_base(
    normalized_base: tuple[str, ...],
    *,
    universe_version: str,
    universe_file_sha256: str,
) -> None:
    if len(normalized_base) != EXPECTED_BASE_SYMBOLS:
        raise ValueError("History v2 requires exactly 57 base price symbols")
    if len(normalized_base) != len(set(normalized_base)):
        raise ValueError("Base price symbols must be unique")
    _require_hash(universe_file_sha256, "Universe file SHA-256")
    frozen_universe = load_closed_test_universe(DEFAULT_UNIVERSE_PATH)
    actual_universe_sha256 = hashlib.sha256(
        DEFAULT_UNIVERSE_PATH.read_bytes()
    ).hexdigest().upper()
    if universe_version != frozen_universe.version:
        raise ValueError("Base universe version does not match the frozen artifact")
    if universe_file_sha256.upper() != actual_universe_sha256:
        raise ValueError("Base universe file hash does not match the frozen artifact")
    if normalized_base != frozen_universe.refreshable_symbols:
        raise ValueError(
            "Base symbols must exactly match the frozen predecessor plan and order"
        )


def _requests(
    symbols: tuple[str, ...],
    target_session: date,
) -> tuple[RequestSpec, ...]:
    return (
        RequestSpec(
            request_identity="official-calendar-nyse-history-v2",
            symbol="_CALENDAR_NYSE",
            endpoint_category="OFFICIAL_NYSE_CALENDAR",
            method="GET",
            url=NYSE_CALENDAR_ENDPOINT,
            configured_weight=1,
        ),
        RequestSpec(
            request_identity="official-calendar-nasdaq-history-v2",
            symbol="_CALENDAR_NASDAQ",
            endpoint_category="OFFICIAL_NASDAQ_CALENDAR",
            method="GET",
            url=NASDAQ_CALENDAR_ENDPOINT,
            configured_weight=1,
        ),
        *(
            RequestSpec(
                request_identity=(
                    f"yahoo-chart-history-v2-{symbol}-{target_session.isoformat()}"
                ),
                symbol=symbol,
                endpoint_category="YAHOO_CHART_JSON",
                method="GET",
                url=_history_url(symbol, target_session),
                configured_weight=1,
            )
            for symbol in symbols
        ),
    )


def _history_url(symbol: str, target_session: date) -> str:
    period2 = int(
        datetime.combine(
            target_session,
            datetime.max.time(),
            tzinfo=ZoneInfo("America/New_York"),
        )
        .astimezone(UTC)
        .timestamp()
    )
    period1 = int(
        (
            datetime.fromtimestamp(period2, tz=UTC)
            - timedelta(days=HISTORY_WINDOW_CALENDAR_DAYS)
        ).timestamp()
    )
    query = urlencode(
        {
            "period1": period1,
            "period2": period2 + 1,
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
    )
    return f"{YAHOO_CHART_ENDPOINT.format(symbol=symbol)}?{query}"


def _require_hash(value: str, label: str) -> None:
    candidate = value.removeprefix("sha256:")
    if len(candidate) != 64 or any(
        character not in "0123456789abcdefABCDEF"
        for character in candidate
    ):
        raise ValueError(f"{label} must be a SHA-256 hash")
