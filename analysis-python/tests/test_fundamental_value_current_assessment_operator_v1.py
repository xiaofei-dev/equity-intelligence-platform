from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_fundamental_value_current_assessment_v1 import (
    _FakeEodhdTransport,
    _FakeEvidenceRegistrar,
)

from equity_analysis.fundamental_value.current_assessment_execution_v1 import (
    build_current_assessment_execution_plan_v1,
    execute_current_assessment_v1,
)
from equity_analysis.fundamental_value.current_assessment_operator_v1 import (
    CurrentAssessmentOperatorStop,
    CurrentAssessmentReceiptSetV1,
    replay_and_persist_current_assessments_v1,
)
from equity_analysis.fundamental_value.current_fundamentals_execution_v1 import (
    build_current_fundamentals_plan_v1,
    execute_current_fundamentals_v1,
)
from equity_analysis.fundamental_value.identity_projection_v2 import (
    load_accepted_identity_projection_v2,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    TransportResponse,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
STAGE8C_STORAGE = (
    REPOSITORY_ROOT
    / "storage/fundamental-value-forward-enrollment-v1/stage8c"
)
CURRENT_RECEIPT_STORAGE = (
    REPOSITORY_ROOT / "storage/fundamental-value-current-assessment-v1"
)


@pytest.fixture(scope="module")
def accepted_projection():
    marker = STAGE8C_STORAGE / ".fv-stage8c-private-storage.json"
    if not marker.is_file():
        pytest.skip("accepted private Stage 8C storage is not available")
    return load_accepted_identity_projection_v2(
        repository_root=REPOSITORY_ROOT,
        storage_root=STAGE8C_STORAGE,
    )


@dataclass(frozen=True)
class _Persisted:
    assessment_id: str
    assessment_content_hash: str


class _Recorder:
    def __init__(self) -> None:
        self.items = []

    def persist(self, value):
        self.items.append(value)
        return _Persisted(
            assessment_id=value.security_id,
            assessment_content_hash=value.content_hash,
        )


class _PriceTransport:
    def send(self, request):
        return TransportResponse(
            200,
            (("date", "Wed, 12 Aug 2026 17:22:26 GMT"),),
            json.dumps(
                [
                    {
                        "date": "2026-08-11",
                        "open": 19.0,
                        "high": 21.0,
                        "low": 18.0,
                        "close": 20.0,
                        "adjusted_close": 20.0,
                        "volume": 1_000_000,
                    }
                ]
            ).encode("utf-8"),
        )


def _prepare_receipts(tmp_path: Path, projection):
    fundamentals_plan = build_current_fundamentals_plan_v1(
        run_id="FV-CURRENT-OPERATOR-FUNDAMENTALS-001",
        preflight_sealed_at=datetime(2026, 8, 12, 17, 20, tzinfo=UTC),
        identity_projection_content_hash=projection.content_hash,
        identities=projection.members,
        network_authorized=True,
    )
    fundamentals_run = execute_current_fundamentals_v1(
        fundamentals_plan,
        storage_root=tmp_path,
        transport=_FakeEodhdTransport(),
        sealed_at=datetime(2026, 8, 12, 17, 23, tzinfo=UTC),
    )
    fundamentals = {
        capture.symbol: (capture.raw, capture.payload, capture.source_seal)
        for capture in fundamentals_run.captures
    }
    price_plan = build_current_assessment_execution_plan_v1(
        run_id="FV-CURRENT-OPERATOR-PRICE-001",
        preflight_sealed_at=datetime(2026, 8, 12, 17, 22, 25, tzinfo=UTC),
        identity_projection_content_hash=projection.content_hash,
        identities=projection.members,
        network_authorized=True,
        price_provider="EODHD_EOD",
    )
    execute_current_assessment_v1(
        price_plan,
        identities=projection.members,
        evidence_registrar=_FakeEvidenceRegistrar(),
        fundamentals=fundamentals,
        storage_root=tmp_path,
        transport=_PriceTransport(),
        sealed_at=datetime(2026, 8, 12, 17, 23, tzinfo=UTC),
    )
    return fundamentals_plan, price_plan


def test_offline_operator_rebuilds_from_receipts_and_ignores_old_assessments(
    tmp_path: Path, accepted_projection
) -> None:
    fundamentals_plan, price_plan = _prepare_receipts(tmp_path, accepted_projection)
    old_assessment_root = tmp_path / price_plan.run_id / "assessments"
    for path in old_assessment_root.glob("*.json"):
        path.unlink()
    old_assessment_root.rmdir()
    recorder = _Recorder()

    result = replay_and_persist_current_assessments_v1(
        storage_root=tmp_path,
        receipt_set=CurrentAssessmentReceiptSetV1(
            identity_projection_content_hash=accepted_projection.content_hash,
            fundamentals_run_id=fundamentals_plan.run_id,
            fundamentals_plan_hash=fundamentals_plan.plan_hash,
            price_run_id=price_plan.run_id,
            price_plan_hash=price_plan.plan_hash,
        ),
        projection=accepted_projection,
        decision_cutoff=datetime(2026, 8, 12, 17, 23, tzinfo=UTC),
        evidence_registrar=_FakeEvidenceRegistrar(),
        assessment_persister=recorder,
    )

    assert result.assessment_ids == tuple(
        member.security_id for member in accepted_projection.members
    )
    assert result.assessment_content_hashes == tuple(
        item.content_hash for item in recorder.items
    )
    assert tuple(item.symbol for item in recorder.items) == ("GOOG", "FOX", "MSFT")


def test_offline_operator_rejects_manifest_or_receipt_drift(
    tmp_path: Path, accepted_projection
) -> None:
    fundamentals_plan, price_plan = _prepare_receipts(tmp_path, accepted_projection)
    manifest_path = tmp_path / price_plan.run_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["physicalRequests"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CurrentAssessmentOperatorStop, match="RECEIPT_MANIFEST_HASH_DRIFT"):
        replay_and_persist_current_assessments_v1(
            storage_root=tmp_path,
            receipt_set=CurrentAssessmentReceiptSetV1(
                identity_projection_content_hash=accepted_projection.content_hash,
                fundamentals_run_id=fundamentals_plan.run_id,
                fundamentals_plan_hash=fundamentals_plan.plan_hash,
                price_run_id=price_plan.run_id,
                price_plan_hash=price_plan.plan_hash,
            ),
            projection=accepted_projection,
            decision_cutoff=datetime(2026, 8, 12, 17, 23, tzinfo=UTC),
            evidence_registrar=_FakeEvidenceRegistrar(),
            assessment_persister=_Recorder(),
        )


def test_actual_private_receipts_replay_without_exposing_values(
    accepted_projection,
) -> None:
    fundamentals_run = "FV-CURRENT-FUNDAMENTALS-20260812T171713Z-001"
    price_run = "FV-CURRENT-EODHD-PRICES-20260812T172225Z-001"
    if not (CURRENT_RECEIPT_STORAGE / fundamentals_run / "manifest.json").is_file():
        pytest.skip("accepted private current-assessment receipts are unavailable")
    recorder = _Recorder()
    result = replay_and_persist_current_assessments_v1(
        storage_root=CURRENT_RECEIPT_STORAGE,
        receipt_set=CurrentAssessmentReceiptSetV1(
            identity_projection_content_hash=accepted_projection.content_hash,
            fundamentals_run_id=fundamentals_run,
            fundamentals_plan_hash=(
                "FCC98952243C4F04E8212A2AB892C2B663D7E2CF6D4B83145751BA754B1F4B49"
            ),
            price_run_id=price_run,
            price_plan_hash=(
                "13E42141EAE19618102CC24F4164629CB9FA0F06FFAA94236E573E97BCE61896"
            ),
        ),
        projection=accepted_projection,
        decision_cutoff=datetime(2026, 8, 12, 17, 23, tzinfo=UTC),
        evidence_registrar=_FakeEvidenceRegistrar(),
        assessment_persister=recorder,
    )
    assert tuple(item.symbol for item in recorder.items) == ("GOOG", "FOX", "MSFT")
    assert len(result.assessment_ids) == 3
    assert len(set(result.assessment_content_hashes)) == 3
