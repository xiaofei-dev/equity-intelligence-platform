from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from equity_analysis.daily_refresh.models import Dataset, RefreshPlan
from equity_analysis.evidence_foundation.contracts_v1 import (
    CompletedSession,
    SecurityIdentity,
    UnifiedEvidenceContractViolation,
)
from equity_analysis.evidence_foundation.domain_contracts_v1 import (
    EvidenceDomain,
)
from equity_analysis.evidence_foundation.persistence_v1 import (
    PersistedEvidenceEnvelope,
)
from equity_analysis.evidence_foundation.provider_adapter_v1 import (
    ProviderEvidenceAdapterV1,
    ProviderEvidenceRequestV1,
    provider_request_identity_payload_v1,
)
from equity_analysis.provider_validation.execution_safety import (
    ExecutionLease,
    PhysicalRequestJournal,
    SymbolExecutionJournal,
)

EVIDENCE_REFRESH_PLAN_VERSION = "provider-neutral-evidence-refresh-plan-v1.0.0"


class EvidenceRefreshItemStatus(StrEnum):
    PERSISTED = "PERSISTED"
    REPLAYED = "REPLAYED"
    FAILED = "FAILED"


class EvidenceRefreshOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ProviderAdapterFailure(RuntimeError):
    """Sanitized adapter failure that may be retried by a later resume."""

    def __init__(self, code: str) -> None:
        if not code or not code.replace("_", "").isalnum():
            raise ValueError("Provider adapter failure code is invalid")
        super().__init__(code)
        self.code = code


class EvidenceRefreshBlocked(RuntimeError):
    """Fail-closed refresh state requiring explicit operator resolution."""


class EvidencePersistenceV1(Protocol):
    def persist_candidate(self, envelope: PersistedEvidenceEnvelope) -> None: ...


@dataclass(frozen=True)
class EvidenceRefreshItemV1:
    item_id: str
    request: ProviderEvidenceRequestV1

    def __post_init__(self) -> None:
        UUID(self.item_id)
        if self.item_id != self.request.request_id:
            raise UnifiedEvidenceContractViolation(
                "Refresh item identity must equal its canonical adapter request identity"
            )


