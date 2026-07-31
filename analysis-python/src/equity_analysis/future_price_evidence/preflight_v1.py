from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
from equity_analysis.future_price_evidence.contracts_v1 import (
    ADTV_POLICY_VERSION,
    FUTURE_PRICE_EVIDENCE_VERSION,
    NETWORK_CONFIRMATION,
    YAHOO_CHART_NORMALIZATION_VERSION,
    FuturePriceEvidenceError,
)
from equity_analysis.provider_validation.execution_safety import (
    PhysicalRequestJournal,
)

FUTURE_PRICE_PREFLIGHT_VERSION = "FUTURE-PRICE-EVIDENCE-PREFLIGHT-v1.0.0"
YAHOO_CHART_ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
NYSE_CALENDAR_ENDPOINT = "https://www.nyse.com/markets/hours-calendars"
NASDAQ_CALENDAR_ENDPOINT = "https://www.nasdaq.com/market-activity/stock-market-holiday-schedule"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PREREGISTRATION_SEAL = (
    REPOSITORY_ROOT
    / "docs"
    / "generated"
    / "forward-preregistration-seal-v2-1.json"
)
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs"
    / "generated"
    / "future-completed-session-price-evidence-preflight-v1.json"
)


@dataclass(frozen=True)
class RequestSpec:
    request_identity: str
    symbol: str
    endpoint_category: str
    method: str
    url: str
    configured_weight: int


@dataclass(frozen=True)
class FuturePriceEvidencePlan:
    run_id: str
    target_session: date
    universe_version: str
    universe_file_sha256: str
    symbols: tuple[str, ...]
    requests: tuple[RequestSpec, ...]
    preregistration_seal_hash: str
    preregistration_cutoff: datetime
    plan_hash: str


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _verify_preregistration_seal(path: Path) -> tuple[dict[str, Any], str]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    claim = artifact.get("sealContentHash")
    actual = canonical_hash(
        {key: value for key, value in artifact.items() if key != "sealContentHash"}
    )
    if claim != actual:
        raise FuturePriceEvidenceError("PREREGISTRATION_SEAL_HASH_MISMATCH")
    cutoff = datetime.fromisoformat(artifact["futureDecisionMustBeStrictlyAfter"])
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise FuturePriceEvidenceError("PREREGISTRATION_CUTOFF_NOT_TIMEZONE_AWARE")
    return artifact, actual


def _first_post_preregistration_session(
    cutoff: datetime,
    calendar: UnitedStatesMarketCalendar,
) -> date:
    local_date = cutoff.astimezone(ZoneInfo("America/New_York")).date()
    return calendar.shift_sessions(local_date, 1)


def _yahoo_chart_url(symbol: str, target_session: date) -> str:
    # The endpoint receives an intentionally bounded 45-calendar-day window,
    # which safely covers the 20 completed sessions required for ADTV.
    period2 = int(
        datetime.combine(
            target_session,
            datetime.max.time(),
            tzinfo=ZoneInfo("America/New_York"),
        )
        .astimezone(UTC)
        .timestamp()
    )
    period1 = period2 - (45 * 24 * 60 * 60)
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


