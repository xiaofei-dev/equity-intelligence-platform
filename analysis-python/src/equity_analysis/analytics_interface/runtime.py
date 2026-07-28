from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from equity_analysis.analytics_interface.contracts import (
    REQUEST_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    AiOverlayStatus,
    AnalyticsModelId,
    AnalyticsModelInputError,
    AnalyticsModelResolutionError,
    LongHorizonModelRequest,
    MissingDataState,
    ModelRequest,
    ModelResultEnvelope,
    ModelRunStatus,
    TacticalModelRequest,
    dataclass_payload,
)
from equity_analysis.research_rating.long_horizon_v1 import (
    LONG_HORIZON_VERSION,
    LongHorizonAssessment,
    LongHorizonInputs,
    evaluate_long_horizon,
)
from equity_analysis.tactical.signal_v2 import (
    TACTICAL_SIGNAL_VERSION,
    TacticalAssessment,
    evaluate_tactical_signal,
)


class AnalyticsModelEvaluator(Protocol):
    model_id: AnalyticsModelId
    model_version: str
    request_type: type[Any]

    def evaluate(self, request: ModelRequest) -> ModelResultEnvelope: ...


@dataclass(frozen=True)
class LongHorizonEvaluator:
    evaluate_function: Callable[
        [LongHorizonInputs],
        LongHorizonAssessment,
    ] = evaluate_long_horizon
    model_id: AnalyticsModelId = AnalyticsModelId.LONG_HORIZON_RESEARCH
    model_version: str = LONG_HORIZON_VERSION
    request_type: type[LongHorizonModelRequest] = LongHorizonModelRequest

    def evaluate(self, request: ModelRequest) -> ModelResultEnvelope:
        if not isinstance(request, LongHorizonModelRequest):
            raise AnalyticsModelInputError(
                "Long-horizon evaluator received the wrong request type",
                "MODEL_REQUEST_TYPE_MISMATCH",
            )
        try:
            assessment = self.evaluate_function(request.inputs)
        except ValueError as error:
            raise AnalyticsModelInputError(
                str(error),
                "INVALID_MODEL_INPUT",
            ) from error
        missing = _unique(
            request.evidence.missing_inputs + assessment.missing_fields
        )
        status = (
            ModelRunStatus.ASSESSED
            if assessment.status == "ASSESSED"
            else ModelRunStatus.INSUFFICIENT_DATA
        )
        missing_state = (
            MissingDataState.COMPLETE
            if status == ModelRunStatus.ASSESSED and not missing
            else MissingDataState.PARTIAL
            if status == ModelRunStatus.ASSESSED
            else MissingDataState.INSUFFICIENT
        )
        return _result(
            request=request,
            status=status,
            missing_state=missing_state,
            missing_inputs=missing,
            deterministic_result=dataclass_payload(assessment),
        )


@dataclass(frozen=True)
class TacticalEvaluator:
    evaluate_function: Callable[..., TacticalAssessment] = evaluate_tactical_signal
    model_id: AnalyticsModelId = AnalyticsModelId.DAILY_TACTICAL_SIGNAL
    model_version: str = TACTICAL_SIGNAL_VERSION
    request_type: type[TacticalModelRequest] = TacticalModelRequest

    def evaluate(self, request: ModelRequest) -> ModelResultEnvelope:
        if not isinstance(request, TacticalModelRequest):
            raise AnalyticsModelInputError(
                "Tactical evaluator received the wrong request type",
                "MODEL_REQUEST_TYPE_MISMATCH",
            )
        try:
            assessment = self.evaluate_function(
                request.security_bars,
                request.benchmark_bars,
                event_drift_score=request.event_drift_score,
                prior_reversal_context=request.prior_reversal_context,
            )
        except ValueError as error:
            raise AnalyticsModelInputError(
                str(error),
                "INVALID_MODEL_INPUT",
            ) from error
        missing = list(request.evidence.missing_inputs)
        for horizon in assessment.horizons:
            if getattr(horizon, "opportunity_score", None) is None:
                missing.append(f"{horizon.horizon_label.lower()}_history")
        normalized_missing = _unique(tuple(missing))
        return _result(
            request=request,
            status=ModelRunStatus.ASSESSED,
            missing_state=(
                MissingDataState.PARTIAL
                if normalized_missing
                else MissingDataState.COMPLETE
            ),
            missing_inputs=normalized_missing,
            # Serialize the complete registered result so additive fields remain
            # forward-compatible at the envelope boundary.
            deterministic_result=dataclass_payload(assessment),
        )


