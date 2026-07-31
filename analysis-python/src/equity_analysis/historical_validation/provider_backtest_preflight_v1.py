from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "PRACTICAL-LONG-HORIZON-BACKTEST-DATA-v1.0.0"
PREFLIGHT_VERSION = "PROVIDER-BACKTEST-PREFLIGHT-v1.0.0"
UNIVERSE_SIZE = 100
MARKET_BENCHMARK = "SPY"
PRICE_START_DATE = "2014-01-01"
PRICE_END_DATE = "2026-07-28"
EODHD_DAILY_ALLOWANCE = 100_000
EODHD_MINIMUM_RESERVE = 10_000
EODHD_RETRY_LIMIT = 0
YAHOO_RETRY_LIMIT = 0
LONG_HORIZON_SESSIONS = (252, 504, 756, 1260)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
BASE_UNIVERSE_PATH = Path(
    "analysis-python/resources/universes/"
    "market-intelligence-closed-test-us-v1.json"
)
EXPANSION_UNIVERSE_PATH = Path(
    "analysis-python/tests/fixtures/provider_expansion_universe_v2.json"
)
FORMULA_INPUT_AGGREGATE_PATH = Path(
    "docs/generated/formula-ready-243-final-aggregate-v1.json"
)
PRICE_MANIFEST_PATH = Path(
    "docs/generated/"
    "historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json"
)
CACHED_TRANSPORT_AUDIT_PATH = Path(
    "docs/generated/provider-cached-transport-semantic-audit-v1.2.json"
)


class ProviderBacktestPreflightError(RuntimeError):
    """Raised when the practical backtest acquisition plan is not reproducible."""


@dataclass(frozen=True)
class SelectedSecurity:
    security_id: str
    symbol: str
    role: str
    sector: str
    source_ordinal: int
    formula_input_content_hash: str
    formula_input_storage_reference: str
    historical_price_state: str


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProviderBacktestPreflightError(f"EXPECTED_JSON_OBJECT[{path}]")
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest().upper()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _verify_artifact(value: dict[str, Any], *, label: str) -> str:
    claimed = value.get("artifactContentHash")
    if not isinstance(claimed, str):
        raise ProviderBacktestPreflightError(f"{label}_CONTENT_HASH_MISSING")
    body = dict(value)
    body.pop("artifactContentHash")
    actual = canonical_hash(body)
    if claimed.upper() != actual:
        raise ProviderBacktestPreflightError(f"{label}_CONTENT_HASH_MISMATCH")
    return actual