def build_future_price_evidence_plan(
    *,
    preregistration_seal_path: Path = DEFAULT_PREREGISTRATION_SEAL,
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
    target_session: date | None = None,
    run_id: str = "FUTURE-PRICE-EVIDENCE-v1-PREFLIGHT",
    calendar: UnitedStatesMarketCalendar | None = None,
) -> FuturePriceEvidencePlan:
    market_calendar = calendar or UnitedStatesMarketCalendar()
    seal, seal_hash = _verify_preregistration_seal(preregistration_seal_path)
    cutoff = datetime.fromisoformat(seal["futureDecisionMustBeStrictlyAfter"])
    earliest_target = _first_post_preregistration_session(cutoff, market_calendar)
    target = target_session or earliest_target
    if target < earliest_target or not market_calendar.is_session(target):
        raise ValueError("Target must be a market session strictly after preregistration")
    universe = load_closed_test_universe(universe_path)
    symbols = universe.refreshable_symbols
    if len(symbols) != 57 or len(set(symbols)) != 57:
        raise FuturePriceEvidenceError("FUTURE_PRICE_SCOPE_MUST_HAVE_57_SYMBOLS")
    if seal["prospectiveUniverseVersion"] != universe.version:
        raise FuturePriceEvidenceError("PREREGISTRATION_UNIVERSE_VERSION_MISMATCH")
    requests = (
        RequestSpec(
            request_identity="official-calendar-nyse",
            symbol="_CALENDAR_NYSE",
            endpoint_category="OFFICIAL_NYSE_CALENDAR",
            method="GET",
            url=NYSE_CALENDAR_ENDPOINT,
            configured_weight=1,
        ),
        RequestSpec(
            request_identity="official-calendar-nasdaq",
            symbol="_CALENDAR_NASDAQ",
            endpoint_category="OFFICIAL_NASDAQ_CALENDAR",
            method="GET",
            url=NASDAQ_CALENDAR_ENDPOINT,
            configured_weight=1,
        ),
        *(
            RequestSpec(
                request_identity=f"yahoo-chart-{symbol}-{target.isoformat()}",
                symbol=symbol,
                endpoint_category="YAHOO_CHART_JSON",
                method="GET",
                url=_yahoo_chart_url(symbol, target),
                configured_weight=1,
            )
            for symbol in symbols
        ),
    )
    plan_body = {
        "version": FUTURE_PRICE_EVIDENCE_VERSION,
        "runId": run_id,
        "targetSession": target,
        "universeVersion": universe.version,
        "universeFileSha256": _file_sha256(universe_path),
        "orderedSymbols": symbols,
        "requests": tuple(request.__dict__ for request in requests),
        "preregistrationSealHash": seal_hash,
        "preregistrationCutoff": cutoff,
    }
    return FuturePriceEvidencePlan(
        run_id=run_id,
        target_session=target,
        universe_version=universe.version,
        universe_file_sha256=_file_sha256(universe_path),
        symbols=symbols,
        requests=requests,
        preregistration_seal_hash=seal_hash,
        preregistration_cutoff=cutoff,
        plan_hash=canonical_hash(plan_body),
    )


