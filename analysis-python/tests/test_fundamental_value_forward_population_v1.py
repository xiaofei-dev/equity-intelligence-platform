from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.prospective_company_quality_population_v1 import (
    C5_IDENTITY_SET_HASH,
    C5_MEMBER_COUNT,
    C5_PRIVATE_SEAL_FILE_SHA256,
    DEFAULT_OUTPUT_PATH,
    KNOWN_US_ISIN_CUSIP_CONFLICT_COUNT,
    MIC_COUNTS,
    PopulationMetadataManifest,
    PopulationMetadataRow,
    PopulationMetadataViolation,
    SourceFileSeal,
    build_population_metadata_manifest,
    canonical_hash,
    cusip_checksum_valid,
    isin_checksum_valid,
    load_population_metadata_manifest,
    manifest_to_dict,
    seal_population_metadata_manifest,
    seal_population_metadata_row,
    to_acquisition_population_input_manifest,
    validate_population_metadata_manifest,
    write_population_metadata_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
C5_PRIVATE_SEAL = Path(
    r"C:\Users\simon\.codex\worktrees\e1a0\equity-intelligence-platform\storage\fundamental-value-historical-validation-v1\stage7c5-provider-native\sealed-predictors.json"
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


def _cusip(ordinal: int) -> str:
    base = f"{ordinal:08d}"
    total = 0
    for index, character in enumerate(base):
        number = int(character) * (2 if index % 2 == 1 else 1)
        total += number // 10 + number % 10
    return base + str((10 - total % 10) % 10)


def _isin(cusip: str) -> str:
    for check_digit in "0123456789":
        candidate = "US" + cusip + check_digit
        if isin_checksum_valid(candidate):
            return candidate
    raise AssertionError("Unable to construct an ISIN")


def _synthetic_manifest() -> PopulationMetadataManifest:
    rows: list[PopulationMetadataRow] = []
    for ordinal in range(1, C5_MEMBER_COUNT + 1):
        symbol = f"T{ordinal:06d}"
        source_hash = _sha(f"source-{ordinal}")
        provisional = PopulationMetadataRow(
            member_ordinal=ordinal,
            security_id=f"EODHD:{symbol}",
            symbol=symbol,
            mic="XNYS" if ordinal <= 122 else "XNAS",
            isin=_isin(_cusip(ordinal)),
            cusip=_cusip(ordinal),
            identifier_input_state="CHECKSUM_VALID_UNADJUDICATED",
            reason_codes=("OPENFIGI_AND_SEC_ADJUDICATION_REQUIRED",),
            c5_source_content_hash=source_hash,
            source_run_id=f"20260101T000000Z-{ordinal:012x}",
            source_request_identity=_sha(f"request-{ordinal}"),
            completion_event_hash=_sha(f"event-{ordinal}"),
            completion_event_file_sha256=_sha(f"event-file-{ordinal}"),
            completion_event_path=f"storage/test/events/{ordinal}.json",
            fundamentals_response_file_sha256=source_hash,
            fundamentals_response_path=f"storage/test/responses/{ordinal}.bin",
            row_content_hash="",
        )
        rows.append(seal_population_metadata_row(provisional))
    source_files = tuple(
        SourceFileSeal(
            source_kind=f"TEST_SOURCE_{ordinal}",
            logical_path=f"test/source-{ordinal}.json",
            file_sha256=_sha(f"file-{ordinal}"),
            canonical_content_hash=_sha(f"content-{ordinal}"),
        )
        for ordinal in range(1, 5)
    )
    identity_hash = canonical_hash(
        sorted(item.security_id for item in rows)
    )
    return seal_population_metadata_manifest(
        rows=tuple(rows),
        source_files=source_files,
        c5_identity_set_hash=identity_hash,
        test_only=True,
    )


@pytest.fixture(scope="module")
def actual_manifest() -> PopulationMetadataManifest:
    if not C5_PRIVATE_SEAL.exists():
        pytest.skip("The controlled C5 private seal is not present")
    return build_population_metadata_manifest(
        repo_root=REPO_ROOT,
        c5_private_seal_path=C5_PRIVATE_SEAL,
    )


def test_synthetic_manifest_round_trip_and_acquisition_projection() -> None:
    manifest = _synthetic_manifest()
    validate_population_metadata_manifest(manifest)
    acquisition = to_acquisition_population_input_manifest(manifest)

    assert len(manifest.rows) == 191
    assert dict(MIC_COUNTS) == {"XNAS": 69, "XNYS": 122}
    assert acquisition.test_only is True
    assert acquisition.c5_identity_set_hash == manifest.c5_identity_set_hash
    assert len(acquisition.rows) == 191
    assert manifest_to_dict(manifest)["financialNumericValuesIncluded"] is False


def test_identifier_checksums_and_row_state_fail_closed() -> None:
    manifest = _synthetic_manifest()
    first = manifest.rows[0]

    assert cusip_checksum_valid(first.cusip)
    assert isin_checksum_valid(first.isin)
    with pytest.raises(PopulationMetadataViolation, match="ISIN_CHECKSUM_INVALID"):
        seal_population_metadata_row(
            replace(
                first,
                isin=first.isin[:-1]
                + ("0" if first.isin[-1] != "0" else "1"),
                row_content_hash="",
            )
        )
    with pytest.raises(
        PopulationMetadataViolation, match="IDENTIFIER_INPUT_STATE_DRIFT"
    ):
        seal_population_metadata_row(
            replace(
                first,
                identifier_input_state="KNOWN_PROVIDER_IDENTIFIER_CONFLICT",
                row_content_hash="",
            )
        )


def test_manifest_tuple_hash_and_authority_boundaries_fail_closed() -> None:
    manifest = _synthetic_manifest()
    with pytest.raises(PopulationMetadataViolation, match="MEMBER_SET_INVALID"):
        validate_population_metadata_manifest(
            replace(manifest, rows=list(manifest.rows))  # type: ignore[arg-type]
        )
    with pytest.raises(
        PopulationMetadataViolation, match="POPULATION_AUTHORITY_BOUNDARY_DRIFT"
    ):
        validate_population_metadata_manifest(
            replace(manifest, network_authorized=True)
        )
    with pytest.raises(PopulationMetadataViolation, match="ROW_CONTENT_HASH_DRIFT"):
        tampered_hash = _sha("tampered-source")
        tampered = replace(
            manifest.rows[0],
            c5_source_content_hash=tampered_hash,
            fundamentals_response_file_sha256=tampered_hash,
        )
        validate_population_metadata_manifest(
            replace(manifest, rows=(tampered,) + manifest.rows[1:])
        )


def test_immutable_writer_accepts_only_exact_replay(tmp_path: Path) -> None:
    manifest = _synthetic_manifest()
    output = tmp_path / DEFAULT_OUTPUT_PATH.name

    first_hash, first_replay = write_population_metadata_manifest(manifest, output)
    second_hash, second_replay = write_population_metadata_manifest(manifest, output)

    assert first_hash == second_hash
    assert first_replay is False
    assert second_replay is True
    assert load_population_metadata_manifest(output) == manifest
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["state"] = "TAMPERED"
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(
        PopulationMetadataViolation, match="IMMUTABLE_MANIFEST_REPLAY_CONFLICT"
    ):
        write_population_metadata_manifest(manifest, output)


def test_persisted_manifest_unknown_fields_and_header_types_fail_closed(
    tmp_path: Path,
) -> None:
    manifest = _synthetic_manifest()
    output = tmp_path / "manifest.json"
    write_population_metadata_manifest(manifest, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["unknown"] = "not-accepted"
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(
        PopulationMetadataViolation, match="POPULATION_MANIFEST_SHAPE_DRIFT"
    ):
        load_population_metadata_manifest(output)


def test_actual_controlled_sources_produce_exact_191_row_manifest(
    actual_manifest: PopulationMetadataManifest,
) -> None:
    assert actual_manifest.test_only is False
    assert actual_manifest.c5_identity_set_hash == C5_IDENTITY_SET_HASH
    assert len(actual_manifest.rows) == 191
    assert Counter(item.mic for item in actual_manifest.rows) == {
        "XNYS": 122,
        "XNAS": 69,
    }
    assert (
        actual_manifest.known_us_isin_cusip_conflict_count
        == KNOWN_US_ISIN_CUSIP_CONFLICT_COUNT
    )
    assert actual_manifest.foreign_isin_namespace_count == 7
    assert actual_manifest.network_authorized is False
    assert actual_manifest.v24_enrollment_authorized is False
    assert actual_manifest.identity_acquisition_input_ready is True
    assert actual_manifest.source_files[0].file_sha256 == C5_PRIVATE_SEAL_FILE_SHA256
    assert all(isin_checksum_valid(item.isin) for item in actual_manifest.rows)
    assert all(cusip_checksum_valid(item.cusip) for item in actual_manifest.rows)


def test_actual_manifest_contains_no_financial_values_and_projects_exactly(
    actual_manifest: PopulationMetadataManifest,
) -> None:
    payload = manifest_to_dict(actual_manifest)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    acquisition = to_acquisition_population_input_manifest(actual_manifest)

    assert '"value":' not in encoded
    assert '"numericValue":' not in encoded
    assert '"revenue":' not in encoded
    assert acquisition.test_only is False
    assert acquisition.c5_identity_set_hash == C5_IDENTITY_SET_HASH
    assert len(acquisition.rows) == 191


def test_actual_builder_rejects_c5_file_hash_drift(tmp_path: Path) -> None:
    if not C5_PRIVATE_SEAL.exists():
        pytest.skip("The controlled C5 private seal is not present")
    copied = tmp_path / "sealed-predictors.json"
    copied.write_bytes(C5_PRIVATE_SEAL.read_bytes() + b"\n")

    with pytest.raises(
        PopulationMetadataViolation, match="C5_PRIVATE_SEAL_FILE_HASH_DRIFT"
    ):
        build_population_metadata_manifest(
            repo_root=REPO_ROOT,
            c5_private_seal_path=copied,
        )
