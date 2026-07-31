"""Historical time-slice validation for deterministic investment models."""

from equity_analysis.historical_validation.engine import evaluate_time_slices
from equity_analysis.historical_validation.models import (
    BenchmarkKind,
    EvidenceMode,
    HistoricalConclusion,
    HistoricalOutcome,
    HistoricalSignal,
    HistoricalTimeSlice,
    HistoricalValidationProtocol,
    HistoricalValidationReport,
    TimePartition,
    UniverseMode,
)
from equity_analysis.historical_validation.sampling_v1 import (
    HISTORICAL_SLICE_PLAN_VERSION,
    HistoricalAgeBand,
    HistoricalSamplePoint,
    HistoricalSlicePlan,
    build_historical_slice_plan,
)
from equity_analysis.historical_validation.tactical_slices_v1 import (
    TACTICAL_SLICE_VALIDATION_VERSION,
    TacticalSliceAggregate,
    TacticalSliceEpisode,
    TacticalSliceValidationResult,
    evaluate_tactical_time_slices,
)

__all__ = [
    "BenchmarkKind",
    "EvidenceMode",
    "HistoricalConclusion",
    "HistoricalOutcome",
    "HistoricalSignal",
    "HistoricalTimeSlice",
    "HistoricalValidationProtocol",
    "HistoricalValidationReport",
    "TimePartition",
    "UniverseMode",
    "HISTORICAL_SLICE_PLAN_VERSION",
    "HistoricalAgeBand",
    "HistoricalSamplePoint",
    "HistoricalSlicePlan",
    "build_historical_slice_plan",
    "TACTICAL_SLICE_VALIDATION_VERSION",
    "TacticalSliceAggregate",
    "TacticalSliceEpisode",
    "TacticalSliceValidationResult",
    "evaluate_tactical_time_slices",
    "evaluate_time_slices",
]
