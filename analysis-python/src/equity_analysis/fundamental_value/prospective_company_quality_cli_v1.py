from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from equity_analysis.fundamental_value.prospective_company_quality_v1 import (
    evaluate_offline_readiness,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate offline readiness for company-quality forward enrollment."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate_offline_readiness(
        calendar_last_session=date(2026, 7, 28),
        evidence_has_ingested_at=False,
        evidence_has_durable_identity=False,
        required_latest_completed_session=date(2026, 7, 31),
    )
    args.output.write_text(
        json.dumps(
            {
                "schemaVersion": "fv-cq-forward-enrollment-readiness-v1.0.0",
                "status": result.status,
                "reasons": list(result.reasons),
                "realEnrollmentWritten": result.real_enrollment_written,
                "stage8aContentHash": result.stage8a_content_hash,
                "networkAuthorized": False,
                "outcomesAccessed": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
