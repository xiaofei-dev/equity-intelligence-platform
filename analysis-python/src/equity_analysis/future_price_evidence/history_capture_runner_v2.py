from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.request import Request, urlopen
from uuid import uuid4

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.daily_refresh.universe import (
    DEFAULT_UNIVERSE_PATH,
    load_closed_test_universe,
)
from equity_analysis.future_price_evidence.contracts_v1 import (
    NETWORK_CONFIRMATION,
    CalendarAuthority,
    DualAuthorityCompletedSessionEvidence,
    FuturePriceEvidenceError,
    NormalizedFuturePriceEvidence,
    RawHttpTransportCapture,
    build_calendar_review,
    build_dual_authority_evidence,
    capture_raw_http_response,
    git_safe_receipt,
    normalize_yahoo_chart_capture,
)
from equity_analysis.future_price_evidence.history_coverage_v2 import (
    MOMENTUM_12_1_REQUIRED_SESSIONS,
    FuturePriceHistoryCoverageV2,
    assess_future_price_history_coverage_v2,
)
from equity_analysis.future_price_evidence.history_preflight_v2 import (
    DEFAULT_HISTORY_PREFLIGHT_OUTPUT,
    EXPECTED_PRICE_SYMBOLS,
    EXPECTED_TOTAL_HTTP_ATTEMPTS,
    FuturePriceHistoryPlanV2,
    build_future_price_history_plan_v2,
)
from equity_analysis.future_price_evidence.persistence_adapter_v1 import (
    FuturePriceEvidencePersistenceAdapter,
    FuturePriceEvidencePersistenceReceipt,
    FuturePriceEvidencePersistenceRequest,
)
from equity_analysis.future_price_evidence.preflight_v1 import RequestSpec
from equity_analysis.provider_validation.execution_safety import (
    ExecutionLease,
    JournaledOpener,
    PhysicalRequestJournal,
)

FUTURE_PRICE_HISTORY_CAPTURE_VERSION = "FUTURE-PRICE-HISTORY-CAPTURE-v2.0.0"
FUTURE_PRICE_HISTORY_CONTROLLED_VERSION = (
    "FUTURE-PRICE-HISTORY-CONTROLLED-EVIDENCE-v2.0.0"
)
LIVE_CONFIRMATION = NETWORK_CONFIRMATION
DATABASE_CONFIRMATION = "I_CONFIRM_FUTURE_PRICE_HISTORY_DATABASE_WRITE"
DEFAULT_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_STORAGE_ROOT = (
    DEFAULT_REPOSITORY_ROOT / "storage/future-price-history-capture-v2"
)
DEFAULT_REPORT_ROOT = DEFAULT_REPOSITORY_ROOT / "docs/generated"
DEFAULT_LEASE_PATH = DEFAULT_STORAGE_ROOT / ".future-price-history-v2.lock"


class FuturePriceHistoryCaptureError(RuntimeError):
    pass


class HistoryPersistenceRequestFactory(Protocol):
    def __call__(
        self,
        *,
        evidence: NormalizedFuturePriceEvidence,
        calendar_evidence: DualAuthorityCompletedSessionEvidence,
        plan: FuturePriceHistoryPlanV2,
        run_id: str,
    ) -> FuturePriceEvidencePersistenceRequest: ...


@dataclass(frozen=True)
class AdapterPersistenceGateway:
    """Explicit bridge to the existing per-security atomic persistence adapter."""

    adapter: FuturePriceEvidencePersistenceAdapter
    request_factory: HistoryPersistenceRequestFactory

    def persist(
        self,
        *,
        evidences: tuple[NormalizedFuturePriceEvidence, ...],
        calendar_evidence: DualAuthorityCompletedSessionEvidence,
        plan: FuturePriceHistoryPlanV2,
        run_id: str,
    ) -> tuple[FuturePriceEvidencePersistenceReceipt, ...]:
        return tuple(
            self.adapter.persist(
                self.request_factory(
                    evidence=evidence,
                    calendar_evidence=calendar_evidence,
                    plan=plan,
                    run_id=run_id,
                )
            )
            for evidence in evidences
        )


@dataclass(frozen=True)
class CalendarReviewConfirmation:
    reviewed_by: str
    nyse_confirms_scheduled_session: bool
    nyse_confirms_close: bool
    nasdaq_confirms_scheduled_session: bool
    nasdaq_confirms_close: bool

    def __post_init__(self) -> None:
        if not self.reviewed_by.strip():
            raise ValueError("A named calendar reviewer is required")