def build_future_price_evidence_preflight(
    plan: FuturePriceEvidencePlan,
) -> dict[str, Any]:
    endpoint_counts: dict[str, int] = {}
    for request in plan.requests:
        endpoint_counts[request.endpoint_category] = (
            endpoint_counts.get(request.endpoint_category, 0) + 1
        )
    request_rows = [
        {
            "requestIdentity": item.request_identity,
            "symbol": item.symbol,
            "endpointCategory": item.endpoint_category,
            "method": item.method,
            "url": item.url,
            "configuredWeight": item.configured_weight,
        }
        for item in plan.requests
    ]
    body = {
        "artifactType": "FUTURE_COMPLETED_SESSION_PRICE_EVIDENCE_PREFLIGHT",
        "schemaVersion": FUTURE_PRICE_PREFLIGHT_VERSION,
        "evidenceContractVersion": FUTURE_PRICE_EVIDENCE_VERSION,
        "runId": plan.run_id,
        "planHash": plan.plan_hash,
        "status": "BLOCKED_AWAITING_COMPLETED_SESSION_DUAL_REVIEW_AND_LIVE_APPROVAL",
        "targetSession": plan.target_session.isoformat(),
        "preregistrationCutoff": plan.preregistration_cutoff.isoformat(),
        "preregistrationSealHash": plan.preregistration_seal_hash,
        "universeVersion": plan.universe_version,
        "universeFileSha256": plan.universe_file_sha256,
        "symbolCount": len(plan.symbols),
        "symbols": list(plan.symbols),
        "endpointCounts": dict(sorted(endpoint_counts.items())),
        "expectedPhysicalHttpAttempts": len(plan.requests),
        "physicalHttpAttemptHardCeiling": len(plan.requests),
        "configuredWeightHardCeiling": sum(item.configured_weight for item in plan.requests),
        "providerRetryLimit": 0,
        "requests": request_rows,
        "networkExecutionDefault": False,
        "networkExecutionAuthorized": False,
        "liveConfirmationRequired": True,
        "liveConfirmationTokenSha256": hashlib.sha256(NETWORK_CONFIRMATION.encode())
        .hexdigest()
        .upper(),
        "directYahooChartJsonRequired": True,
        "yfinanceDataFrameAcceptedAsRawTransport": False,
        "rawTransportRequirement": {
            "bodyHashSemantics": "EXACT_HTTP_RESPONSE_BODY_BYTES",
            "envelopeHashRequired": True,
            "responseBodyCheckpointRequired": True,
            "normalizedContentHashMayNotSubstitute": True,
        },
        "completedSessionRequirement": {
            "nyseOfficialBodyHashRequired": True,
            "nasdaqOfficialBodyHashRequired": True,
            "namedReviewerRequired": True,
            "publishedEarlyCloseHandled": True,
            "incompleteSessionStopsRun": True,
        },
        "priceAndActionRequirement": {
            "providerSchemaVersion": "yahoo-chart-v8-json",
            "normalizationVersion": YAHOO_CHART_NORMALIZATION_VERSION,
            "adjustmentMode": "TOTAL_RETURN_ADJUSTED",
            "actionToAdjustedPriceBindingRequired": True,
            "providerRevisionKeyRequired": True,
            "sourceRevisionStatusRequired": True,
        },
        "adtvRequirement": {
            "metricName": "average_daily_dollar_volume",
            "metricVersion": ADTV_POLICY_VERSION,
            "completedSessionCount": 20,
            "formula": "MEAN(RAW_CLOSE * RAW_VOLUME)",
            "sameTargetSessionRequired": True,
            "numericValueGitSafe": False,
        },
        "executionSafety": {
            "crossProcessExecutionLeaseRequired": True,
            "physicalRequestJournalRequired": True,
            "immutableResponseCheckpointRequired": True,
            "idempotentReplayRequired": True,
            "unknownRequestStateStopsRun": True,
            "unknownRequestAutomaticRetryAllowed": False,
            "databaseWritesAuthorized": False,
        },
        "stopConditions": [
            "TARGET_SESSION_NOT_COMPLETED",
            "DUAL_AUTHORITY_CALENDAR_EVIDENCE_MISSING_OR_UNREVIEWED",
            "UNIVERSE_OR_PREREGISTRATION_HASH_CHANGED",
            "NETWORK_NOT_EXPLICITLY_AUTHORIZED",
            "PHYSICAL_REQUEST_STATE_UNKNOWN",
            "ATTEMPT_OR_WEIGHT_CEILING_EXCEEDED",
            "HTTP_AUTH_LIMIT_FORMAT_OR_SEMANTIC_ANOMALY",
            "RAW_TRANSPORT_BODY_OR_ENVELOPE_NOT_DURABLY_HASHED",
            "ACTION_ADJUSTMENT_BINDING_INCOMPLETE",
            "ADTV_20_COMPLETED_SESSIONS_MISSING",
        ],
        "providerNetworkRequestsExecuted": 0,
        "databaseWritesExecuted": 0,
        "scoresOrRanksComputed": False,
        "rawProviderValuesIncluded": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def assert_network_execution_authorized(
    *,
    network_enabled: bool,
    confirmation: str | None,
    as_of: datetime,
    plan: FuturePriceEvidencePlan,
    calendar: UnitedStatesMarketCalendar | None = None,
) -> None:
    if not network_enabled or confirmation != NETWORK_CONFIRMATION:
        raise FuturePriceEvidenceError("NETWORK_EXECUTION_NOT_EXPLICITLY_AUTHORIZED")
    market_calendar = calendar or UnitedStatesMarketCalendar()
    if market_calendar.latest_completed_session(as_of) < plan.target_session:
        raise FuturePriceEvidenceError("TARGET_SESSION_NOT_COMPLETED")


def assert_no_unknown_request_state(
    journal: PhysicalRequestJournal,
    requests: tuple[RequestSpec, ...],
) -> None:
    for request in requests:
        state, _replay = journal.resume(
            request.symbol,
            request.request_identity,
        )
        if state == "UNKNOWN":
            raise FuturePriceEvidenceError(
                f"PHYSICAL_REQUEST_STATE_UNKNOWN[{request.request_identity}]"
            )


def write_immutable_preflight(path: Path, artifact: dict[str, Any]) -> str:
    encoded = (json.dumps(artifact, indent=2, ensure_ascii=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise FuturePriceEvidenceError("IMMUTABLE_PREFLIGHT_CONFLICT")
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest().upper()
