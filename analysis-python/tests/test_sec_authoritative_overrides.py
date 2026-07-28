import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from equity_analysis.provider_validation.sec_authoritative_overrides import (
    REGISTRY_SCHEMA_VERSION,
    canonical_sec_ticker,
    load_authoritative_ticker_overrides,
)


def _write_registry(path: Path, override: dict) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": REGISTRY_SCHEMA_VERSION,
                "overrides": [override],
            }
        ),
        encoding="utf-8",
    )


def _valid_override() -> dict:
    return {
        "ticker": "BRK.B",
        "issuerLegalName": "Example Corporation",
        "cik": "0000000001",
        "sourceReference": "https://www.sec.gov/Archives/example.htm",
        "evidenceHash": "A" * 64,
        "observedAt": "2026-07-26T00:00:00Z",
        "effectiveAt": "2025-01-01T00:00:00Z",
        "expiresAt": None,
    }


def test_ticker_normalization_supports_sec_special_tickers() -> None:
    assert canonical_sec_ticker(" brk.b ") == "BRK-B"
    assert canonical_sec_ticker("brk/b") == "BRK-B"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("cik", "57515", "ten digits"),
        ("cik", "000005751X", "ten digits"),
        ("sourceReference", "", "official SEC source"),
        (
            "sourceReference",
            "https://example.com/evidence",
            "official SEC source",
        ),
        ("evidenceHash", "", "SHA-256 evidence hash"),
    ),
)
def test_registry_rejects_missing_or_invalid_authority(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    override = _valid_override()
    override[field] = value
    registry = tmp_path / "registry.json"
    _write_registry(registry, override)

    with pytest.raises(ValueError, match=message):
        load_authoritative_ticker_overrides(
            registry,
            as_of=datetime(2026, 7, 27, tzinfo=UTC),
        )


def test_registry_rejects_expired_override(tmp_path: Path) -> None:
    override = _valid_override()
    override["expiresAt"] = "2026-07-26T00:00:00Z"
    registry = tmp_path / "registry.json"
    _write_registry(registry, override)

    with pytest.raises(ValueError, match="expired"):
        load_authoritative_ticker_overrides(
            registry,
            as_of=datetime(2026, 7, 27, tzinfo=UTC),
        )
