from pathlib import Path

import pytest

from equity_analysis.provider_validation.execution_safety import repository_root_env_path
from equity_analysis.provider_validation.sec_filing_evidence_cli import (
    CANARY_SYMBOLS,
    PHYSICAL_ATTEMPT_CEILING,
    build_preflight,
)


def test_preflight_is_bounded_and_contains_one_cache_missing_security(
    tmp_path: Path,
) -> None:
    preflight = build_preflight(
        run_id="20260727T000000Z-test",
        repository_root=tmp_path,
    )
    assert tuple(preflight["symbols"]) == CANARY_SYMBOLS
    assert {"AAPL", "CAT", "JNJ"} <= set(preflight["cacheMissingSymbols"])
    assert preflight["plannedPhysicalHttpAttempts"] == 29
    assert preflight["maximumPhysicalHttpAttempts"] == PHYSICAL_ATTEMPT_CEILING
    assert preflight["eodhdRequests"] == 0
    assert preflight["maximumRetries"] == 0


def test_preflight_rejects_more_than_five_or_duplicate_symbols(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="SEC_CANARY_SYMBOL_SET_INVALID"):
        build_preflight(
            run_id="run",
            repository_root=tmp_path,
            symbols=("A", "B", "C", "D", "E", "F"),
        )
    with pytest.raises(ValueError, match="SEC_CANARY_SYMBOL_SET_INVALID"):
        build_preflight(
            run_id="run",
            repository_root=tmp_path,
            symbols=("A", "A"),
        )


def test_preflight_refuses_existing_immutable_output(tmp_path: Path) -> None:
    run_id = "20260727T000000Z-test"
    path = tmp_path / "docs/generated" / f"sec-filing-evidence-{run_id}.json"
    path.parent.mkdir(parents=True)
    path.write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError, match="IMMUTABLE_OUTPUT_EXISTS"):
        build_preflight(run_id=run_id, repository_root=tmp_path)


def test_live_environment_path_uses_repository_root_not_calling_cwd() -> None:
    path = repository_root_env_path()
    assert path.name == ".env"
    assert path == Path(__file__).resolve().parents[2] / ".env"
    assert (path.parent / "analysis-python" / "pyproject.toml").is_file()
