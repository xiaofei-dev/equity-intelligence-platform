from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest

from equity_analysis.forward_validation.benchmark_input_refresh_v22 import (
    CAPTURE_ARTIFACT_RELATIVE_PATH,
    CONSTRUCTION_ARTIFACT_RELATIVE_PATH,
    COVERAGE_ARTIFACT_RELATIVE_PATH,
    STORAGE_RELATIVE_ROOT,
    build_capture_preflight,
    build_git_safe_artifacts,
    execute_capture,
    normalize_fundamentals_response,
    write_git_safe_artifacts,
)
from equity_analysis.forward_validation.preregistration_seal_v21 import (
    BENCHMARK_ARTIFACT_RELATIVE_PATH,
    LEGACY_DECISION_RELATIVE_PATH,
    PARENT_ARTIFACT_RELATIVE_PATH,
    SEAL_ARTIFACT_RELATIVE_PATH,
)
from equity_analysis.forward_validation.preregistration_seal_v22 import (
    BENCHMARK_PREREGISTRATION_ARTIFACT_RELATIVE_PATH,
    CANDIDATE_POLICY_ARTIFACT_RELATIVE_PATH,
    DATA_PREFLIGHT_ARTIFACT_RELATIVE_PATH,
    EXTERNAL_REFERENCE_ARTIFACT_RELATIVE_PATH,
    FEASIBILITY_ARTIFACT_RELATIVE_PATH,
    SEAL_ARTIFACT_V22_RELATIVE_PATH,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXED_NOW = datetime(2026, 7, 30, 4, 30, tzinfo=UTC)
CONTRACT_PATHS = (
    PARENT_ARTIFACT_RELATIVE_PATH,
    BENCHMARK_ARTIFACT_RELATIVE_PATH,
    SEAL_ARTIFACT_RELATIVE_PATH,
    LEGACY_DECISION_RELATIVE_PATH,
    FEASIBILITY_ARTIFACT_RELATIVE_PATH,
    CANDIDATE_POLICY_ARTIFACT_RELATIVE_PATH,
    EXTERNAL_REFERENCE_ARTIFACT_RELATIVE_PATH,
    DATA_PREFLIGHT_ARTIFACT_RELATIVE_PATH,
    BENCHMARK_PREREGISTRATION_ARTIFACT_RELATIVE_PATH,
    SEAL_ARTIFACT_V22_RELATIVE_PATH,
)


class _Response:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args) -> None:
        return None


class _FakeFundamentalsOpener:
    def __init__(self, *, invalid_at: int | None = None) -> None:
        self.calls = 0
        self.invalid_at = invalid_at

    def __call__(self, request, **_kwargs):
        self.calls += 1
        if self.invalid_at == self.calls:
            return _Response(b"[]")
        symbol = urlparse(request.full_url).path.rsplit("/", 1)[-1].split(".")[0]
        value = 100 + self.calls
        payload = {
            "General": {
                "Code": symbol,
                "CurrencyCode": "USD",
                "UpdatedAt": "2026-07-30",
            },
            "Highlights": {
                "EBITDA": str(value),
                "GrossProfitTTM": str(value * 2),
                "RevenueTTM": str(value * 4),
            },
            "Valuation": {"EnterpriseValue": str(value * 10)},
            "Financials": {
                "Balance_Sheet": {
                    "quarterly": {
                        "2026-06-30": {
                            "date": "2026-06-30",
                            "currency_symbol": "USD",
                        }
                    }
                }
            },
        }
        return _Response(json.dumps(payload).encode("utf-8"))


def _contract_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    for relative_path in CONTRACT_PATHS:
        source = REPOSITORY_ROOT / relative_path
        destination = repository / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return repository


def _response(
    *,
    ebitda: str = "-10",
    enterprise_value: str = "100",
    gross_profit: str = "-20",
    revenue: str = "200",
    updated_at: str = "2026-07-30",
    statement_currency: str = "USD",
) -> dict[str, object]:
    return {
        "General": {
            "Code": "TEST",
            "CurrencyCode": "USD",
            "UpdatedAt": updated_at,
        },
        "Highlights": {
            "EBITDA": ebitda,
            "GrossProfitTTM": gross_profit,
            "RevenueTTM": revenue,
        },
        "Valuation": {"EnterpriseValue": enterprise_value},
        "Financials": {
            "Balance_Sheet": {
                "quarterly": {
                    "2026-06-30": {
                        "date": "2026-06-30",
                        "currency_symbol": statement_currency,
                    }
                }
            }
        },
    }


def test_sealed_capture_preflight_is_exact_and_zero_retry(tmp_path: Path) -> None:
    repository = _contract_repository(tmp_path)
    preflight = build_capture_preflight(
        repository_root=repository,
        run_id="offline-preflight",
    )

    assert len(preflight["symbols"]) == 55
    assert len({row["symbol"] for row in preflight["symbols"]}) == 55
    assert preflight["physicalAttemptCeiling"] == 55
    assert preflight["configuredWeightCeiling"] == 550
    assert preflight["retryCount"] == 0
    assert preflight["unknownRequestMayReplay"] is False


