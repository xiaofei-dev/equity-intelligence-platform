from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from equity_analysis.daily_refresh.persistence import PostgresRefreshPersistence
from equity_analysis.market_data.eodhd import EodhdProvider
from equity_analysis.provider_validation.expansion_gate import canonical_hash

REPLAY_SCHEMA_VERSION = "cached-fundamentals-replay-v1.0.0"
JOURNAL_RELATIVE_ROOT = Path(
    "storage/provider-validation/scoring-inputs-v2/physical-request-journals"
)


@dataclass(frozen=True)
class CachedFundamentalsEvidence:
    symbol: str
    retrieved_at: datetime
    response_content_hash: str
    response_storage_reference: str
    completed_event_path: Path


@dataclass(frozen=True)
class CachedFundamentalsReplayResult:
    source_snapshot_id: UUID
    requested_symbol_count: int
    replayed_symbols: tuple[str, ...]
    missing_symbols: tuple[str, ...]
    rows_written: int
    rows_rejected: int
    ingestion_batch_ids: tuple[UUID, ...]
    network_requests_executed: int = 0
    schema_version: str = REPLAY_SCHEMA_VERSION


def _verify_event(path: Path) -> dict[str, Any]:
    event = json.loads(path.read_text(encoding="utf-8"))
    expected = event.get("eventHash")
    actual = canonical_hash(
        {key: value for key, value in event.items() if key != "eventHash"}
    )
    if expected != actual:
        raise ValueError(f"CACHE_EVENT_HASH_MISMATCH[{path}]")
    return event


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Cached request time must include a timezone")
    return parsed.astimezone(UTC)


def _resolve_storage_path(repository_root: Path, storage_reference: str) -> Path:
    candidate = (repository_root / storage_reference).resolve()
    journal_root = (repository_root / JOURNAL_RELATIVE_ROOT).resolve()
    if candidate != journal_root and journal_root not in candidate.parents:
        raise ValueError("Cached response is outside the approved journal root")
    return candidate


def discover_cached_fundamentals(
    *,
    repository_root: Path,
    symbols: set[str],
    cutoff: datetime | None = None,
) -> dict[str, CachedFundamentalsEvidence]:
    normalized_symbols = {symbol.strip().upper() for symbol in symbols}
    journal_root = repository_root / JOURNAL_RELATIVE_ROOT
    selected: dict[str, CachedFundamentalsEvidence] = {}
    for completed_path in sorted(journal_root.rglob("*-COMPLETED.json")):
        completed = _verify_event(completed_path)
        detail = completed.get("detail", {})
        symbol = str(completed.get("symbol", "")).strip().upper()
        if (
            completed.get("state") != "COMPLETED"
            or detail.get("endpointCategory") != "fundamentals"
            or symbol not in normalized_symbols
        ):
            continue
        if int(detail.get("status", 0)) != 200:
            raise ValueError(f"CACHE_RESPONSE_NOT_SUCCESSFUL[{completed_path}]")
        intents = sorted(completed_path.parent.glob("*-INTENT.json"))
        if len(intents) != 1:
            raise ValueError(f"CACHE_INTENT_NOT_UNIQUE[{completed_path}]")
        intent = _verify_event(intents[0])
        if intent.get("requestIdentity") != completed.get("requestIdentity"):
            raise ValueError(f"CACHE_REQUEST_IDENTITY_MISMATCH[{completed_path}]")
        if intent.get("detail", {}).get("endpointCategory") != "fundamentals":
            raise ValueError(f"CACHE_ENDPOINT_MISMATCH[{completed_path}]")
        retrieved_at = _as_utc(str(intent["detail"]["startedAt"])) + timedelta(
            milliseconds=int(detail.get("durationMs", 0)) + 1
        )
        if cutoff is not None and retrieved_at > cutoff:
            continue
        storage_reference = str(detail["responseCheckpointPath"]).replace("\\", "/")
        response_path = _resolve_storage_path(repository_root, storage_reference)
        raw = response_path.read_bytes()
        response_hash = str(detail["responseContentHash"]).upper()
        if sha256(raw).hexdigest().upper() != response_hash:
            raise ValueError(f"CACHE_RESPONSE_HASH_MISMATCH[{response_path}]")
        candidate = CachedFundamentalsEvidence(
            symbol=symbol,
            retrieved_at=retrieved_at,
            response_content_hash=response_hash,
            response_storage_reference=storage_reference,
            completed_event_path=completed_path,
        )
        current = selected.get(symbol)
        if current is None or candidate.retrieved_at > current.retrieved_at:
            selected[symbol] = candidate
    return selected


