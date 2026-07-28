from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    new_run_id,
    write_immutable_json,
)
from equity_analysis.provider_validation.interest_consistency_audit_v1 import (
    build_interest_consistency_audit,
)
from equity_analysis.provider_validation.issuer_interest_evidence_cli import (
    CANARY_SYMBOLS,
    _response_body_from_event,
)
from equity_analysis.provider_validation.objective_rating_semantics_audit import (
    _verify_event,
)
from equity_analysis.provider_validation.sec_filing_evidence import (
    SEC_FILING_EVIDENCE_SCHEMA_VERSION,
    SEC_INLINE_XBRL_PARSER_VERSION,
    build_filing_evidence,
)

REPLAY_SCHEMA_VERSION = "sec-issuer-interest-evidence-offline-replay-v1.0.0"
SOURCE_RUN_ID = "20260728T051809Z-ff6c07bd66ff"


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def _payload_hash(payload: dict[str, Any], field: str) -> str:
    return canonical_hash({key: value for key, value in payload.items() if key != field})


def _completed_events_by_response_hash(
    repository_root: Path,
    source_run_id: str,
) -> dict[str, dict[str, Any]]:
    root = (
        repository_root
        / "storage/provider-validation/sec-issuer-interest-evidence/"
        "physical-request-journals"
        / source_run_id
    )
    if not root.is_dir():
        raise ValueError("ISSUER_INTEREST_SOURCE_JOURNAL_MISSING")
    events = {}
    completed_count = 0
    for path in sorted(root.rglob("*-COMPLETED.json")):
        event = _verify_event(path)
        completed_count += 1
        decoded = _response_body_from_event(event, repository_root=repository_root)
        for response_hash in (
            event["detail"]["responseContentHash"],
            sha256(decoded).hexdigest().upper(),
        ):
            existing = events.get(response_hash)
            if existing is not None and existing["requestIdentity"] != event[
                "requestIdentity"
            ]:
                existing_body = _response_body_from_event(
                    existing,
                    repository_root=repository_root,
                )
                if existing_body != decoded:
                    raise ValueError(
                        f"ISSUER_INTEREST_RESPONSE_HASH_COLLISION[{response_hash}]"
                    )
            events[response_hash] = event
    if completed_count != 72:
        raise ValueError("ISSUER_INTEREST_SOURCE_COMPLETED_COUNT_NOT_72")
    return events


def _body_for_category(
    *,
    category: str,
    source_hashes: dict[str, str],
    completed: dict[str, dict[str, Any]],
    symbol: str,
    accession: str,
    repository_root: Path,
) -> bytes:
    response_hash = source_hashes[category]
    event = completed.get(response_hash)
    if event is None:
        raise ValueError(
            f"ISSUER_INTEREST_SOURCE_RESPONSE_MISSING[{symbol}:{accession}:{category}]"
        )
    return _response_body_from_event(event, repository_root=repository_root)