def test_normalizer_keeps_negative_numerators_and_explicit_failures() -> None:
    normalized = normalize_fundamentals_response(
        symbol="TEST",
        public_security_id="test-id",
        response=_response(),
        source_response_content_hash=f"sha256:{'a' * 64}",
        retrieved_at=FIXED_NOW,
    )

    assert normalized["rules"]["PURE_VALUE"]["status"] == "VALID"
    assert normalized["rules"]["PURE_VALUE"]["score"].startswith("-")
    assert normalized["rules"]["PURE_QUALITY"]["status"] == "VALID"
    assert normalized["rules"]["PURE_QUALITY"]["score"].startswith("-")

    invalid = normalize_fundamentals_response(
        symbol="TEST",
        public_security_id="test-id",
        response=_response(enterprise_value="0"),
        source_response_content_hash=f"sha256:{'b' * 64}",
        retrieved_at=FIXED_NOW,
    )
    assert invalid["rules"]["PURE_VALUE"] == {
        "status": "INVALID",
        "reasonCodes": ["DENOMINATOR_NOT_POSITIVE"],
    }

    conflict = normalize_fundamentals_response(
        symbol="TEST",
        public_security_id="test-id",
        response=_response(statement_currency="EUR"),
        source_response_content_hash=f"sha256:{'c' * 64}",
        retrieved_at=FIXED_NOW,
    )
    assert conflict["rules"]["PURE_VALUE"]["status"] == "CONFLICT"
    assert conflict["rules"]["PURE_QUALITY"]["status"] == "VALID"

    stale = normalize_fundamentals_response(
        symbol="TEST",
        public_security_id="test-id",
        response=_response(updated_at="2025-01-01"),
        source_response_content_hash=f"sha256:{'d' * 64}",
        retrieved_at=FIXED_NOW,
    )
    assert stale["rules"]["PURE_VALUE"]["status"] == "STALE"
    assert stale["rules"]["PURE_QUALITY"]["status"] == "STALE"


def test_full_offline_fake_capture_is_bounded_and_git_safe(
    tmp_path: Path,
) -> None:
    repository = _contract_repository(tmp_path)
    opener = _FakeFundamentalsOpener()

    execution = execute_capture(
        repository_root=repository,
        api_key="test-key-not-written",
        run_id="offline-fake-run",
        opener=opener,
        now=lambda: FIXED_NOW,
    )
    capture, coverage, construction = build_git_safe_artifacts(execution)
    paths = write_git_safe_artifacts(
        repository_root=repository,
        capture=capture,
        coverage=coverage,
        construction=construction,
    )

    assert opener.calls == 55
    assert execution["physicalAttempts"] == 55
    assert execution["configuredWeight"] == 550
    assert execution["retryCount"] == 0
    assert execution["lockReleased"] is True
    assert not (repository / STORAGE_RELATIVE_ROOT / ".forward-benchmark-input-v2-2.lock").exists()
    assert coverage["pureValue"]["validCount"] == 55
    assert coverage["pureQuality"]["validCount"] == 55
    assert construction["pureValue"]["selectedCount"] == 11
    assert construction["pureQuality"]["selectedCount"] == 11
    assert tuple(paths) == (
        repository / CAPTURE_ARTIFACT_RELATIVE_PATH,
        repository / COVERAGE_ARTIFACT_RELATIVE_PATH,
        repository / CONSTRUCTION_ARTIFACT_RELATIVE_PATH,
    )
    rendered = json.dumps(
        {
            "capture": capture,
            "coverage": coverage,
            "construction": construction,
        },
        sort_keys=True,
    ).lower()
    assert '"value":' not in rendered
    assert '"score":' not in rendered
    assert "test-key-not-written" not in rendered
    assert len(
        tuple(
            (
                repository
                / STORAGE_RELATIVE_ROOT
                / "physical-request-journals"
                / "offline-fake-run"
                / "requests"
            ).rglob("*-COMPLETED.json")
        )
    ) == 55
    assert len(
        tuple(
            (
                repository
                / STORAGE_RELATIVE_ROOT
                / "normalized"
                / "offline-fake-run"
            ).rglob("*.json")
        )
    ) == 55

    with pytest.raises(ValueError, match="EODHD API key is required"):
        execute_capture(
            repository_root=repository,
            api_key="",
            run_id="no-key",
            opener=opener,
            now=lambda: FIXED_NOW,
        )
    with pytest.raises(
        RuntimeError,
        match="RUN_ID_ALREADY_EXISTS_AND_CANNOT_REPLAY",
    ):
        execute_capture(
            repository_root=repository,
            api_key="test-key-not-written",
            run_id="offline-fake-run",
            opener=opener,
            now=lambda: FIXED_NOW,
        )
    assert opener.calls == 55


def test_schema_anomaly_stops_without_retry_and_releases_lease(
    tmp_path: Path,
) -> None:
    repository = _contract_repository(tmp_path)
    opener = _FakeFundamentalsOpener(invalid_at=2)

    with pytest.raises(
        ValueError,
        match=r"RESPONSE_SCHEMA_OR_SEMANTIC_DRIFT\[ROOT\]",
    ):
        execute_capture(
            repository_root=repository,
            api_key="test-key-not-written",
            run_id="offline-failure-run",
            opener=opener,
            now=lambda: FIXED_NOW + timedelta(seconds=opener.calls),
        )

    assert opener.calls == 2
    assert not (
        repository
        / STORAGE_RELATIVE_ROOT
        / ".forward-benchmark-input-v2-2.lock"
    ).exists()
    run_events = tuple(
        (
            repository
            / STORAGE_RELATIVE_ROOT
            / "physical-request-journals"
            / "offline-failure-run"
            / "run"
        ).glob("*.json")
    )
    assert any("ABORTED" in path.name for path in run_events)