def load_cached_fundamentals_payload(
    *,
    repository_root: Path,
    evidence: CachedFundamentalsEvidence,
) -> dict[str, Any]:
    response_path = _resolve_storage_path(
        repository_root, evidence.response_storage_reference
    )
    raw = response_path.read_bytes()
    if sha256(raw).hexdigest().upper() != evidence.response_content_hash:
        raise ValueError(f"CACHE_RESPONSE_HASH_MISMATCH[{response_path}]")
    if raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)
    payload = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    if not isinstance(payload, dict):
        raise ValueError(f"CACHED_FUNDAMENTALS_NOT_OBJECT[{evidence.symbol}]")
    return payload


def replay_cached_current_fundamentals(
    *,
    database_url: str,
    repository_root: Path,
    source_snapshot_id: UUID,
    persistence: PostgresRefreshPersistence,
    cutoff: datetime | None = None,
) -> CachedFundamentalsReplayResult:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT member.symbol_at_snapshot, security.public_id
            FROM analytics.snapshot_universe_member member
            JOIN analytics.security security ON security.id = member.security_id
            WHERE member.snapshot_id = %s
              AND member.membership_status = 'INCLUDED'
            ORDER BY member.symbol_at_snapshot
            """,
            (source_snapshot_id,),
        ).fetchall()
    if not rows:
        raise ValueError("Source snapshot has no included securities")

    identities = {str(row[0]).upper(): row[1] for row in rows}
    evidence_by_symbol = discover_cached_fundamentals(
        repository_root=repository_root,
        symbols=set(identities),
        cutoff=cutoff,
    )
    provider = EodhdProvider(
        api_key="offline-cached-replay",
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Cached fundamentals replay must not use the network")
        ),
        max_retries=0,
    )
    replayed: list[str] = []
    batches: list[UUID] = []
    rows_written = 0
    rows_rejected = 0
    for symbol in sorted(evidence_by_symbol):
        evidence = evidence_by_symbol[symbol]
        payload = load_cached_fundamentals_payload(
            repository_root=repository_root,
            evidence=evidence,
        )
        envelope = provider.parse_fundamentals_payload(
            symbol=symbol,
            payload=payload,
            content_hash=f"sha256:{evidence.response_content_hash.lower()}",
            retrieved_at=evidence.retrieved_at,
            source_reference=(
                f"eodhd:fundamentals:{provider.map_symbol(symbol)}:"
                f"cached-profile-replay-v1:{evidence.response_content_hash}"
            ),
        )
        write = persistence.write_current_fundamentals_projection(
            str(identities[symbol]),
            envelope,
            storage_reference=evidence.response_storage_reference,
        )
        replayed.append(symbol)
        batches.append(write.ingestion_batch_id)
        rows_written += write.rows_written
        rows_rejected += write.rows_rejected

    missing = tuple(sorted(set(identities) - set(evidence_by_symbol)))
    return CachedFundamentalsReplayResult(
        source_snapshot_id=source_snapshot_id,
        requested_symbol_count=len(identities),
        replayed_symbols=tuple(replayed),
        missing_symbols=missing,
        rows_written=rows_written,
        rows_rejected=rows_rejected,
        ingestion_batch_ids=tuple(sorted(set(batches), key=str)),
    )