class AnalyticsModelRegistry:
    def __init__(
        self,
        evaluators: tuple[AnalyticsModelEvaluator, ...] = (),
    ) -> None:
        self._evaluators: dict[
            tuple[AnalyticsModelId, str],
            AnalyticsModelEvaluator,
        ] = {}
        for evaluator in evaluators:
            self.register(evaluator)

    def register(self, evaluator: AnalyticsModelEvaluator) -> None:
        key = (evaluator.model_id, evaluator.model_version)
        if key in self._evaluators:
            raise ValueError(
                f"Evaluator {evaluator.model_id}/{evaluator.model_version} is registered"
            )
        self._evaluators[key] = evaluator

    def resolve(
        self,
        model_id: AnalyticsModelId,
        model_version: str,
    ) -> AnalyticsModelEvaluator:
        evaluator = self._evaluators.get((model_id, model_version))
        if evaluator is not None:
            return evaluator
        if any(key[0] == model_id for key in self._evaluators):
            raise AnalyticsModelResolutionError(
                f"Model version {model_version} is not supported for {model_id}",
                "MODEL_VERSION_UNSUPPORTED",
            )
        raise AnalyticsModelResolutionError(
            f"Model {model_id} is not registered",
            "MODEL_NOT_REGISTERED",
        )


class AnalyticsModelFacade:
    def __init__(self, registry: AnalyticsModelRegistry) -> None:
        self._registry = registry

    def evaluate(self, request: ModelRequest) -> ModelResultEnvelope:
        if request.schema_version != REQUEST_SCHEMA_VERSION:
            raise AnalyticsModelResolutionError(
                f"Request schema {request.schema_version} is not supported",
                "MODEL_REQUEST_SCHEMA_UNSUPPORTED",
            )
        evaluator = self._registry.resolve(
            request.model_id,
            request.model_version,
        )
        if not isinstance(request, evaluator.request_type):
            raise AnalyticsModelInputError(
                "Request type does not match the selected model",
                "MODEL_REQUEST_TYPE_MISMATCH",
            )
        return evaluator.evaluate(request)


def create_default_model_facade() -> AnalyticsModelFacade:
    return AnalyticsModelFacade(
        AnalyticsModelRegistry(
            (
                LongHorizonEvaluator(),
                TacticalEvaluator(),
            )
        )
    )


def _result(
    *,
    request: ModelRequest,
    status: ModelRunStatus,
    missing_state: MissingDataState,
    missing_inputs: tuple[str, ...],
    deterministic_result: dict[str, Any],
) -> ModelResultEnvelope:
    return ModelResultEnvelope(
        request_schema_version=request.schema_version,
        schema_version=RESULT_SCHEMA_VERSION,
        model_id=request.model_id,
        model_version=request.model_version,
        symbol=request.symbol,
        status=status,
        missing_data_state=missing_state,
        missing_inputs=missing_inputs,
        as_of=request.timing.as_of,
        effective_at=request.timing.effective_at,
        expires_at=request.timing.expires_at,
        input_hash=request.input_hash,
        evidence_hash=request.evidence.evidence_hash,
        provider_provenance=request.evidence.providers,
        deterministic_result=deterministic_result,
        ai_boundary=request.evidence.ai_boundary,
        ai_overlay_status=AiOverlayStatus.NOT_EXECUTED,
        ai_overlay_result=None,
    )


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