def rebuild_canary_evidence_offline(
    *,
    repository_root: Path,
    source_run_id: str,
    replay_run_id: str,
    output_path: Path,
) -> dict[str, Any]:
    report_path = (
        repository_root
        / f"docs/generated/sec-issuer-interest-evidence-{source_run_id}.json"
    )
    preflight_path = (
        repository_root
        / f"docs/generated/sec-issuer-interest-evidence-{source_run_id}-preflight.json"
    )
    source_report = json.loads(report_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if source_report["runId"] != source_run_id or preflight["runId"] != source_run_id:
        raise ValueError("ISSUER_INTEREST_SOURCE_RUN_ID_MISMATCH")
    if _payload_hash(source_report, "artifactContentHash") != source_report[
        "artifactContentHash"
    ]:
        raise ValueError("ISSUER_INTEREST_SOURCE_REPORT_HASH_MISMATCH")
    if _payload_hash(preflight, "contentHash") != preflight["contentHash"]:
        raise ValueError("ISSUER_INTEREST_SOURCE_PREFLIGHT_HASH_MISMATCH")
    if tuple(source_report["symbols"]) != CANARY_SYMBOLS:
        raise ValueError("ISSUER_INTEREST_SOURCE_SYMBOL_SET_DRIFT")

    completed = _completed_events_by_response_hash(repository_root, source_run_id)
    preflight_by_key = {
        (entry["symbol"], entry["accession"]): entry
        for entry in preflight["entries"]
    }
    evidence_root = (
        repository_root
        / "storage/provider-validation/scoring-inputs-v4/filing-evidence"
    )
    records = []
    concept_counts: Counter[str] = Counter()
    for source_record in source_report["records"]:
        symbol = source_record["symbol"]
        accession = source_record["accession"]
        entry = preflight_by_key[(symbol, accession)]
        old_path = repository_root / source_record["evidencePath"]
        old_payload = json.loads(old_path.read_text(encoding="utf-8"))
        if _payload_hash(old_payload, "contentHash") != old_payload["contentHash"]:
            raise ValueError(
                f"ISSUER_INTEREST_SOURCE_EVIDENCE_HASH_MISMATCH[{symbol}:{accession}]"
            )
        source_hashes = source_record["sourceHashes"]

        evidence = build_filing_evidence(
            symbol=symbol,
            cik=entry["cik"],
            filing=entry["filing"],
            source_references=old_payload["sourceReferences"],
            source_hashes=old_payload["sourceHashes"],
            inline_document=_body_for_category(
                category="filing",
                source_hashes=source_hashes,
                completed=completed,
                symbol=symbol,
                accession=accession,
                repository_root=repository_root,
            ),
            presentation_document=_body_for_category(
                category="presentation",
                source_hashes=source_hashes,
                completed=completed,
                symbol=symbol,
                accession=accession,
                repository_root=repository_root,
            ),
            label_document=_body_for_category(
                category="labels",
                source_hashes=source_hashes,
                completed=completed,
                symbol=symbol,
                accession=accession,
                repository_root=repository_root,
            ),
            ingested_at=old_payload["ingestedAt"],
        )
        path = evidence_root / symbol / f"{evidence['contentHash']}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if (
                _payload_hash(existing, "contentHash")
                != evidence["contentHash"]
                or existing != evidence
            ):
                raise ValueError(
                    f"ISSUER_INTEREST_REBUILT_EVIDENCE_COLLISION[{symbol}:{accession}]"
                )
        else:
            write_immutable_json(path, evidence)
        concepts = sorted(
            {item["concept"] for item in evidence["interestEvidence"]}
        )
        concept_counts.update(concepts)
        concept_evidence = [
            {
                "concept": item["concept"],
                "contextRef": item["contextRef"],
                "periodStart": item["context"].get("periodStart"),
                "periodEnd": item["context"].get("periodEnd"),
                "dimensions": item["context"].get("dimensions", []),
                "unitRef": item.get("unitRef"),
                "nil": item["nil"],
                "statementRoles": sorted(
                    {
                        row["statementRole"]
                        for row in item["presentation"]
                        if row.get("statementRole")
                    }
                ),
                "presentationLabels": sorted(
                    {
                        row["presentationLabel"]
                        for row in item["presentation"]
                        if row.get("presentationLabel")
                    }
                ),
                "scopeStatus": item["scope"]["status"],
                "calculationEvidenceStatus": item[
                    "calculationEvidenceStatus"
                ],
            }
            for item in evidence["interestEvidence"]
        ]
        records.append(
            {
                "symbol": symbol,
                "accession": accession,
                "sourceEvidencePath": source_record["evidencePath"],
                "sourceEvidenceContentHash": source_record[
                    "evidenceContentHash"
                ],
                "rebuiltEvidencePath": path.relative_to(
                    repository_root
                ).as_posix(),
                "rebuiltEvidenceContentHash": evidence["contentHash"],
                "interestConcepts": concepts,
                "interestEvidenceCount": len(evidence["interestEvidence"]),
                "interestEvidence": concept_evidence,
                "sourceResponseHashes": {
                    key: source_hashes[key]
                    for key in (
                        "filingIndex",
                        "filing",
                        "presentation",
                        "labels",
                    )
                },
                "calculationEvidenceStatus": (
                    "NOT_COLLECTED_NOT_IN_APPROVED_ENDPOINT_SET"
                ),
            }
        )

    artifact = {
        "artifactType": "SEC_ISSUER_INTEREST_EVIDENCE_OFFLINE_REPLAY",
        "schemaVersion": REPLAY_SCHEMA_VERSION,
        "runId": replay_run_id,
        "sourceLiveRunId": source_run_id,
        "sourceReportPath": report_path.relative_to(repository_root).as_posix(),
        "sourceReportSha256": _file_sha256(report_path),
        "sourceReportContentHash": source_report["artifactContentHash"],
        "sourcePreflightPath": preflight_path.relative_to(
            repository_root
        ).as_posix(),
        "sourcePreflightSha256": _file_sha256(preflight_path),
        "symbols": list(CANARY_SYMBOLS),
        "accessionCount": len(records),
        "parserVersion": SEC_INLINE_XBRL_PARSER_VERSION,
        "evidenceSchemaVersion": SEC_FILING_EVIDENCE_SCHEMA_VERSION,
        "records": records,
        "interestConceptAccessionCounts": dict(sorted(concept_counts.items())),
        "physicalHttpAttempts": 0,
        "eodhdRequests": 0,
        "secRequests": 0,
        "rawSecValuesIncluded": False,
        "scoresOrRanksIncluded": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    write_immutable_json(output_path, artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild the bounded issuer-interest evidence canary from "
            "hash-verified response journals without network access."
        )
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd().parent)
    parser.add_argument("--source-run-id", default=SOURCE_RUN_ID)
    args = parser.parse_args()
    root = args.repository_root.resolve()
    run_id = new_run_id(datetime.now(UTC))
    replay_path = (
        root
        / f"docs/generated/sec-issuer-interest-evidence-{run_id}-offline-replay.json"
    )
    replay = rebuild_canary_evidence_offline(
        repository_root=root,
        source_run_id=args.source_run_id,
        replay_run_id=run_id,
        output_path=replay_path,
    )
    audit_path = (
        root
        / f"docs/generated/sec-issuer-interest-consistency-{run_id}-canary.json"
    )
    audit = build_interest_consistency_audit(
        repository_root=root,
        aggregate_path=root
        / "docs/generated/formula-ready-243-final-aggregate-v1.json",
        supplement_manifest_path=root
        / "docs/generated/objective-rating-v1-current-snapshot-supplements-v3.json",
        factor_manifest_path=root
        / "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-4.json",
        output_path=audit_path,
        supplement_storage_root=root
        / "storage/provider-validation/current-interest-supplements-v1",
        symbols=CANARY_SYMBOLS,
    )
    print(
        json.dumps(
            {
                "runId": run_id,
                "replayPath": replay_path.relative_to(root).as_posix(),
                "replayContentHash": replay["artifactContentHash"],
                "auditPath": audit_path.relative_to(root).as_posix(),
                "auditContentHash": audit["artifactContentHash"],
                "statusCounts": audit["statusCounts"],
                "qcInputReadyCount": audit["qcInputReadyCount"],
                "networkRequestsExecuted": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