@dataclass(frozen=True)
class FuturePriceHistoryCaptureResult:
    run_id: str
    target_session: date
    state: str
    plan_hash: str
    calendar_evidence_hash: str
    symbol_count: int
    ready_symbol_count: int
    physical_attempts: int
    configured_weight: int
    report_path: Path
    report_sha256: str
    report_content_hash: str
    controlled_manifest_path: Path
    controlled_manifest_sha256: str
    controlled_manifest_content_hash: str
    checkpoint_path: Path
    database_receipt_count: int


def load_verified_history_preflight_v2(
    path: Path = DEFAULT_HISTORY_PREFLIGHT_OUTPUT,
) -> tuple[dict[str, Any], FuturePriceHistoryPlanV2]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    claim = artifact.get("artifactContentHash")
    actual = canonical_hash(
        {key: value for key, value in artifact.items() if key != "artifactContentHash"}
    )
    if claim != actual:
        raise FuturePriceHistoryCaptureError("HISTORY_PREFLIGHT_CONTENT_HASH_MISMATCH")
    if artifact.get("status") != (
        "BLOCKED_AWAITING_TARGET_SESSION_COMPLETION_AND_LIVE_APPROVAL"
    ):
        raise FuturePriceHistoryCaptureError("HISTORY_PREFLIGHT_STATUS_CHANGED")
    universe = load_closed_test_universe(DEFAULT_UNIVERSE_PATH)
    plan = build_future_price_history_plan_v2(
        base_symbols=universe.refreshable_symbols,
        target_session=date.fromisoformat(str(artifact["targetSession"])),
        universe_version=str(artifact["universeVersion"]),
        universe_file_sha256=str(artifact["universeFileSha256"]),
    )
    expected = {
        "planHash": plan.plan_hash,
        "preregistrationSealHash": plan.preregistration_seal_hash,
        "externalReferenceUniverseHash": plan.external_reference_universe_hash,
        "externalReferenceRowsHash": plan.external_reference_rows_hash,
        "orderedSymbolsHash": plan.ordered_symbols_hash,
        "symbolPlanHash": plan.symbol_plan_hash,
        "orderedSymbols": list(plan.ordered_symbols),
        "priceSymbolCount": EXPECTED_PRICE_SYMBOLS,
        "expectedPhysicalHttpAttempts": EXPECTED_TOTAL_HTTP_ATTEMPTS,
        "physicalHttpAttemptHardCeiling": EXPECTED_TOTAL_HTTP_ATTEMPTS,
        "configuredWeightHardCeiling": EXPECTED_TOTAL_HTTP_ATTEMPTS,
        "providerRetryLimit": 0,
        "historyWindowCalendarDays": 420,
        "minimumParsedCompletedSessionsPerSymbol": (
            MOMENTUM_12_1_REQUIRED_SESSIONS
        ),
    }
    for key, value in expected.items():
        if artifact.get(key) != value:
            raise FuturePriceHistoryCaptureError(f"HISTORY_PREFLIGHT_BINDING_CHANGED[{key}]")
    endpoint_counts = artifact.get("endpointCounts")
    if endpoint_counts != {
        "OFFICIAL_NASDAQ_CALENDAR": 1,
        "OFFICIAL_NYSE_CALENDAR": 1,
        "YAHOO_CHART_JSON": EXPECTED_PRICE_SYMBOLS,
    }:
        raise FuturePriceHistoryCaptureError("HISTORY_PREFLIGHT_ENDPOINT_COUNTS_CHANGED")
    if len(plan.requests) != EXPECTED_TOTAL_HTTP_ATTEMPTS:
        raise FuturePriceHistoryCaptureError("HISTORY_CAPTURE_REQUEST_COUNT_NOT_69")
    return artifact, plan


def assert_history_capture_authorized(
    *,
    plan: FuturePriceHistoryPlanV2,
    as_of: datetime,
    network_enabled: bool,
    live_confirmation: str | None,
    calendar: UnitedStatesMarketCalendar | None = None,
) -> None:
    if not network_enabled or live_confirmation != LIVE_CONFIRMATION:
        raise FuturePriceHistoryCaptureError("NETWORK_EXECUTION_NOT_EXPLICITLY_AUTHORIZED")
    market_calendar = calendar or UnitedStatesMarketCalendar()
    if market_calendar.latest_completed_session(as_of) < plan.target_session:
        raise FuturePriceHistoryCaptureError("TARGET_SESSION_NOT_COMPLETED")


