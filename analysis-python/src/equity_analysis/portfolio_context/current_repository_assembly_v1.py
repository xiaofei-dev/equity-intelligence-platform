"""ID-only repository-hydrated current portfolio assembly boundary."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from equity_analysis.evidence_foundation.contracts_v1 import DataState
from equity_analysis.evidence_foundation.persistence_v1 import EvidenceFoundationRepository
from equity_analysis.evidence_foundation.persistence_v1 import _result_hash as selector_result_hash
from equity_analysis.fundamental_value.current_assessment_persistence_v1 import (
    CurrentAssessmentRepositoryV1,
)
from equity_analysis.quant_trading.research_persistence_v11 import (
    QuantResearchDecisionRepositoryV11,
)

from .contracts_v1 import ConstraintInputV1, EvidenceState, ModelEvidenceLabel, SleeveType
from .evidence_assembly_v2 import (
    ASSEMBLY_VERSION,
    CurrentPortfolioAssemblyResultV1,
    CurrentPortfolioAssemblyV1,
    CurrentPortfolioEvidenceViolation,
    HoldingEvidenceV1,
    ModelReferenceV1,
    PriceEvidenceV1,
    assemble_current_portfolio_v1,
)


@dataclass(frozen=True, slots=True)
class HoldingSelectionReferenceV1:
    security_id: str
    ticker: str
    quantity: Decimal
    sleeve: SleeveType
    sector_code: str
    selection_request_id: str
    model_reference_id: str | None


@dataclass(frozen=True, slots=True)
class CurrentPortfolioByIdRequestV1:
    as_of_time: datetime
    cash_value: Decimal
    liability_value: Decimal
    holdings: tuple[HoldingSelectionReferenceV1, ...]
    constraints: ConstraintInputV1


class CurrentPortfolioRepositoryAssemblerV1:
    """Hydrate V22/V26/V27 records; callers cannot supply valuations or evidence hashes."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise CurrentPortfolioEvidenceViolation("DATABASE_URL_REQUIRED")
        self._database_url = database_url

    def assemble(
        self, request: CurrentPortfolioByIdRequestV1
    ) -> CurrentPortfolioAssemblyResultV1:
        if type(request.holdings) is not tuple:
            raise CurrentPortfolioEvidenceViolation("HOLDING_REFERENCES_MUST_BE_TUPLE")
        evidence_repository = EvidenceFoundationRepository(self._database_url)
        holdings = tuple(
            self._holding(evidence_repository, item, request.as_of_time)
            for item in request.holdings
        )
        references, per_security_references = self._model_references(request)
        result = assemble_current_portfolio_v1(
            CurrentPortfolioAssemblyV1(
                request.as_of_time,
                request.cash_value,
                request.liability_value,
                holdings,
                references,
                request.constraints,
            )
        )
        result.evidence_manifest["perSecurityModelReferences"] = per_security_references
        canonical = json.dumps(
            {
                key: value
                for key, value in result.evidence_manifest.items()
                if key != "manifestHash"
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        result.evidence_manifest["manifestHash"] = (
            f"sha256:{sha256(canonical.encode()).hexdigest()}"
        )
        return result

    def _model_references(
        self, request: CurrentPortfolioByIdRequestV1
    ) -> tuple[tuple[ModelReferenceV1, ...], list[dict[str, object]]]:
        fundamental_repository = CurrentAssessmentRepositoryV1(self._database_url)
        quant_repository = QuantResearchDecisionRepositoryV11(self._database_url)
        rows: list[dict[str, object]] = []
        by_sleeve: dict[SleeveType, list[tuple[str, str, ModelEvidenceLabel, bool]]] = {
            SleeveType.LONG_TERM_CORE: [],
            SleeveType.QUANT_TRADING: [],
        }
        quant_cache: dict[str, object] = {}
        for holding in sorted(request.holdings, key=lambda item: item.security_id):
            _uuid(holding.security_id, "SECURITY_ID_INVALID")
            _uuid(holding.selection_request_id, "SELECTION_REQUEST_ID_INVALID")
            if holding.sleeve is SleeveType.UNASSIGNED:
                if holding.model_reference_id is not None:
                    raise CurrentPortfolioEvidenceViolation(
                        "UNASSIGNED_MODEL_REFERENCE_FORBIDDEN"
                    )
                rows.append({"securityId": holding.security_id, "sleeve": holding.sleeve.value,
                             "referenceId": None, "referenceHash": None})
                continue
            if holding.model_reference_id is None:
                raise CurrentPortfolioEvidenceViolation("MODEL_REFERENCE_REQUIRED")
            _uuid(holding.model_reference_id, "MODEL_REFERENCE_ID_INVALID")
            if holding.sleeve is SleeveType.LONG_TERM_CORE:
                persisted = fundamental_repository.load(holding.model_reference_id)
                payload = persisted.payload
                decision_cutoff = _instant(payload.get("decision_cutoff"))
                if decision_cutoff > request.as_of_time:
                    raise CurrentPortfolioEvidenceViolation(
                        "FUNDAMENTAL_REFERENCE_AFTER_CONTEXT_CUTOFF"
                    )
                security_id = payload.get("security_id", payload.get("securityId"))
                if security_id != holding.security_id:
                    raise CurrentPortfolioEvidenceViolation(
                        "FUNDAMENTAL_REFERENCE_SECURITY_MISMATCH"
                    )
                model = str(payload["assessment"]["model_version"])
                label = ModelEvidenceLabel(payload["model_evidence_label"])
                allowed = _effective_research_authority(
                    payload["model_evidence_label"],
                    payload["investment_view"]["deterministic_action_authorized"],
                )
                reference_hash = persisted.assessment_content_hash
            else:
                persisted = quant_cache.get(holding.model_reference_id)
                if persisted is None:
                    persisted = quant_repository.load(holding.model_reference_id)
                    quant_cache[holding.model_reference_id] = persisted
                payload = persisted.payload
                decision_date = payload.get("decisionDate")
                if (
                    type(decision_date) is not str
                    or decision_date > request.as_of_time.date().isoformat()
                ):
                    raise CurrentPortfolioEvidenceViolation(
                        "QUANT_REFERENCE_AFTER_CONTEXT_CUTOFF"
                    )
                if not any(
                    signal.get("securityId") == holding.security_id
                    for signal in payload.get("signals", [])
                ):
                    raise CurrentPortfolioEvidenceViolation(
                        "QUANT_REFERENCE_SECURITY_MISMATCH"
                    )
                model = str(payload["modelVersion"])
                label = ModelEvidenceLabel(payload["modelEvidenceLabel"])
                allowed = _effective_research_authority(
                    payload["modelEvidenceLabel"],
                    payload["authority"]["deterministicResearchSignal"],
                )
                reference_hash = persisted.content_hash
            _hash(reference_hash, "MODEL_REFERENCE_HASH_INVALID")
            by_sleeve[holding.sleeve].append(
                (holding.model_reference_id, reference_hash, label, allowed)
            )
            rows.append(
                {
                    "securityId": holding.security_id,
                    "sleeve": holding.sleeve.value,
                    "referenceId": holding.model_reference_id,
                    "referenceHash": reference_hash,
                    "modelVersion": model,
                    "evidenceLabel": label.value,
                    "researchUseAllowed": allowed,
                }
            )
        references: list[ModelReferenceV1] = []
        for sleeve in (SleeveType.LONG_TERM_CORE, SleeveType.QUANT_TRADING):
            items = by_sleeve[sleeve]
            if not items:
                empty_hash = f"sha256:{sha256(f'{sleeve.value}:empty'.encode()).hexdigest()}"
                references.append(
                    ModelReferenceV1(
                        sleeve,
                        "NO_MODEL",
                        ModelEvidenceLabel.NOT_VALIDATED,
                        False,
                        str(
                            uuid5(
                                NAMESPACE_URL,
                                f"{ASSEMBLY_VERSION}:{sleeve.value}:empty",
                            )
                        ),
                        empty_hash,
                    )
                )
                continue
            models = {row["modelVersion"] for row in rows if row["sleeve"] == sleeve.value}
            labels = {item[2] for item in items}
            if len(models) != 1 or len(labels) != 1:
                raise CurrentPortfolioEvidenceViolation("SLEEVE_MODEL_REFERENCE_DRIFT")
            canonical = json.dumps([(item[0], item[1]) for item in items], separators=(",", ":"))
            digest = f"sha256:{sha256(canonical.encode()).hexdigest()}"
            references.append(
                ModelReferenceV1(
                    sleeve,
                    next(iter(models)),
                    next(iter(labels)),
                    all(item[3] for item in items),
                    str(
                        uuid5(
                            NAMESPACE_URL,
                            f"{ASSEMBLY_VERSION}:{sleeve.value}:{digest}",
                        )
                    ),
                    digest,
                )
            )
        return tuple(references), rows

    def _holding(
        self,
        repository: EvidenceFoundationRepository,
        reference: HoldingSelectionReferenceV1,
        cutoff: datetime,
    ) -> HoldingEvidenceV1:
        aggregate = repository.load_selector_aggregate(reference.selection_request_id)
        request = aggregate.request
        result = aggregate.result
        if request.security.security_id != reference.security_id:
            raise CurrentPortfolioEvidenceViolation("PRICE_REFERENCE_SECURITY_MISMATCH")
        if request.security.ticker != reference.ticker:
            raise CurrentPortfolioEvidenceViolation("PRICE_REFERENCE_TICKER_MISMATCH")
        if request.decision_cutoff > cutoff or request.sealed_ingestion_cutoff > cutoff:
            raise CurrentPortfolioEvidenceViolation("PRICE_REFERENCE_AFTER_CONTEXT_CUTOFF")
        if (
            request.policy.domain != "DAILY_PRICE"
            or request.policy.field_code != "CLOSE_PRICE"
            or request.policy.domain_constraints.get("adjustmentMode")
            != "UNADJUSTED"
        ):
            raise CurrentPortfolioEvidenceViolation("PRICE_REFERENCE_DOMAIN_MISMATCH")
        selected = result.selected
        state = EvidenceState(result.state.value)
        result_hash = selector_result_hash(request, result)
        if result.state is DataState.VALID:
            if selected is None or selected.canonical_data is None:
                raise CurrentPortfolioEvidenceViolation("VALID_PRICE_SELECTION_INCOMPLETE")
            if selected.canonical_data.get("adjustmentMode") != "UNADJUSTED":
                raise CurrentPortfolioEvidenceViolation("PRICE_REFERENCE_DOMAIN_MISMATCH")
            price_value = selected.canonical_data.get("close")
            if type(price_value) is not str:
                raise CurrentPortfolioEvidenceViolation("CLOSE_PRICE_VALUE_INVALID")
            stale_after = selected.stale_after
            if (
                stale_after is None
                or stale_after.tzinfo is None
                or stale_after.microsecond != 0
                or cutoff > stale_after
            ):
                raise CurrentPortfolioEvidenceViolation("PRICE_EVIDENCE_STALE_AT_CONTEXT")
            price = Decimal(price_value)
            evidence = PriceEvidenceV1(
                state,
                reference.selection_request_id,
                result_hash,
                selected.evidence_id,
                selected.normalized_record_hash,
                price,
                selected.effective_at,
                selected.available_at,
                selected.ingested_at,
            )
        else:
            evidence = PriceEvidenceV1(
                state,
                reference.selection_request_id,
                result_hash,
                None,
                None,
                None,
                None,
                None,
                None,
            )
        return HoldingEvidenceV1(
            reference.security_id,
            reference.ticker,
            reference.quantity,
            reference.sleeve,
            reference.sector_code,
            evidence,
        )


def _instant(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str and value.endswith("Z"):
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as error:
            raise CurrentPortfolioEvidenceViolation(
                "MODEL_REFERENCE_DECISION_CUTOFF_INVALID"
            ) from error
    else:
        raise CurrentPortfolioEvidenceViolation(
            "MODEL_REFERENCE_DECISION_CUTOFF_INVALID"
        )
    if parsed.tzinfo is None or parsed.microsecond != 0:
        raise CurrentPortfolioEvidenceViolation(
            "MODEL_REFERENCE_DECISION_CUTOFF_INVALID"
        )
    return parsed


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _uuid(value: object, reason: str) -> str:
    if type(value) is not str or not _UUID.fullmatch(value):
        raise CurrentPortfolioEvidenceViolation(reason)
    return value


def _hash(value: object, reason: str) -> str:
    if type(value) is not str or not _HASH.fullmatch(value):
        raise CurrentPortfolioEvidenceViolation(reason)
    return value


def _effective_research_authority(label: object, asserted: object) -> bool:
    if type(asserted) is not bool:
        raise CurrentPortfolioEvidenceViolation("MODEL_RESEARCH_AUTHORITY_INVALID")
    if label == "NOT_VALIDATED":
        return False
    return asserted
