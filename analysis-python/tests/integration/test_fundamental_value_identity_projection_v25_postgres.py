from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from equity_analysis.fundamental_value.identity_projection_v2 import (
    PostgresIdentityAuthorityV2Repository,
    load_accepted_identity_projection_v2,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
STAGE8C_STORAGE = (
    REPOSITORY_ROOT
    / "storage/fundamental-value-forward-enrollment-v1/stage8c"
)


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required")
    if "test" not in value.rsplit("/", 1)[-1].lower():
        pytest.fail("V25 integration requires an explicitly disposable test database")
    return value


def test_v25_real_projection_round_trip_and_exact_replay() -> None:
    url = _database_url()
    if not (STAGE8C_STORAGE / ".fv-stage8c-private-storage.json").is_file():
        pytest.skip("accepted private Stage 8C storage is not available")
    projection = load_accepted_identity_projection_v2(
        repository_root=REPOSITORY_ROOT,
        storage_root=STAGE8C_STORAGE,
    )
    repository = PostgresIdentityAuthorityV2Repository(url)
    first = repository.persist(projection)
    replay = repository.persist(projection)
    loaded = repository.load(projection.content_hash)
    assert first == projection
    assert replay == projection
    assert loaded == projection

    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM analytics.fv_identity_authority_v2
                     WHERE projection_content_hash=%s),
                    (SELECT count(*) FROM analytics.fv_identity_authority_member_v2
                     WHERE authority_id=(
                       SELECT authority_id FROM analytics.fv_identity_authority_v2
                       WHERE projection_content_hash=%s)),
                    (SELECT count(*) FROM analytics.fv_identity_authority_seal_v2
                     WHERE projection_content_hash=%s),
                    (SELECT count(*) FROM analytics.security
                     WHERE symbol IN ('GOOG','FOX','MSFT'))
                """,
                (projection.content_hash,) * 3,
            )
            assert cursor.fetchone() == (1, 3, 1, 3)
            cursor.execute(
                """
                SELECT count(*)
                FROM analytics.fv_identity_authority_member_v2 member
                JOIN analytics.evidence_listing_identity_v1 listing
                  ON listing.listing_id=member.listing_id
                 AND listing.security_id=member.security_id
                 AND listing.mic=member.mic
                JOIN analytics.evidence_ticker_assignment_v1 ticker
                  ON ticker.ticker_assignment_id=member.ticker_assignment_id
                 AND ticker.listing_id=member.listing_id
                 AND ticker.ticker=member.ticker
                WHERE member.authority_id=(
                    SELECT authority_id FROM analytics.fv_identity_authority_v2
                    WHERE projection_content_hash=%s)
                """,
                (projection.content_hash,),
            )
            assert cursor.fetchone() == (3,)


def test_v25_authority_is_append_only() -> None:
    url = _database_url()
    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                cursor.execute(
                    """
                    UPDATE analytics.fv_identity_authority_v2
                    SET evidence_claim='ALTERED'
                    WHERE projection_content_hash=%s
                    """,
                    (
                        "sha256:96887c70c369f412a2bfbb480ebe176db841cacb0c9a6f9c2618ee36c2bcf545",
                    ),
                )
        connection.rollback()