def build_ready_for_execution_status(
    *,
    preflight_path: Path = DEFAULT_HISTORY_PREFLIGHT_OUTPUT,
    as_of: datetime,
    calendar: UnitedStatesMarketCalendar | None = None,
) -> dict[str, Any]:
    artifact, plan = load_verified_history_preflight_v2(preflight_path)
    latest = (calendar or UnitedStatesMarketCalendar()).latest_completed_session(as_of)
    body = {
        "artifactType": "FUTURE_PRICE_HISTORY_CAPTURE_EXECUTION_STATUS",
        "schemaVersion": FUTURE_PRICE_HISTORY_CAPTURE_VERSION,
        "status": (
            "READY_FOR_COMPLETED_SESSION_EXECUTION"
            if latest >= plan.target_session
            else "BLOCKED_AWAITING_TARGET_SESSION_COMPLETION"
        ),
        "targetSession": plan.target_session.isoformat(),
        "latestCompletedSession": latest.isoformat(),
        "preflightArtifactContentHash": artifact["artifactContentHash"],
        "planHash": plan.plan_hash,
        "symbolPlanHash": plan.symbol_plan_hash,
        "priceSymbolCount": len(plan.ordered_symbols),
        "officialCalendarRequestCount": 2,
        "yahooChartRequestCount": len(plan.ordered_symbols),
        "physicalHttpAttemptHardCeiling": len(plan.requests),
        "configuredWeightHardCeiling": sum(
            item.configured_weight for item in plan.requests
        ),
        "providerRetryLimit": 0,
        "networkRequestsExecuted": 0,
        "databaseWritesExecuted": 0,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


class FuturePriceHistoryCaptureRunnerV2:
    def __init__(
        self,
        *,
        preflight_path: Path = DEFAULT_HISTORY_PREFLIGHT_OUTPUT,
        storage_root: Path = DEFAULT_STORAGE_ROOT,
        report_root: Path = DEFAULT_REPORT_ROOT,
        lease_path: Path = DEFAULT_LEASE_PATH,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        market_calendar: UnitedStatesMarketCalendar | None = None,
    ) -> None:
        self._preflight_path = preflight_path
        self._storage_root = storage_root
        self._report_root = report_root
        self._lease_path = lease_path
        self._opener = opener
        self._clock = clock
        self._market_calendar = market_calendar or UnitedStatesMarketCalendar()

    def execute(
        self,
        *,
        review: CalendarReviewConfirmation,
        network_enabled: bool,
        live_confirmation: str | None,
        database_write_enabled: bool = False,
        database_confirmation: str | None = None,
        persistence_gateway: AdapterPersistenceGateway | None = None,
        run_id: str | None = None,
        resume: bool = False,
    ) -> FuturePriceHistoryCaptureResult:
        preflight, plan = load_verified_history_preflight_v2(self._preflight_path)
        now = self._clock()
        assert_history_capture_authorized(
            plan=plan,
            as_of=now,
            network_enabled=network_enabled,
            live_confirmation=live_confirmation,
            calendar=self._market_calendar,
        )
        if database_write_enabled and (
            database_confirmation != DATABASE_CONFIRMATION
            or persistence_gateway is None
        ):
            raise FuturePriceHistoryCaptureError(
                "DATABASE_WRITE_NOT_EXPLICITLY_AUTHORIZED"
            )
        actual_run_id = run_id or _new_run_id(now)
        run_root = self._storage_root / "runs" / actual_run_id
        if run_root.exists() and not resume:
            raise FuturePriceHistoryCaptureError("RUN_ALREADY_EXISTS_EXPLICIT_RESUME_REQUIRED")
        journal = PhysicalRequestJournal(self._storage_root / "journals", actual_run_id)
        preflight_detail = {
            "sliceId": plan.plan_hash,
            "symbols": list(plan.ordered_symbols),
            "targetSession": plan.target_session.isoformat(),
            "preflightArtifactContentHash": preflight["artifactContentHash"],
            "physicalHttpAttemptHardCeiling": len(plan.requests),
            "configuredWeightHardCeiling": sum(
                item.configured_weight for item in plan.requests
            ),
            "providerRetryLimit": 0,
        }
        if resume:
            journal.resume_preflight(preflight_detail)
            completed = self._load_completed_result(
                run_id=actual_run_id,
                run_root=run_root,
                plan=plan,
            )
            if completed is not None:
                return completed
        else:
            journal.preflight(preflight_detail)
        request_by_url = {item.url: item for item in plan.requests}

        def classify(request: Request) -> tuple[str, str, str, int]:
            spec = request_by_url.get(request.full_url)
            if spec is None:
                raise FuturePriceHistoryCaptureError("UNPLANNED_REQUEST_URL")
            return (
                spec.symbol,
                spec.endpoint_category,
                spec.request_identity,
                spec.configured_weight,
            )

        opened = JournaledOpener(
            self._opener,
            journal,
            request_classifier=classify,
            physical_attempt_ceiling=len(plan.requests),
            configured_weight_ceiling=sum(
                item.configured_weight for item in plan.requests
            ),
        )
        lease = ExecutionLease(self._lease_path, actual_run_id)
        try:
            with lease:
                captures = self._capture_requests(
                    requests=plan.requests[:2],
                    run_root=run_root,
                    opened=opened,
                )
                calendar_evidence = self._calendar_evidence(
                    plan=plan,
                    captures=captures,
                    review=review,
                )
                captures.update(
                    self._capture_requests(
                        requests=plan.requests[2:],
                        run_root=run_root,
                        opened=opened,
                    )
                )
                if len(captures) != EXPECTED_TOTAL_HTTP_ATTEMPTS:
                    raise FuturePriceHistoryCaptureError("CAPTURE_COUNT_NOT_69")
                evidences, coverage = self._normalize_all(
                    plan=plan,
                    run_root=run_root,
                    captures=captures,
                    calendar_evidence=calendar_evidence,
                )
                not_ready = tuple(
                    item.symbol
                    for item in coverage
                    if not item.all_requirements_ready
                )
                if not_ready:
                    raise FuturePriceHistoryCaptureError(
                        "PARSED_COMPLETED_SESSIONS_BELOW_253["
                        + ",".join(not_ready)
                        + "]"
                    )
                manifest_path, manifest_sha, manifest_hash = (
                    self._write_controlled_manifest(
                        run_root=run_root,
                        plan=plan,
                        calendar_evidence=calendar_evidence,
                        evidences=evidences,
                        coverage=coverage,
                    )
                )
                receipts: tuple[FuturePriceEvidencePersistenceReceipt, ...] = ()
                if database_write_enabled:
                    if persistence_gateway is None:
                        raise AssertionError("Database gateway was checked above")
                    receipts = persistence_gateway.persist(
                        evidences=evidences,
                        calendar_evidence=calendar_evidence,
                        plan=plan,
                        run_id=actual_run_id,
                    )
                    if len(receipts) != len(evidences):
                        raise FuturePriceHistoryCaptureError(
                            "DATABASE_PERSISTENCE_RECEIPT_COUNT_MISMATCH"
                        )
                checkpoint = self._write_checkpoint(
                    run_root=run_root,
                    run_id=actual_run_id,
                    plan=plan,
                    calendar_evidence=calendar_evidence,
                    manifest_hash=manifest_hash,
                    database_receipts=receipts,
                )
                report_path, report_sha, report_hash = self._write_report(
                    run_id=actual_run_id,
                    plan=plan,
                    preflight=preflight,
                    calendar_evidence=calendar_evidence,
                    captures=captures,
                    evidences=evidences,
                    coverage=coverage,
                    manifest_path=manifest_path,
                    manifest_sha=manifest_sha,
                    manifest_hash=manifest_hash,
                    checkpoint=checkpoint,
                    physical_attempts=opened.physical_attempts,
                    configured_weight=opened.configured_weight,
                    endpoint_counts=opened.physical_attempts_by_endpoint,
                    database_receipts=receipts,
                )
                journal.finalize(
                    "COMPLETE",
                    {
                        "status": "READY",
                        "reportSha256": report_sha,
                        "manifestSha256": manifest_sha,
                        "checkpointSha256": _file_sha256(checkpoint),
                        "physicalAttempts": opened.physical_attempts,
                        "configuredWeight": opened.configured_weight,
                    },
                )
        except Exception as error:
            try:
                journal.finalize(
                    "ABORTED",
                    {
                        "status": "STOPPED",
                        "sanitizedReason": _sanitized_error(error),
                        "physicalAttempts": opened.physical_attempts,
                        "configuredWeight": opened.configured_weight,
                    },
                )
            except (OSError, RuntimeError, ValueError):
                pass
            raise
        return FuturePriceHistoryCaptureResult(
            run_id=actual_run_id,
            target_session=plan.target_session,
            state="READY",
            plan_hash=plan.plan_hash,
            calendar_evidence_hash=calendar_evidence.evidence_hash,
            symbol_count=len(evidences),
            ready_symbol_count=len(coverage),
            physical_attempts=opened.physical_attempts,
            configured_weight=opened.configured_weight,
            report_path=report_path,
            report_sha256=report_sha,
            report_content_hash=report_hash,
            controlled_manifest_path=manifest_path,
            controlled_manifest_sha256=manifest_sha,
            controlled_manifest_content_hash=manifest_hash,
            checkpoint_path=checkpoint,
            database_receipt_count=len(receipts),
        )

    def _load_completed_result(
        self,
        *,
        run_id: str,
        run_root: Path,
        plan: FuturePriceHistoryPlanV2,
    ) -> FuturePriceHistoryCaptureResult | None:
        checkpoint = run_root / "checkpoint.json"
        report_path = self._report_root / f"future-price-history-capture-{run_id}.json"
        manifest_path = run_root / "controlled-manifest.json"
        existing = (checkpoint.exists(), report_path.exists(), manifest_path.exists())
        if not any(existing):
            return None
        if not all(existing):
            raise FuturePriceHistoryCaptureError("COMPLETED_RUN_ARTIFACT_SET_INCOMPLETE")
        checkpoint_payload = _verified_artifact(checkpoint)
        report = _verified_artifact(report_path)
        manifest = _verified_artifact(manifest_path)
        if (
            checkpoint_payload.get("state") != "COMPLETE"
            or checkpoint_payload.get("planHash") != plan.plan_hash
            or report.get("status") != "READY"
            or report.get("planHash") != plan.plan_hash
            or manifest.get("planHash") != plan.plan_hash
        ):
            raise FuturePriceHistoryCaptureError("COMPLETED_RUN_ARTIFACT_BINDING_INVALID")
        return FuturePriceHistoryCaptureResult(
            run_id=run_id,
            target_session=plan.target_session,
            state="READY",
            plan_hash=plan.plan_hash,
            calendar_evidence_hash=str(report["calendarEvidenceHash"]),
            symbol_count=int(report["priceSymbolCount"]),
            ready_symbol_count=int(report["readySymbolCount"]),
            physical_attempts=0,
            configured_weight=0,
            report_path=report_path,
            report_sha256=_file_sha256(report_path),
            report_content_hash=str(report["artifactContentHash"]),
            controlled_manifest_path=manifest_path,
            controlled_manifest_sha256=_file_sha256(manifest_path),
            controlled_manifest_content_hash=str(manifest["artifactContentHash"]),
            checkpoint_path=checkpoint,
            database_receipt_count=int(report["databaseWritesExecuted"]),
        )

    def _capture_requests(
        self,
        *,
        requests: tuple[RequestSpec, ...],
        run_root: Path,
        opened: JournaledOpener,
    ) -> dict[str, RawHttpTransportCapture]:
        captures: dict[str, RawHttpTransportCapture] = {}
        for spec in requests:
            request = Request(
                spec.url,
                method=spec.method,
                headers={
                    "Accept": (
                        "application/json"
                        if spec.endpoint_category == "YAHOO_CHART_JSON"
                        else "text/html,application/xhtml+xml"
                    ),
                    "Accept-Encoding": "identity",
                    "User-Agent": "equity-intelligence-platform/1.0",
                },
            )
            with opened(request, timeout=30) as response:
                body = response.read()
                status = int(getattr(response, "status", 200))
                headers = {
                    str(key): str(value)
                    for key, value in getattr(response, "headers", {}).items()
                }
            if status != 200:
                raise FuturePriceHistoryCaptureError(
                    f"HTTP_STATUS_NOT_200[{spec.endpoint_category}:{status}]"
                )
            captured = capture_raw_http_response(
                storage_root=run_root,
                request_identity=spec.request_identity,
                endpoint_category=spec.endpoint_category,
                requested_url=spec.url,
                final_url=spec.url,
                http_status=status,
                headers=headers,
                body=body,
                captured_at=self._clock(),
            )
            captures[spec.request_identity] = captured
        return captures

    def _calendar_evidence(
        self,
        *,
        plan: FuturePriceHistoryPlanV2,
        captures: dict[str, RawHttpTransportCapture],
        review: CalendarReviewConfirmation,
    ) -> DualAuthorityCompletedSessionEvidence:
        rows = {}
        reviewed_at = self._clock()
        mapping = (
            (
                CalendarAuthority.NYSE,
                "official-calendar-nyse-history-v2",
                review.nyse_confirms_scheduled_session,
                review.nyse_confirms_close,
            ),
            (
                CalendarAuthority.NASDAQ,
                "official-calendar-nasdaq-history-v2",
                review.nasdaq_confirms_scheduled_session,
                review.nasdaq_confirms_close,
            ),
        )
        for authority, identity, confirms_session, confirms_close in mapping:
            capture = captures[identity]
            rows[authority] = build_calendar_review(
                authority=authority,
                target_session=plan.target_session,
                official_source_url=capture.final_url,
                raw_body_sha256=capture.response_body_sha256,
                raw_body_storage_reference=capture.response_body_storage_reference,
                retrieved_at=capture.captured_at,
                reviewed_at=reviewed_at,
                reviewed_by=review.reviewed_by,
                confirms_scheduled_session=confirms_session,
                confirms_regular_or_published_early_close=confirms_close,
            )
        return build_dual_authority_evidence(
            target_session=plan.target_session,
            completed_session_cutoff=max(reviewed_at, self._clock()),
            nyse=rows[CalendarAuthority.NYSE],
            nasdaq=rows[CalendarAuthority.NASDAQ],
        )

    @staticmethod
    def _normalize_all(
        *,
        plan: FuturePriceHistoryPlanV2,
        run_root: Path,
        captures: dict[str, RawHttpTransportCapture],
        calendar_evidence: DualAuthorityCompletedSessionEvidence,
    ) -> tuple[
        tuple[NormalizedFuturePriceEvidence, ...],
        tuple[FuturePriceHistoryCoverageV2, ...],
    ]:
        evidences = []
        coverage = []
        for symbol in plan.ordered_symbols:
            identity = (
                f"yahoo-chart-history-v2-{symbol}-{plan.target_session.isoformat()}"
            )
            evidence = normalize_yahoo_chart_capture(
                storage_root=run_root,
                symbol=symbol,
                target_session=plan.target_session,
                raw_capture=captures[identity],
                calendar_evidence=calendar_evidence,
            )
            evidences.append(evidence)
            coverage.append(assess_future_price_history_coverage_v2(evidence))
        return tuple(evidences), tuple(coverage)

    def _write_controlled_manifest(
        self,
        *,
        run_root: Path,
        plan: FuturePriceHistoryPlanV2,
        calendar_evidence: DualAuthorityCompletedSessionEvidence,
        evidences: tuple[NormalizedFuturePriceEvidence, ...],
        coverage: tuple[FuturePriceHistoryCoverageV2, ...],
    ) -> tuple[Path, str, str]:
        rows = []
        evidence_root = run_root / "normalized-evidence"
        for evidence, item in zip(evidences, coverage, strict=True):
            payload = _controlled_payload(evidence, item)
            content_hash = canonical_hash(payload)
            encoded = _encoded_json({**payload, "artifactContentHash": content_hash})
            path_token = content_hash.removeprefix("sha256:").upper()
            path = evidence_root / path_token[:2] / f"{path_token}.json"
            _write_immutable(path, encoded, "CONTROLLED_EVIDENCE_CONFLICT")
            rows.append(
                {
                    "symbol": evidence.symbol,
                    "evidenceHash": evidence.evidence_hash,
                    "coverageHash": item.coverage_hash,
                    "controlledArtifactContentHash": content_hash,
                    "controlledArtifactFileSha256": hashlib.sha256(encoded).hexdigest().upper(),
                    "controlledStorageReference": path.relative_to(
                        self._storage_root
                    ).as_posix(),
                    "observedSessionCount": item.observed_sessions,
                    "coverageState": (
                        "READY" if item.all_requirements_ready else "INSUFFICIENT_HISTORY"
                    ),
                }
            )
        body = {
            "artifactType": "FUTURE_PRICE_HISTORY_CONTROLLED_MANIFEST",
            "schemaVersion": FUTURE_PRICE_HISTORY_CONTROLLED_VERSION,
            "planHash": plan.plan_hash,
            "symbolPlanHash": plan.symbol_plan_hash,
            "targetSession": plan.target_session.isoformat(),
            "calendarEvidenceHash": calendar_evidence.evidence_hash,
            "symbolCount": len(rows),
            "rows": rows,
            "rawProviderValuesIncluded": False,
            "scoresOrRanksIncluded": False,
        }
        content_hash = canonical_hash(body)
        encoded = _encoded_json({**body, "artifactContentHash": content_hash})
        path = run_root / "controlled-manifest.json"
        _write_immutable(path, encoded, "CONTROLLED_MANIFEST_CONFLICT")
        return path, hashlib.sha256(encoded).hexdigest().upper(), content_hash

    @staticmethod
    def _write_checkpoint(
        *,
        run_root: Path,
        run_id: str,
        plan: FuturePriceHistoryPlanV2,
        calendar_evidence: DualAuthorityCompletedSessionEvidence,
        manifest_hash: str,
        database_receipts: tuple[FuturePriceEvidencePersistenceReceipt, ...],
    ) -> Path:
        body = {
            "artifactType": "FUTURE_PRICE_HISTORY_CAPTURE_CHECKPOINT",
            "schemaVersion": FUTURE_PRICE_HISTORY_CAPTURE_VERSION,
            "runId": run_id,
            "state": "COMPLETE",
            "planHash": plan.plan_hash,
            "symbolPlanHash": plan.symbol_plan_hash,
            "calendarEvidenceHash": calendar_evidence.evidence_hash,
            "controlledManifestContentHash": manifest_hash,
            "databaseReceiptCount": len(database_receipts),
            "databaseReceiptHashes": [
                item.checkpoint_hash for item in database_receipts
            ],
        }
        encoded = _encoded_json({**body, "artifactContentHash": canonical_hash(body)})
        path = run_root / "checkpoint.json"
        _write_immutable(path, encoded, "CAPTURE_CHECKPOINT_CONFLICT")
        return path

    def _write_report(
        self,
        *,
        run_id: str,
        plan: FuturePriceHistoryPlanV2,
        preflight: dict[str, Any],
        calendar_evidence: DualAuthorityCompletedSessionEvidence,
        captures: dict[str, RawHttpTransportCapture],
        evidences: tuple[NormalizedFuturePriceEvidence, ...],
        coverage: tuple[FuturePriceHistoryCoverageV2, ...],
        manifest_path: Path,
        manifest_sha: str,
        manifest_hash: str,
        checkpoint: Path,
        physical_attempts: int,
        configured_weight: int,
        endpoint_counts: dict[str, int],
        database_receipts: tuple[FuturePriceEvidencePersistenceReceipt, ...],
    ) -> tuple[Path, str, str]:
        body = {
            "artifactType": "FUTURE_COMPLETED_SESSION_PRICE_HISTORY_CAPTURE",
            "schemaVersion": FUTURE_PRICE_HISTORY_CAPTURE_VERSION,
            "runId": run_id,
            "status": "READY",
            "targetSession": plan.target_session.isoformat(),
            "preflightArtifactContentHash": preflight["artifactContentHash"],
            "planHash": plan.plan_hash,
            "symbolPlanHash": plan.symbol_plan_hash,
            "preregistrationSealHash": plan.preregistration_seal_hash,
            "externalReferenceUniverseHash": plan.external_reference_universe_hash,
            "calendarEvidenceHash": calendar_evidence.evidence_hash,
            "priceSymbolCount": len(evidences),
            "readySymbolCount": sum(
                item.all_requirements_ready for item in coverage
            ),
            "minimumParsedCompletedSessionsPerSymbol": (
                MOMENTUM_12_1_REQUIRED_SESSIONS
            ),
            "physicalHttpAttempts": physical_attempts,
            "physicalHttpAttemptHardCeiling": EXPECTED_TOTAL_HTTP_ATTEMPTS,
            "configuredWeight": configured_weight,
            "configuredWeightHardCeiling": EXPECTED_TOTAL_HTTP_ATTEMPTS,
            "providerRetryLimit": 0,
            "physicalAttemptsByEndpoint": endpoint_counts,
            "rawCaptureCount": len(captures),
            "rawBodyHashes": sorted(
                item.response_body_sha256 for item in captures.values()
            ),
            "rawEnvelopeHashes": sorted(
                item.response_envelope_hash for item in captures.values()
            ),
            "symbols": [
                {
                    **git_safe_receipt(evidence),
                    "historyCoverageHash": item.coverage_hash,
                    "observedCompletedSessionCount": item.observed_sessions,
                    "historyCoverageState": (
                        "READY" if item.all_requirements_ready else "INSUFFICIENT_HISTORY"
                    ),
                }
                for evidence, item in zip(evidences, coverage, strict=True)
            ],
            "controlledManifestPath": manifest_path.relative_to(
                DEFAULT_REPOSITORY_ROOT
            ).as_posix()
            if manifest_path.is_relative_to(DEFAULT_REPOSITORY_ROOT)
            else manifest_path.as_posix(),
            "controlledManifestFileSha256": manifest_sha,
            "controlledManifestContentHash": manifest_hash,
            "checkpointFileSha256": _file_sha256(checkpoint),
            "databaseWritesExecuted": len(database_receipts),
            "rawProviderValuesIncluded": False,
            "scoresOrRanksIncluded": False,
        }
        content_hash = canonical_hash(body)
        encoded = _encoded_json({**body, "artifactContentHash": content_hash})
        path = self._report_root / f"future-price-history-capture-{run_id}.json"
        _write_immutable(path, encoded, "HISTORY_CAPTURE_REPORT_CONFLICT")
        return path, hashlib.sha256(encoded).hexdigest().upper(), content_hash


def _controlled_payload(
    evidence: NormalizedFuturePriceEvidence,
    coverage: FuturePriceHistoryCoverageV2,
) -> dict[str, Any]:
    return {
        "artifactType": "FUTURE_PRICE_HISTORY_CONTROLLED_EVIDENCE",
        "schemaVersion": FUTURE_PRICE_HISTORY_CONTROLLED_VERSION,
        "symbol": evidence.symbol,
        "targetSession": evidence.target_session.isoformat(),
        "provider": evidence.provider,
        "providerSchemaVersion": evidence.provider_schema_version,
        "normalizationVersion": evidence.normalization_version,
        "rawTransportBodyHash": evidence.raw_transport.response_body_sha256,
        "rawTransportEnvelopeHash": evidence.raw_transport.response_envelope_hash,
        "calendarEvidenceHash": evidence.calendar_evidence_hash,
        "actionBinding": {
            "bindingHash": evidence.action_binding.binding_hash,
            "rawBarSetHash": evidence.action_binding.raw_bar_set_hash,
            "selectedActionSetHash": evidence.action_binding.selected_action_set_hash,
            "adjustedBarSetHash": evidence.action_binding.adjusted_bar_set_hash,
            "adjustmentMode": evidence.action_binding.adjustment_mode,
            "adjustmentPolicyVersion": (
                evidence.action_binding.adjustment_policy_version
            ),
            "providerRevisionKey": evidence.action_binding.provider_revision_key,
            "sourceRevisionStatus": evidence.action_binding.source_revision_status,
        },
        "bars": [
            {
                "tradingDate": item.trading_date.isoformat(),
                "open": str(item.open_price),
                "high": str(item.high_price),
                "low": str(item.low_price),
                "close": str(item.close_price),
                "adjustedClose": str(item.adjusted_close),
                "volume": item.volume,
            }
            for item in evidence.bars
        ],
        "adtv": {
            "metricName": evidence.adtv.metric_name,
            "metricVersion": evidence.adtv.metric_version,
            "observationDate": evidence.adtv.observation_date.isoformat(),
            "completedSessionCount": evidence.adtv.completed_session_count,
            "currency": evidence.adtv.currency,
            "numericValue": str(evidence.adtv.numeric_value),
            "priceVolumeInputHash": evidence.adtv.price_volume_input_hash,
            "availableAt": evidence.adtv.available_at.isoformat(),
            "ingestedAt": evidence.adtv.ingested_at.isoformat(),
            "status": evidence.adtv.status,
            "observationHash": evidence.adtv.observation_hash,
        },
        "coverage": {
            "coverageHash": coverage.coverage_hash,
            "observedFirstSession": coverage.observed_first_session.isoformat(),
            "observedLastSession": coverage.observed_last_session.isoformat(),
            "observedSessions": coverage.observed_sessions,
            "requirements": [
                {
                    "requirement": item.requirement,
                    "requiredSessions": item.required_sessions,
                    "observedSessions": item.observed_sessions,
                    "state": item.state.value,
                }
                for item in coverage.requirements
            ],
            "momentumStartSession": (
                coverage.momentum_start_session.isoformat()
                if coverage.momentum_start_session
                else None
            ),
            "momentumEndSession": (
                coverage.momentum_end_session.isoformat()
                if coverage.momentum_end_session
                else None
            ),
        },
        "availableAt": evidence.available_at.isoformat(),
        "ingestedAt": evidence.ingested_at.isoformat(),
        "evidenceHash": evidence.evidence_hash,
    }


def _new_run_id(now: datetime) -> str:
    return f"{now.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:12]}"


def _encoded_json(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _write_immutable(path: Path, content: bytes, conflict_code: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise FuturePriceHistoryCaptureError(conflict_code)
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _verified_artifact(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    claim = payload.get("artifactContentHash")
    actual = canonical_hash(
        {key: value for key, value in payload.items() if key != "artifactContentHash"}
    )
    if claim != actual:
        raise FuturePriceHistoryCaptureError(
            f"IMMUTABLE_ARTIFACT_CONTENT_HASH_MISMATCH[{path.name}]"
        )
    return payload


def _sanitized_error(error: Exception) -> str:
    if isinstance(error, FuturePriceEvidenceError | FuturePriceHistoryCaptureError):
        return str(error)[:500]
    return type(error).__name__.upper()