@dataclass(frozen=True)
class EvidenceRefreshPlanV1:
    run_id: str
    plan_version: str
    items: tuple[EvidenceRefreshItemV1, ...]

    def __post_init__(self) -> None:
        UUID(self.run_id)
        if self.plan_version != EVIDENCE_REFRESH_PLAN_VERSION:
            raise UnifiedEvidenceContractViolation(
                "Unsupported provider-neutral evidence refresh plan version"
            )
        item_ids = tuple(item.item_id for item in self.items)
        if len(set(item_ids)) != len(item_ids):
            raise UnifiedEvidenceContractViolation(
                "Provider-neutral evidence refresh items must be unique"
            )

    @property
    def content_hash(self) -> str:
        payload = {
            "planVersion": self.plan_version,
            "runId": self.run_id,
            "items": [
                _refresh_request_identity_payload(item.request)
                for item in self.items
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceRefreshItemResultV1:
    item_id: str
    status: EvidenceRefreshItemStatus
    evidence_ids: tuple[str, ...]
    error_code: str | None


@dataclass(frozen=True)
class EvidenceRefreshRunResultV1:
    run_id: str
    outcome: EvidenceRefreshOutcome
    item_results: tuple[EvidenceRefreshItemResultV1, ...]


class ProviderNeutralEvidenceRefreshCoordinatorV1:
    """Bind existing lease/journal/checkpoint machinery to V22 persistence."""

    def __init__(
        self,
        *,
        repository: EvidencePersistenceV1,
        adapters: tuple[ProviderEvidenceAdapterV1, ...],
        private_runtime_root: Path,
    ) -> None:
        self._repository = repository
        self._adapters = {}
        for adapter in adapters:
            provider_code = adapter.descriptor.provider_code
            if provider_code in self._adapters:
                raise ValueError("Provider evidence adapters must be unique")
            self._adapters[provider_code] = adapter
        self._root = private_runtime_root

    def run(
        self,
        plan: EvidenceRefreshPlanV1,
    ) -> EvidenceRefreshRunResultV1:
        lease_path = self._root / "leases" / f"{plan.run_id}.lock"
        with ExecutionLease(lease_path, plan.run_id):
            physical_journal = PhysicalRequestJournal(
                self._root / "journals",
                plan.run_id,
            )
            preflight = {
                "sliceId": plan.content_hash,
                "symbols": [item.item_id for item in plan.items],
                "planVersion": plan.plan_version,
            }
            run_directory = (
                self._root / "journals" / plan.run_id / "run"
            )
            if run_directory.exists():
                try:
                    physical_journal.resume_preflight(preflight)
                except RuntimeError as error:
                    raise EvidenceRefreshBlocked(
                        "EVIDENCE_REFRESH_PLAN_REPLAY_MISMATCH"
                    ) from error
            else:
                physical_journal.preflight(preflight)
            symbol_journal = SymbolExecutionJournal(
                self._root / "journals",
                plan.run_id,
            )
            results = tuple(
                self._execute_item(
                    plan=plan,
                    item=item,
                    journal=symbol_journal,
                )
                for item in plan.items
            )
            failed = sum(
                result.status == EvidenceRefreshItemStatus.FAILED
                for result in results
            )
            outcome = (
                EvidenceRefreshOutcome.FAILED
                if results and failed == len(results)
                else EvidenceRefreshOutcome.PARTIAL
                if failed
                else EvidenceRefreshOutcome.SUCCEEDED
            )
            physical_journal.finalize(
                "ABORTED" if failed else "COMPLETE",
                {
                    "planHash": plan.content_hash,
                    "outcome": outcome.value,
                    "failedItemCount": failed,
                },
            )
            return EvidenceRefreshRunResultV1(
                run_id=plan.run_id,
                outcome=outcome,
                item_results=results,
            )

    def _execute_item(
        self,
        *,
        plan: EvidenceRefreshPlanV1,
        item: EvidenceRefreshItemV1,
        journal: SymbolExecutionJournal,
    ) -> EvidenceRefreshItemResultV1:
        resume_state, checkpoint = journal.resume(item.item_id)
        if resume_state == "UNKNOWN":
            raise EvidenceRefreshBlocked(
                f"UNKNOWN_EVIDENCE_REFRESH_STATE[{item.item_id}]"
            )
        if resume_state == "SKIP":
            if (
                checkpoint is None
                or checkpoint.get("planHash") != plan.content_hash
                or checkpoint.get("itemId") != item.item_id
            ):
                raise EvidenceRefreshBlocked(
                    f"EVIDENCE_REFRESH_CHECKPOINT_MISMATCH[{item.item_id}]"
                )
            return EvidenceRefreshItemResultV1(
                item_id=item.item_id,
                status=EvidenceRefreshItemStatus.REPLAYED,
                evidence_ids=tuple(checkpoint["evidenceIds"]),
                error_code=None,
            )
        adapter = self._adapters.get(item.request.provider_code)
        if adapter is None:
            raise EvidenceRefreshBlocked(
                f"PROVIDER_EVIDENCE_ADAPTER_NOT_CONFIGURED[{item.request.provider_code}]"
            )
        journal.append(
            item.item_id,
            "INTENT",
            {
                "planHash": plan.content_hash,
                "providerCode": item.request.provider_code,
            },
        )
        try:
            batch = adapter.fetch_canonical_evidence(item.request)
            batch.validate_for(item.request, adapter.descriptor)
            for envelope in batch.evidence:
                self._repository.persist_candidate(envelope)
        except ProviderAdapterFailure as error:
            journal.append(
                item.item_id,
                "FAILED",
                {
                    "planHash": plan.content_hash,
                    "errorCode": error.code,
                },
            )
            return EvidenceRefreshItemResultV1(
                item_id=item.item_id,
                status=EvidenceRefreshItemStatus.FAILED,
                evidence_ids=(),
                error_code=error.code,
            )
        result = {
            "planHash": plan.content_hash,
            "itemId": item.item_id,
            "evidenceIds": [
                envelope.candidate.evidence_id for envelope in batch.evidence
            ],
        }
        checkpoint_path, checkpoint_hash = journal.checkpoint(
            item.item_id,
            result,
        )
        journal.append(
            item.item_id,
            "COMPLETED",
            {
                "planHash": plan.content_hash,
                "checkpointPath": str(checkpoint_path),
                "checkpointHash": checkpoint_hash,
            },
        )
        return EvidenceRefreshItemResultV1(
            item_id=item.item_id,
            status=EvidenceRefreshItemStatus.PERSISTED,
            evidence_ids=tuple(result["evidenceIds"]),
            error_code=None,
        )


def bind_daily_refresh_plan_v1(
    plan: RefreshPlan,
    *,
    securities: Mapping[str, SecurityIdentity],
    completed_session: CompletedSession,
    provider_routes: Mapping[str, str],
) -> EvidenceRefreshPlanV1:
    """Project the existing offline refresh plan onto canonical adapter work."""

    if plan.expected_session_date != completed_session.session_date:
        raise UnifiedEvidenceContractViolation(
            "Daily refresh plan session does not match the completed session"
        )
    bound: list[EvidenceRefreshItemV1] = []
    seen_request_keys: set[str] = set()
    for item in plan.items:
        if item.expected_session_date != completed_session.session_date:
            raise UnifiedEvidenceContractViolation(
                "Daily refresh item session does not match the completed session"
            )
        security = securities.get(item.security.security_id)
        provider_code = provider_routes.get(item.provider_code)
        if security is None or provider_code is None:
            raise UnifiedEvidenceContractViolation(
                "Daily refresh plan identity or provider route is unresolved"
            )
        if (
            security.security_id != item.security.security_id
            or security.ticker != item.security.symbol
            or security.mic != completed_session.mic
        ):
            raise UnifiedEvidenceContractViolation(
                "Daily refresh security, listing, or session identity is inconsistent"
            )
        domain, fields = _dataset_binding(item.dataset)
        if item.request_key in seen_request_keys:
            continue
        seen_request_keys.add(item.request_key)
        request = ProviderEvidenceRequestV1.create(
            provider_code=provider_code,
            security=security,
            completed_session=completed_session,
            domain=domain,
            requested_field_codes=fields,
            start_date=item.start_date,
            end_date=item.end_date,
        )
        bound.append(
            EvidenceRefreshItemV1(
                item_id=request.request_id,
                request=request,
            )
        )
    item_identity = "\x1f".join(item.item_id for item in bound)
    run_id = str(
        uuid5(
            NAMESPACE_URL,
            "\x1f".join(
                (
                    EVIDENCE_REFRESH_PLAN_VERSION,
                    plan.configuration_hash,
                    plan.universe_version,
                    plan.as_of.astimezone(UTC).isoformat(),
                    completed_session.completed_at.astimezone(UTC).isoformat(),
                    item_identity,
                )
            ),
        )
    )
    return EvidenceRefreshPlanV1(
        run_id=run_id,
        plan_version=EVIDENCE_REFRESH_PLAN_VERSION,
        items=tuple(bound),
    )


def _dataset_binding(
    dataset: Dataset,
) -> tuple[EvidenceDomain, tuple[str, ...]]:
    if dataset == Dataset.DAILY_PRICE:
        return (
            EvidenceDomain.DAILY_PRICE,
            (
                "OPEN_PRICE",
                "HIGH_PRICE",
                "LOW_PRICE",
                "CLOSE_PRICE",
                "ADJUSTED_CLOSE",
                "VOLUME",
            ),
        )
    if dataset == Dataset.CORPORATE_ACTION:
        return EvidenceDomain.CORPORATE_ACTION, ("CORPORATE_ACTION",)
    if dataset == Dataset.FUNDAMENTALS:
        return (
            EvidenceDomain.FUNDAMENTAL,
            (
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
            ),
        )
    raise UnifiedEvidenceContractViolation(
        f"Unsupported daily refresh dataset {dataset}"
    )


def _refresh_request_identity_payload(
    request: ProviderEvidenceRequestV1,
) -> dict[str, object]:
    return {
        "itemId": request.request_id,
        **provider_request_identity_payload_v1(
            provider_code=request.provider_code,
            security=request.security,
            completed_session=request.completed_session,
            domain=request.domain,
            requested_field_codes=request.requested_field_codes,
            start_date=request.start_date,
            end_date=request.end_date,
        ),
    }
