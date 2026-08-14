from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from equity_analysis.fundamental_value.current_assessment_persistence_v1 import (
    CurrentAssessmentPersistenceConflict,
    CurrentAssessmentRepositoryV1,
)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.parameters = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, parameters=None):
        self.sql = sql
        self.parameters = parameters

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


def _row(cutoff: datetime, *, assessment_id: str = "10000000-0000-4000-8000-000000000001"):
    return {
        "assessment_id": assessment_id,
        "security_id": "10000000-0000-4000-8000-000000000010",
        "symbol": "GOOG",
        "decision_cutoff": cutoff,
        "recorded_at": datetime(2026, 8, 12, 20, 1, tzinfo=UTC),
    }


def _repository(monkeypatch, rows):
    cursor = _Cursor(rows)
    repository = CurrentAssessmentRepositoryV1(
        "postgresql://local/test", connect=lambda *_args, **_kwargs: _Connection(cursor)
    )
    monkeypatch.setattr(repository, "_verify_producer_registry", lambda _cursor: None)
    top = rows[0] if rows else None
    record = None if top is None else SimpleNamespace(
        assessment_id=top["assessment_id"],
        recorded_at=top["recorded_at"],
        payload={
            "security_id": top["security_id"],
            "symbol": top["symbol"],
            "decision_cutoff": top["decision_cutoff"].isoformat().replace("+00:00", "Z"),
        },
    )
    monkeypatch.setattr(repository, "_load_by_id", lambda _cursor, _id: record)
    return repository, cursor, record


def test_latest_symbol_uses_deterministic_cutoff_recorded_identity_order(monkeypatch):
    latest = datetime(2026, 8, 12, 20, tzinfo=UTC)
    repository, cursor, record = _repository(
        monkeypatch,
        [
            _row(latest),
            _row(
                datetime(2026, 8, 11, 20, tzinfo=UTC),
                assessment_id="10000000-0000-4000-8000-000000000002",
            ),
        ],
    )
    assert repository.load_latest_for_symbol("GOOG") is record
    assert "ORDER BY decision_cutoff DESC,recorded_at DESC,assessment_id" in cursor.sql
    assert "LIMIT 2" in cursor.sql
    assert cursor.parameters == ("GOOG",)


def test_latest_symbol_rejects_top_cutoff_ties_and_readback_drift(monkeypatch):
    cutoff = datetime(2026, 8, 12, 20, tzinfo=UTC)
    repository, _, _ = _repository(
        monkeypatch,
        [_row(cutoff), _row(cutoff, assessment_id="10000000-0000-4000-8000-000000000002")],
    )
    with pytest.raises(
        CurrentAssessmentPersistenceConflict,
        match="CURRENT_ASSESSMENT_LATEST_DECISION_TIE",
    ):
        repository.load_latest_for_symbol("GOOG")

    repository, _, record = _repository(monkeypatch, [_row(cutoff)])
    record.payload["symbol"] = "FOX"
    with pytest.raises(
        CurrentAssessmentPersistenceConflict,
        match="CURRENT_ASSESSMENT_LATEST_READBACK_DRIFT",
    ):
        repository.load_latest_for_symbol("GOOG")
