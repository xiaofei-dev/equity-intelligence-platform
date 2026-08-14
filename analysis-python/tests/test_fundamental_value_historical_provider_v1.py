from datetime import UTC, date, datetime

import pytest

from equity_analysis.fundamental_value.historical_provider_v1 import (
    AvailabilityQuality,
    HistoricalEvidenceEnvelope,
    ProviderEvidenceState,
    build_eodhd_preflight,
    validate_evidence_envelope,
)


def envelope(quality: AvailabilityQuality) -> HistoricalEvidenceEnvelope:
    return HistoricalEvidenceEnvelope(
        "SEC-1", "FUNDAMENTAL", "EBIT", date(2019, 1, 1), date(2019, 12, 31),
        datetime(2020, 2, 1, tzinfo=UTC), datetime(2020, 2, 1, tzinfo=UTC),
        None if quality == AvailabilityQuality.CURRENT_REVISION_APPROXIMATION
        else datetime(2020, 2, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC),
        "eodhd", "schema-v1", "adapter-v1", "normalization-v1", "revision-v1",
        "actions-v1", "A" * 64, "B" * 64, ProviderEvidenceState.VALID, quality,
    )


def test_preflight_schedule_parity_is_eleven_canaries() -> None:
    result = build_eodhd_preflight()
    assert result["combinedMaximumBatch0"]["crossSectorCanaryCount"] == 11
    assert result["combinedMaximumBatch0"]["physicalRequestCeiling"] == 91
    assert result["phases"]["BASELINE"]["batch0EodhdPhysicalRequests"] == 33
    assert result["phases"]["OPTIONAL_BENCHMARK_EOD_ACTIONS"]["physicalRequests"] == 36
    assert result["fullRun"]["configuredWeightCeilingIncludingSnapshot"] == 4377
    assert result["membershipBatches"]["finalCount"] == 24


def test_approximation_rejects_future_period_and_filing_proxy() -> None:
    value = envelope(AvailabilityQuality.CURRENT_REVISION_APPROXIMATION)
    future_period = HistoricalEvidenceEnvelope(**{**value.__dict__, "period_end": date(2021, 1, 1)})
    with pytest.raises(ValueError, match="FUTURE_PERIOD"):
        validate_evidence_envelope(future_period, datetime(2020, 3, 1, tzinfo=UTC))
    future_filing = HistoricalEvidenceEnvelope(**{**value.__dict__,
        "filing_or_publication_at": datetime(2020, 4, 1, tzinfo=UTC)})
    with pytest.raises(ValueError, match="FUTURE_FILING"):
        validate_evidence_envelope(future_filing, datetime(2020, 3, 1, tzinfo=UTC))


def test_strict_pit_requires_revision_and_adjustment_lineage() -> None:
    value = envelope(AvailabilityQuality.STRICT_PIT)
    value = HistoricalEvidenceEnvelope(**{**value.__dict__, "revision_id": None})
    with pytest.raises(ValueError, match="REVISION_AND_ADJUSTMENT"):
        validate_evidence_envelope(value, datetime(2020, 3, 1, tzinfo=UTC))


def test_evidence_rejects_nonhex_hash() -> None:
    value = HistoricalEvidenceEnvelope(**{**envelope(AvailabilityQuality.STRICT_PIT).__dict__,
                                           "source_hash": "Z" * 64})
    with pytest.raises(ValueError, match="INVALID_SOURCE_HASH"):
        validate_evidence_envelope(value, datetime(2020, 3, 1, tzinfo=UTC))


def test_evidence_rejects_naive_timestamp_and_blank_strict_lineage() -> None:
    value = envelope(AvailabilityQuality.STRICT_PIT)
    naive = HistoricalEvidenceEnvelope(**{**value.__dict__,
        "effective_at": datetime(2020, 1, 1)})
    with pytest.raises(ValueError, match="TIMEZONE_AWARE"):
        validate_evidence_envelope(naive, datetime(2020, 3, 1, tzinfo=UTC))
    blank = HistoricalEvidenceEnvelope(**{**value.__dict__, "revision_id": "  "})
    with pytest.raises(ValueError, match="REVISION_AND_ADJUSTMENT"):
        validate_evidence_envelope(blank, datetime(2020, 3, 1, tzinfo=UTC))
