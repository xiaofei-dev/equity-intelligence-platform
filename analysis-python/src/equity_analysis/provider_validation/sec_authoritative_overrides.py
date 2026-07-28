import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

REGISTRY_SCHEMA_VERSION = "sec-authoritative-ticker-overrides-v1.0.0"
DEFAULT_REGISTRY_PATH = Path(__file__).with_name(
    "sec_authoritative_ticker_overrides_v1.json"
)
_CIK_PATTERN = re.compile(r"^\d{10}$")
_HASH_PATTERN = re.compile(r"^[0-9A-F]{64}$")


@dataclass(frozen=True)
class SecAuthoritativeTickerOverride:
    ticker: str
    issuer_legal_name: str
    cik: str
    source_reference: str
    evidence_hash: str
    observed_at: datetime
    effective_at: datetime
    expires_at: datetime | None


def canonical_sec_ticker(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-").replace("/", "-")


def load_authoritative_ticker_overrides(
    path: Path = DEFAULT_REGISTRY_PATH,
    *,
    as_of: datetime | None = None,
) -> dict[str, SecAuthoritativeTickerOverride]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != REGISTRY_SCHEMA_VERSION:
        raise ValueError("Unsupported SEC authoritative override registry schema")
    evaluated_at = as_of or datetime.now(UTC)
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("SEC override evaluation time must include a timezone")

    overrides: dict[str, SecAuthoritativeTickerOverride] = {}
    for item in payload.get("overrides", ()):
        ticker = canonical_sec_ticker(str(item.get("ticker", "")))
        cik = str(item.get("cik", ""))
        source_reference = str(item.get("sourceReference", ""))
        parsed_source = urlparse(source_reference)
        evidence_hash = str(item.get("evidenceHash", "")).upper()
        issuer_name = str(item.get("issuerLegalName", "")).strip()
        observed_at = _parse_timestamp(item.get("observedAt"), "observedAt")
        effective_at = _parse_timestamp(item.get("effectiveAt"), "effectiveAt")
        expires_raw = item.get("expiresAt")
        expires_at = (
            _parse_timestamp(expires_raw, "expiresAt") if expires_raw is not None else None
        )

        if not ticker or not issuer_name:
            raise ValueError("SEC authoritative override requires ticker and issuer name")
        if not _CIK_PATTERN.fullmatch(cik):
            raise ValueError("SEC authoritative override CIK must contain ten digits")
        if parsed_source.scheme != "https" or not (
            parsed_source.hostname == "sec.gov"
            or parsed_source.hostname.endswith(".sec.gov")
        ):
            raise ValueError("SEC authoritative override requires an official SEC source")
        if not _HASH_PATTERN.fullmatch(evidence_hash):
            raise ValueError("SEC authoritative override requires a SHA-256 evidence hash")
        if effective_at > evaluated_at:
            raise ValueError("SEC authoritative override is not yet effective")
        if expires_at is not None and evaluated_at >= expires_at:
            raise ValueError("SEC authoritative override has expired")
        if ticker in overrides:
            raise ValueError(f"Duplicate SEC authoritative override for {ticker}")

        overrides[ticker] = SecAuthoritativeTickerOverride(
            ticker=ticker,
            issuer_legal_name=issuer_name,
            cik=cik,
            source_reference=source_reference,
            evidence_hash=evidence_hash,
            observed_at=observed_at,
            effective_at=effective_at,
            expires_at=expires_at,
        )
    return overrides


def _parse_timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"SEC authoritative override {field} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"SEC authoritative override {field} must include a timezone")
    return parsed.astimezone(UTC)
