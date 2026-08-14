"""Seed the controlled GOOG V22/V26 graph used by Task 5 live acceptance.

This utility is test-only. It reads no provider endpoint and accepts only a disposable
database whose name contains ``test``. The source payloads and receipt journals come
from the already accepted Git-safe V26 integration fixture.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis-python" / "src"))
sys.path.insert(0, str(ROOT / "analysis-python" / "tests"))

from integration.test_current_assessment_persistence_v26_postgres import (  # noqa: E402
    _build_registered_assessment,
)

from equity_analysis.fundamental_value.current_assessment_persistence_v1 import (  # noqa: E402
    AUTHORIZATION_CONTENT_HASH,
    AUTHORIZATION_REFERENCE,
    CurrentAssessmentRepositoryV1,
    provision_current_assessment_authority_v1,
)


def seed(database_url: str) -> dict[str, str]:
    if "test" not in database_url.rsplit("/", 1)[-1].lower():
        raise ValueError("Task 5 live fixture requires a disposable test database")
    storage = Path(tempfile.mkdtemp(prefix="task5-goog-v26-"))
    assessment = _build_registered_assessment(
        database_url,
        storage,
        provision_assessment_authority=False,
        ticker="GOOG",
        cutoff_second_offset=2,
    )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT projection_content_hash FROM analytics.fv_identity_authority_v2 "
                "ORDER BY recorded_at DESC LIMIT 1"
            )
            projection_hash = cursor.fetchone()["projection_content_hash"]
    provision_current_assessment_authority_v1(
        database_url,
        identity_projection_content_hash=projection_hash,
        authorization_reference=AUTHORIZATION_REFERENCE,
        authorization_content_hash=AUTHORIZATION_CONTENT_HASH,
        authority_write_authorized=True,
    )
    persisted = CurrentAssessmentRepositoryV1(database_url).persist(assessment)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT q.request_id::text AS request_id,q.security_id::text AS security_id
                   FROM analytics.evidence_selection_request_v1 q
                   JOIN analytics.evidence_selector_policy_v1 p ON p.id=q.policy_id
                   WHERE q.security_id=(SELECT security_id FROM analytics.fv_current_assessment_v1
                     WHERE assessment_id=%s) AND p.domain='DAILY_PRICE'
                     AND p.field_code='CLOSE_PRICE'
                   ORDER BY q.decision_cutoff DESC LIMIT 1""",
                (persisted.assessment_id,),
            )
            price = cursor.fetchone()
    return {
        "assessmentId": persisted.assessment_id,
        "securityId": price["security_id"],
        "priceSelectionRequestId": price["request_id"],
        "ticker": "GOOG",
        "sleeve": "LONG_TERM_CORE",
        "providerNetworkRequests": "0",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    arguments = parser.parse_args()
    print(json.dumps(seed(arguments.database_url), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