def _formula_ready_records(
    aggregate: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if aggregate.get("aggregateStatus") != "COMPLETE_WITH_INSUFFICIENT_DATA":
        raise ProviderBacktestPreflightError("FORMULA_INPUT_AGGREGATE_NOT_COMPLETE")
    if int(aggregate.get("uniqueSecurityCount", -1)) != 243:
        raise ProviderBacktestPreflightError("FORMULA_INPUT_SCOPE_CHANGED")
    records: dict[str, dict[str, Any]] = {}
    for raw in aggregate.get("securities", []):
        if not isinstance(raw, dict) or raw.get("status") != "FORMULA_READY":
            continue
        symbol = str(raw.get("symbol", "")).strip().upper()
        content_hash = str(raw.get("contentHash", "")).strip().upper()
        if (
            not symbol
            or len(content_hash) != 64
            or not bool(raw.get("formulaCoverageComplete"))
        ):
            raise ProviderBacktestPreflightError(
                f"INVALID_FORMULA_READY_RECEIPT[{symbol or 'UNKNOWN'}]"
            )
        if symbol in records:
            raise ProviderBacktestPreflightError(
                f"DUPLICATE_FORMULA_READY_RECEIPT[{symbol}]"
            )
        storage_reference = raw.get("storageReference")
        if not storage_reference:
            storage_reference = (
                "storage/provider-validation/scoring-inputs-v2/"
                f"{symbol}/{content_hash}.json"
            )
        records[symbol] = {
            **raw,
            "contentHash": content_hash,
            "storageReference": str(storage_reference).replace("\\", "/"),
        }
    if len(records) != 223:
        raise ProviderBacktestPreflightError("FORMULA_READY_COUNT_CHANGED")
    return records


def _complete_cached_transport_symbols(
    audit: dict[str, Any],
) -> set[str]:
    required = {"fundamentals", "eod", "historical-market-cap"}
    by_symbol: dict[str, set[str]] = defaultdict(set)
    for raw in audit.get("responseEvidence", []):
        if not isinstance(raw, dict):
            raise ProviderBacktestPreflightError(
                "INVALID_CACHED_TRANSPORT_EVIDENCE"
            )
        endpoint = str(raw.get("endpoint", ""))
        if endpoint not in required:
            continue
        for raw_symbol in raw.get("symbols", []):
            by_symbol[str(raw_symbol).strip().upper()].add(endpoint)
    complete = {
        symbol
        for symbol, endpoints in by_symbol.items()
        if endpoints == required
    }
    if len(complete) != 216:
        raise ProviderBacktestPreflightError(
            "COMPLETE_CACHED_TRANSPORT_SCOPE_CHANGED"
        )
    return complete


def _price_records(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (
        manifest.get("status") != "COMPLETE"
        or manifest.get("startDate") != PRICE_START_DATE
        or manifest.get("endDate") != PRICE_END_DATE
        or int(manifest.get("completedSecurityCount", -1)) != 56
        or int(manifest.get("failedSecurityCount", -1)) != 0
    ):
        raise ProviderBacktestPreflightError("HISTORICAL_PRICE_MANIFEST_CHANGED")
    records: dict[str, dict[str, Any]] = {}
    for raw in manifest.get("records", []):
        symbol = str(raw.get("symbol", "")).strip().upper()
        if not symbol or symbol in records:
            raise ProviderBacktestPreflightError(
                f"INVALID_HISTORICAL_PRICE_RECEIPT[{symbol or 'UNKNOWN'}]"
            )
        if (
            symbol == MARKET_BENCHMARK
            and raw.get("firstTradingDate") > "2014-01-02"
        ):
            raise ProviderBacktestPreflightError(
                f"HISTORICAL_PRICE_START_TOO_LATE[{symbol}]"
            )
        if raw.get("lastTradingDate") != PRICE_END_DATE:
            raise ProviderBacktestPreflightError(
                f"HISTORICAL_PRICE_END_CHANGED[{symbol}]"
            )
        records[symbol] = raw
    if MARKET_BENCHMARK not in records:
        raise ProviderBacktestPreflightError("SPY_BENCHMARK_PRICE_MISSING")
    return records


def _expansion_candidates(
    expansion: dict[str, Any],
    *,
    ready_symbols: set[str],
    retained_symbols: set[str],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in expansion.get("candidates", []):
        if not isinstance(raw, dict):
            raise ProviderBacktestPreflightError("INVALID_EXPANSION_CANDIDATE")
        symbol = str(raw.get("symbol", "")).strip().upper()
        if (
            symbol in ready_symbols
            and symbol not in retained_symbols
            and raw.get("candidateRole") in {"PRIMARY", "RESERVE"}
            and raw.get("companyType") == "MATURE_OPERATING_COMPANY"
        ):
            sector = str(raw.get("sector", "")).strip()
            if not sector:
                raise ProviderBacktestPreflightError(
                    f"EXPANSION_SECTOR_MISSING[{symbol}]"
                )
            grouped[sector].append(raw)
    for candidates in grouped.values():
        candidates.sort(
            key=lambda item: (
                int(item.get("sourceOrdinal", 0)),
                str(item.get("symbol")),
            )
        )
    return grouped


def _round_robin_expansion(
    grouped: dict[str, list[dict[str, Any]]],
    *,
    required: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    sectors = sorted(grouped)
    while len(selected) < required:
        progressed = False
        for sector in sectors:
            candidates = grouped[sector]
            if candidates:
                selected.append(candidates.pop(0))
                progressed = True
                if len(selected) == required:
                    break
        if not progressed:
            raise ProviderBacktestPreflightError(
                "INSUFFICIENT_FORMULA_READY_EXPANSION_SECURITIES"
            )
    return selected


def _retained_sector_map(expansion: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in expansion.get("candidates", []):
        if isinstance(raw, dict):
            symbol = str(raw.get("symbol", "")).strip().upper()
            sector = str(raw.get("sector", "")).strip()
            if symbol and sector and symbol not in result:
                result[symbol] = sector
    return result


def select_backtest_universe(
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[SelectedSecurity, ...]:
    base = _load_object(repository_root / BASE_UNIVERSE_PATH)
    expansion = _load_object(repository_root / EXPANSION_UNIVERSE_PATH)
    aggregate = _load_object(repository_root / FORMULA_INPUT_AGGREGATE_PATH)
    price_manifest = _load_object(repository_root / PRICE_MANIFEST_PATH)
    cached_transport = _load_object(
        repository_root / CACHED_TRANSPORT_AUDIT_PATH
    )
    _verify_artifact(aggregate, label="FORMULA_INPUT_AGGREGATE")
    _verify_artifact(price_manifest, label="HISTORICAL_PRICE_MANIFEST")
    _verify_artifact(cached_transport, label="CACHED_TRANSPORT_AUDIT")
    ready = _formula_ready_records(aggregate)
    complete_transport = _complete_cached_transport_symbols(cached_transport)
    _price_records(price_manifest)

    ordered_base = [
        str(symbol).strip().upper()
        for role in ("PRIMARY", "RESERVE")
        for symbol in base.get("roles", {}).get(role, [])
    ]
    retained = [
        symbol
        for symbol in ordered_base
        if symbol in ready and symbol in complete_transport
    ]
    if len(retained) != 42:
        raise ProviderBacktestPreflightError("RETAINED_READY_COUNT_CHANGED")

    grouped = _expansion_candidates(
        expansion,
        ready_symbols=set(ready) & complete_transport,
        retained_symbols=set(retained),
    )
    additions = _round_robin_expansion(
        grouped,
        required=UNIVERSE_SIZE - len(retained),
    )
    sector_by_symbol = _retained_sector_map(expansion)
    selected: list[SelectedSecurity] = []
    for ordinal, symbol in enumerate(retained, start=1):
        receipt = ready[symbol]
        selected.append(
            SelectedSecurity(
                security_id=f"US:{symbol}",
                symbol=symbol,
                role="RETAINED_V1",
                sector=sector_by_symbol[symbol],
                source_ordinal=ordinal,
                formula_input_content_hash=receipt["contentHash"],
                formula_input_storage_reference=receipt["storageReference"],
                historical_price_state="REUSE_CONTROLLED_EODHD_DAILY_PRICE",
            )
        )
    for raw in additions:
        symbol = str(raw["symbol"]).upper()
        receipt = ready[symbol]
        selected.append(
            SelectedSecurity(
                security_id=f"US:{symbol}",
                symbol=symbol,
                role=f"EXPANSION_{raw['candidateRole']}",
                sector=str(raw["sector"]),
                source_ordinal=int(raw["sourceOrdinal"]),
                formula_input_content_hash=receipt["contentHash"],
                formula_input_storage_reference=receipt["storageReference"],
                historical_price_state="REUSE_CONTROLLED_EODHD_DAILY_PRICE",
            )
        )
    if len(selected) != UNIVERSE_SIZE or len(
        {item.symbol for item in selected}
    ) != UNIVERSE_SIZE:
        raise ProviderBacktestPreflightError("BACKTEST_UNIVERSE_SIZE_CHANGED")
    return tuple(selected)


def build_provider_backtest_preflight(
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    base_path = repository_root / BASE_UNIVERSE_PATH
    expansion_path = repository_root / EXPANSION_UNIVERSE_PATH
    aggregate_path = repository_root / FORMULA_INPUT_AGGREGATE_PATH
    price_manifest_path = repository_root / PRICE_MANIFEST_PATH
    cached_transport_path = repository_root / CACHED_TRANSPORT_AUDIT_PATH
    aggregate = _load_object(aggregate_path)
    price_manifest = _load_object(price_manifest_path)
    cached_transport = _load_object(cached_transport_path)
    aggregate_hash = _verify_artifact(
        aggregate, label="FORMULA_INPUT_AGGREGATE"
    )
    price_manifest_hash = _verify_artifact(
        price_manifest, label="HISTORICAL_PRICE_MANIFEST"
    )
    cached_transport_hash = _verify_artifact(
        cached_transport, label="CACHED_TRANSPORT_AUDIT"
    )
    selected = select_backtest_universe(repository_root=repository_root)
    offline_canary_by_sector: dict[str, str] = {}
    for item in selected:
        offline_canary_by_sector.setdefault(item.sector, item.symbol)
    offline_canary_symbols = tuple(
        offline_canary_by_sector[sector]
        for sector in sorted(offline_canary_by_sector)
    )
    if len(offline_canary_symbols) != 8:
        raise ProviderBacktestPreflightError("PRICE_CANARY_SCOPE_CHANGED")

    securities = [
        {
            "securityId": item.security_id,
            "symbol": item.symbol,
            "role": item.role,
            "sector": item.sector,
            "sourceOrdinal": item.source_ordinal,
            "formulaInput": {
                "state": "REUSE_CONTROLLED_FORMULA_READY_INPUT",
                "contentHash": item.formula_input_content_hash,
                "storageReference": item.formula_input_storage_reference,
                "verificationRequiredBeforeModelRun": True,
            },
            "historicalPrice": {
                "state": item.historical_price_state,
                "provider": "eodhd",
                "coverageWindowState": "PENDING_OFFLINE_PAYLOAD_AUDIT",
                "minimumCompletedSessionsRequired": 1261,
            },
        }
        for item in selected
    ]
    body: dict[str, Any] = {
        "artifactType": "PRACTICAL_LONG_HORIZON_PROVIDER_BACKTEST_PREFLIGHT",
        "schemaVersion": PREFLIGHT_VERSION,
        "contractVersion": CONTRACT_VERSION,
        "status": "READY_FOR_ZERO_NETWORK_CONTROLLED_DATA_AUDIT",
        "claimCeiling": "CURRENT_REVISION_BACKTEST_ONLY",
        "claimLimitations": [
            "Historical provider values may include revisions observed after an anchor.",
            "The current constituent universe creates survivorship bias.",
            "The result cannot be labeled PIT_SUPPORTED or FORWARD_SUPPORTED.",
            (
                "A positive SPY-relative result is directional model evidence, "
                "not proof of future profit."
            ),
        ],
        "selection": {
            "policy": (
                "Retain formula-ready closed-test issuers in frozen role order, "
                "then add formula-ready mature operating companies by deterministic "
                "sector round robin and source ordinal."
            ),
            "issuerCount": UNIVERSE_SIZE,
            "marketBenchmark": MARKET_BENCHMARK,
            "stablePublicIdFormat": "US:{SYMBOL}",
            "retainedIssuerCount": 42,
            "expansionIssuerCount": 58,
            "selectionOutcomeBlind": True,
            "universeContentHash": canonical_hash(
                {
                    "securities": [
                        {
                            "securityId": item.security_id,
                            "symbol": item.symbol,
                            "role": item.role,
                            "sector": item.sector,
                            "sourceOrdinal": item.source_ordinal,
                        }
                        for item in selected
                    ]
                }
            ),
        },
        "sourceArtifacts": {
            "baseUniverse": {
                "path": BASE_UNIVERSE_PATH.as_posix(),
                "fileSha256": file_sha256(base_path),
            },
            "expansionUniverse": {
                "path": EXPANSION_UNIVERSE_PATH.as_posix(),
                "fileSha256": file_sha256(expansion_path),
            },
            "formulaInputAggregate": {
                "path": FORMULA_INPUT_AGGREGATE_PATH.as_posix(),
                "fileSha256": file_sha256(aggregate_path),
                "artifactContentHash": aggregate_hash,
                "formulaReadySecurityCount": 223,
            },
            "historicalPriceManifest": {
                "path": PRICE_MANIFEST_PATH.as_posix(),
                "fileSha256": file_sha256(price_manifest_path),
                "artifactContentHash": price_manifest_hash,
                "completedSecurityCount": 56,
            },
            "cachedTransportAudit": {
                "path": CACHED_TRANSPORT_AUDIT_PATH.as_posix(),
                "fileSha256": file_sha256(cached_transport_path),
                "artifactContentHash": cached_transport_hash,
                "completeFundamentalsEodMarketCapSecurityCount": 216,
            },
        },
        "acquisition": {
            "yahooHistoricalPrice": {
                "endpointContract": "NO_LIVE_ENDPOINT",
                "symbols": [],
                "symbolCount": 0,
                "offlineCanarySymbols": list(offline_canary_symbols),
                "offlineCanaryReadCount": len(offline_canary_symbols),
                "plannedPhysicalWrapperCalls": 0,
                "hardPhysicalWrapperCallCeiling": 0,
                "providerRetryLimit": YAHOO_RETRY_LIMIT,
                "cachedSpyStartDate": PRICE_START_DATE,
                "cachedSpyEndDate": PRICE_END_DATE,
                "decision": (
                    "No issuer price request is required because each selected "
                    "FORMULA_READY payload already contains normalized EODHD daily "
                    "price records. The existing hash-verified Yahoo SPY cache is "
                    "reused only for market-benchmark outcomes."
                ),
            },
            "eodhd": {
                "endpoints": [],
                "symbols": [],
                "plannedPhysicalRequests": 0,
                "plannedConfiguredWeight": 0,
                "provisionalBilledCalls": 0,
                "hardBilledCallCeiling": 0,
                "providerRetryLimit": EODHD_RETRY_LIMIT,
                "dailyAllowance": EODHD_DAILY_ALLOWANCE,
                "minimumUnusedReserve": EODHD_MINIMUM_RESERVE,
                "dashboardBaselineRequired": False,
                "decision": (
                    "No EODHD request is authorized because each selected security "
                    "already has a controlled FORMULA_READY payload. Any missing or "
                    "hash-invalid payload stops this plan and requires a new preflight."
                ),
            },
        },
        "modelInputContract": {
            "formulaInputPayloadCount": UNIVERSE_SIZE,
            "formulaInputPayloadHashVerificationRequired": True,
            "genuinelyMissingSelectedSecurityCount": 0,
            "liveProviderRecoveryRequiredCount": 0,
            "minimumAdjustedCloseSessionsPerIssuer": 1261,
            "historicalPricePayloadCountAfterAcquisition": UNIVERSE_SIZE,
            "issuerHistoricalPriceSource": (
                "CONTROLLED_FORMULA_READY_EODHD_ADJUSTED_CLOSE"
            ),
            "marketBenchmarkPriceSource": (
                "HASH_VERIFIED_YAHOO_TOTAL_RETURN_ADJUSTED_SPY"
            ),
            "spyBenchmarkCacheRequired": True,
            "sectorBenchmark": "DEFERRED_NOT_REQUIRED_FOR_V1",
            "longHorizonCompletedSessionTargets": list(LONG_HORIZON_SESSIONS),
            "transactionCostsRequired": True,
            "missingDataRemainsExplicit": True,
            "aiAffectsDeterministicScore": False,
        },
        "executionSafety": {
            "crossProcessLeaseRequired": True,
            "uniqueRunIdRequired": True,
            "immutableRequestJournalRequired": True,
            "contentAddressedControlledStorageRequired": True,
            "gitSafeArtifactsMayContainProviderValues": False,
            "unknownRequestStateStopsRun": True,
            "partialFailureMayResumeOnlyFromHashVerifiedCompletedReceipts": True,
            "networkExecutionAuthorizedByThisArtifact": False,
            "zeroNetworkControlledDataAuditAuthorized": False,
        },
        "automaticStopRules": [
            "SOURCE_ARTIFACT_HASH_CHANGED",
            "UNIVERSE_CONTENT_HASH_CHANGED",
            "CONTROLLED_FORMULA_INPUT_MISSING",
            "CONTROLLED_FORMULA_INPUT_HASH_MISMATCH",
            "SPY_BENCHMARK_PRICE_MISSING",
            "INSUFFICIENT_ADJUSTED_CLOSE_HISTORY",
            "INSUFFICIENT_FINANCIAL_HISTORY",
            "INSUFFICIENT_HISTORICAL_MARKET_CAP_HISTORY",
            "REQUEST_JOURNAL_OR_LEASE_INCONSISTENT",
            "UNKNOWN_PHYSICAL_REQUEST_STATE",
            "LICENSED_VALUE_FOUND_IN_GIT_SAFE_ARTIFACT",
        ],
        "securities": securities,
        "networkRequestsExecuted": False,
        "providerValuesIncluded": False,
        "scoresOrRanksIncluded": False,
        "forwardValidationExecuted": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_preflight(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing != serialized:
            raise ProviderBacktestPreflightError(
                f"IMMUTABLE_PREFLIGHT_CONFLICT[{path}]"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")
