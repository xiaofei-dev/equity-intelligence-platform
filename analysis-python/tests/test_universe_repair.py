from copy import deepcopy

import pytest

from equity_analysis.provider_validation.universe_repair import (
    build_repair_diff_artifact,
    is_valid_candidate,
    repair_slice_manifest_slot,
    repair_universe_slot,
    verify_deterministic_successor,
    verify_minimal_repair,
)


def _candidate(symbol: str, *, cik: str = "0000100493") -> dict[str, object]:
    return {
        "symbol": symbol,
        "securityName": f"{symbol} Inc.",
        "sector": "Consumer Staples",
        "subIndustry": "Packaged Foods & Meats",
        "cik": cik,
        "marketCapBand": "LARGE",
        "marketCapBandStatus": "PROVISIONAL",
        "candidateRole": "PRIMARY",
        "companyType": "MATURE_OPERATING_COMPANY",
        "selectionReason": "Frozen.",
        "sourceOrdinal": 1,
    }


def _universe() -> dict[str, object]:
    candidates = [_candidate(f"A{index:03d}") for index in range(299)]
    invalid = _candidate("Symbol", cik="0000000CIK")
    invalid["securityName"] = "Security"
    invalid["sector"] = "GICS Sector"
    invalid["subIndustry"] = "GICS Sub-Industry"
    candidates.insert(200, invalid)
    return {
        "universeVersion": "v1",
        "universeContentHash": "A" * 64,
        "source": {"sourceContentSha256": "B" * 64},
        "candidates": candidates,
    }


def _manifest(universe: dict[str, object]) -> dict[str, object]:
    candidates = universe["candidates"]
    return {
        "schemaVersion": "v1",
        "universeVersion": "v1",
        "universeContentHash": "A" * 64,
        "manifestContentHash": "C" * 64,
        "slices": [
            {
                "sliceId": f"slice-{index // 20 + 1:03d}",
                "symbols": [
                    item["symbol"] for item in candidates[index : index + 20]
                ],
                "symbolCount": len(candidates[index : index + 20]),
                "sectorDistribution": {},
                "marketCapDistribution": {},
                "roleDistribution": {},
            }
            for index in range(0, 300, 20)
        ],
    }


@pytest.mark.parametrize(
    ("candidate", "valid"),
    [
        (_candidate("TSN"), True),
        (_candidate("BRK-B"), True),
        (_candidate("Symbol"), False),
        (_candidate("TSN", cik="CIK"), False),
        ({**_candidate("TSN"), "sector": ""}, False),
    ],
)
def test_candidate_validation(candidate: dict[str, object], valid: bool) -> None:
    assert is_valid_candidate(candidate) is valid


def test_minimal_repair_preserves_299_records_and_slice_assignments() -> None:
    v1 = _universe()
    manifest_v1 = _manifest(v1)
    replacement = _candidate("TSN")
    replacement["securityName"] = "Tyson Foods"
    replacement["sourceOrdinal"] = 455

    v2, diff = repair_universe_slot(
        v1,
        replacement=replacement,
        universe_version="v2",
    )
    manifest_v2 = repair_slice_manifest_slot(
        manifest_v1,
        universe_v2=v2,
        removed_symbol="Symbol",
        added_symbol="TSN",
    )
    proof = verify_minimal_repair(v1, v2, manifest_v1, manifest_v2)

    assert diff["proof"]["unchangedCandidateRecords"] == 299
    assert diff["removed"][0]["symbol"] == "Symbol"
    assert diff["added"][0]["symbol"] == "TSN"
    assert proof == {
        "removedSymbol": "Symbol",
        "addedSymbol": "TSN",
        "unchangedCandidateRecords": 299,
        "unchangedSliceAssignments": 299,
        "replacementSlice": "slice-011",
        "replacementPosition": 0,
        "uniqueValidSecurities": 300,
        "verificationStatus": "PASS",
    }
    artifact = build_repair_diff_artifact(
        diff,
        proof,
        source_snapshot_sha256="B" * 64,
        base_manifest=manifest_v1,
        repaired_manifest=manifest_v2,
    )
    assert artifact["invariants"]["existingSliceAssignmentsChanged"] == 0
    assert artifact["sliceAssignmentProof"]["unchangedSliceAssignments"] == 299
    assert len(artifact["diffContentHash"]) == 64


def test_verifier_rejects_existing_candidate_or_slice_drift() -> None:
    v1 = _universe()
    manifest_v1 = _manifest(v1)
    v2, _ = repair_universe_slot(
        v1,
        replacement=_candidate("TSN"),
        universe_version="v2",
    )
    manifest_v2 = repair_slice_manifest_slot(
        manifest_v1,
        universe_v2=v2,
        removed_symbol="Symbol",
        added_symbol="TSN",
    )

    candidate_drift = deepcopy(v2)
    candidate_drift["candidates"][0]["sector"] = "Industrials"
    with pytest.raises(ValueError, match="candidate record"):
        verify_minimal_repair(v1, candidate_drift, manifest_v1, manifest_v2)

    slice_drift = deepcopy(manifest_v2)
    slice_drift["slices"][0]["symbols"][0], slice_drift["slices"][0]["symbols"][1] = (
        slice_drift["slices"][0]["symbols"][1],
        slice_drift["slices"][0]["symbols"][0],
    )
    with pytest.raises(ValueError, match="slice assignment"):
        verify_minimal_repair(v1, v2, manifest_v1, slice_drift)


def test_successor_proof_requires_first_unselected_frozen_order_candidate() -> None:
    ordered = [
        {"symbol": "AAPL", "sourceOrdinal": 1},
        {"symbol": "MSFT", "sourceOrdinal": 2},
        {"symbol": "TSN", "sourceOrdinal": 454},
        {"symbol": "MTD", "sourceOrdinal": 312},
    ]
    proof = verify_deterministic_successor(
        ordered,
        frozen_symbols={"AAPL", "MSFT"},
        replacement_symbol="TSN",
    )
    assert proof["replacementSymbol"] == "TSN"
    assert proof["replacementSourceOrdinal"] == 454

    with pytest.raises(ValueError, match="next eligible"):
        verify_deterministic_successor(
            ordered,
            frozen_symbols={"AAPL", "MSFT"},
            replacement_symbol="MTD",
        )
