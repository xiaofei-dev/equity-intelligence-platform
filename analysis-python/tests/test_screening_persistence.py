from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from equity_analysis.screening.models import ScreeningRunRequest
from equity_analysis.screening.persistence import ScreeningRepository
from equity_analysis.screening.snapshot import DataSnapshotRepository, SnapshotRequest

AS_OF = datetime(2026, 7, 25, 20, 0, tzinfo=UTC)


def test_screening_request_hash_is_order_independent_for_strategy_versions() -> None:
    first = ScreeningRunRequest(
        as_of_time=AS_OF,
        data_snapshot_id="snapshot-2026-07-25",
        universe_version="universe-us-general-company-v1.0.0",
        strategy_versions=("UQ-v1.0.0", "QC-v1.0.0"),
    )
    second = first.model_copy(update={"strategy_versions": ("QC-v1.0.0", "UQ-v1.0.0", "QC-v1.0.0")})

    first_payload, first_hash = ScreeningRepository.canonical_request(first)
    second_payload, second_hash = ScreeningRepository.canonical_request(second)

    assert first_payload == second_payload
    assert first_hash == second_hash


def test_snapshot_manifest_is_deterministic_for_source_order() -> None:
    request = SnapshotRequest(
        snapshot_key="snapshot-2026-07-25",
        as_of_time=AS_OF,
        ingestion_cutoff=datetime(2026, 7, 26, 20, 0, tzinfo=UTC),
        universe_version="universe-us-general-company-v1.0.0",
        market_normalization_version="market-v1",
        fundamental_normalization_version="fundamental-v1",
        action_normalization_version="action-v1",
    )
    sources = [
        {
            "batch_id": UUID("00000000-0000-0000-0000-000000000002"),
            "content_hash": "sha256:b",
            "source_reference": "source-b",
        },
        {
            "batch_id": UUID("00000000-0000-0000-0000-000000000001"),
            "content_hash": "sha256:a",
            "source_reference": "source-a",
        },
    ]

    assert DataSnapshotRepository._identity(request, sources) == DataSnapshotRepository._identity(
        request, list(reversed(sources))
    )


def test_snapshot_identity_binds_market_and_supplemental_provider_scope() -> None:
    request = SnapshotRequest(
        snapshot_key="snapshot-2026-07-25",
        as_of_time=AS_OF,
        ingestion_cutoff=datetime(2026, 7, 26, 20, 0, tzinfo=UTC),
        universe_version="universe-us-general-company-v1.0.0",
        market_normalization_version="market-v1",
        fundamental_normalization_version="fundamental-v1",
        action_normalization_version="action-v1",
        market_data_provider="yfinance",
        supplemental_provider_codes=("eodhd",),
    )

    without_fundamentals = replace(request, supplemental_provider_codes=())

    assert DataSnapshotRepository._identity(
        request, []
    ) != DataSnapshotRepository._identity(without_fundamentals, [])
