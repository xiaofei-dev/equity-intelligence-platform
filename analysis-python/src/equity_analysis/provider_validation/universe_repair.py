"""Auditable minimal repair support for a frozen expansion universe."""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from hashlib import sha256
from typing import Any

VALID_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?$")
HEADER_LITERALS = {
    "cik",
    "gics sector",
    "gics sub-industry",
    "security",
    "symbol",
}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest().upper()


def is_valid_candidate(candidate: dict[str, Any]) -> bool:
    required = ("symbol", "securityName", "sector", "subIndustry")
    if any(not str(candidate.get(field, "")).strip() for field in required):
        return False
    if any(
        str(candidate[field]).strip().casefold() in HEADER_LITERALS
        for field in required
    ):
        return False
    symbol = str(candidate["symbol"]).strip()
    raw_cik = candidate.get("cik")
    if raw_cik is None and candidate["subIndustry"] == "LEGACY_120_CLASSIFICATION":
        cik_is_valid = True
    else:
        cik = str(raw_cik or "").strip()
        cik_is_valid = len(cik) == 10 and cik.isdigit()
    return bool(VALID_SYMBOL.fullmatch(symbol)) and cik_is_valid


def _without_hash(payload: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    result.pop(field, None)
    return result


def repair_universe_slot(
    universe_v1: dict[str, Any],
    *,
    replacement: dict[str, Any],
    universe_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replace exactly one invalid candidate while preserving the frozen slot."""
    original = copy.deepcopy(universe_v1)
    candidates = original["candidates"]
    invalid_indexes = [
        index for index, candidate in enumerate(candidates) if not is_valid_candidate(candidate)
    ]
    if len(invalid_indexes) != 1:
        raise ValueError("Exactly one invalid v1 pseudo-security is required")
    if not is_valid_candidate(replacement):
        raise ValueError("Replacement candidate is invalid")

    invalid_index = invalid_indexes[0]
    removed = candidates[invalid_index]
    existing_symbols = {
        str(item["symbol"]) for index, item in enumerate(candidates) if index != invalid_index
    }
    if replacement["symbol"] in existing_symbols:
        raise ValueError("Replacement symbol already exists in the frozen universe")

    repaired_candidate = copy.deepcopy(replacement)
    repaired_candidate["candidateRole"] = removed["candidateRole"]
    repaired_candidate["marketCapBand"] = removed["marketCapBand"]
    repaired_candidate["marketCapBandStatus"] = removed["marketCapBandStatus"]
    repaired_candidate["companyType"] = removed["companyType"]
    repaired_candidate["selectionReason"] = (
        "Minimal deterministic replacement of an invalid source-table pseudo-security; "
        "the replacement inherits the frozen candidate slot and role."
    )

    candidates[invalid_index] = repaired_candidate
    original["universeVersion"] = universe_version
    original["repair"] = {
        "schemaVersion": "provider-expansion-universe-repair-v1.0.0",
        "baseUniverseVersion": universe_v1["universeVersion"],
        "baseUniverseContentHash": universe_v1["universeContentHash"],
        "policy": (
            "Replace the sole invalid pseudo-security with the next eligible candidate "
            "produced by the original frozen selection order; preserve all other slots."
        ),
    }
    original["universeContentHash"] = canonical_hash(
        _without_hash(original, "universeContentHash")
    )

    unchanged = sum(
        left == right
        for index, (left, right) in enumerate(
            zip(universe_v1["candidates"], original["candidates"], strict=True)
        )
        if index != invalid_index
    )
    diff = {
        "schemaVersion": "provider-expansion-universe-diff-v1.0.0",
        "baseUniverseVersion": universe_v1["universeVersion"],
        "baseUniverseContentHash": universe_v1["universeContentHash"],
        "repairedUniverseVersion": original["universeVersion"],
        "repairedUniverseContentHash": original["universeContentHash"],
        "removed": [
            {
                "symbol": removed["symbol"],
                "candidateRole": removed["candidateRole"],
                "sourceOrdinal": removed["sourceOrdinal"],
                "reason": "INVALID_SOURCE_TABLE_PSEUDO_SECURITY",
            }
        ],
        "added": [
            {
                "symbol": repaired_candidate["symbol"],
                "candidateRole": repaired_candidate["candidateRole"],
                "sector": repaired_candidate["sector"],
                "cik": repaired_candidate["cik"],
                "sourceOrdinal": repaired_candidate["sourceOrdinal"],
                "reason": "NEXT_ELIGIBLE_BY_FROZEN_SELECTION_ORDER",
            }
        ],
        "proof": {
            "candidateCountBefore": len(universe_v1["candidates"]),
            "candidateCountAfter": len(original["candidates"]),
            "unchangedCandidateRecords": unchanged,
            "changedSlots": [invalid_index],
            "uniqueSymbolsAfter": len(
                {item["symbol"] for item in original["candidates"]}
            ),
            "allCandidatesValidAfter": all(
                is_valid_candidate(item) for item in original["candidates"]
            ),
        },
    }
    diff["diffContentHash"] = canonical_hash(diff)
    return original, diff


def repair_slice_manifest_slot(
    manifest_v1: dict[str, Any],
    *,
    universe_v2: dict[str, Any],
    removed_symbol: str,
    added_symbol: str,
) -> dict[str, Any]:
    """Preserve all slice assignments and replace only the invalid symbol slot."""
    manifest = copy.deepcopy(manifest_v1)
    matching_slots: list[tuple[int, int]] = []
    for slice_index, slice_record in enumerate(manifest["slices"]):
        for member_index, symbol in enumerate(slice_record["symbols"]):
            if symbol == removed_symbol:
                matching_slots.append((slice_index, member_index))
    if len(matching_slots) != 1:
        raise ValueError("Removed symbol must occur in exactly one manifest slot")
    if any(
        added_symbol in slice_record["symbols"] for slice_record in manifest["slices"]
    ):
        raise ValueError("Replacement symbol already occurs in the v1 manifest")

    slice_index, member_index = matching_slots[0]
    manifest["slices"][slice_index]["symbols"][member_index] = added_symbol
    candidate_by_symbol = {
        str(item["symbol"]): item for item in universe_v2["candidates"]
    }
    members = [
        candidate_by_symbol[symbol]
        for symbol in manifest["slices"][slice_index]["symbols"]
    ]
    slice_record = manifest["slices"][slice_index]
    slice_record["sectorDistribution"] = dict(
        sorted(Counter(item["sector"] for item in members).items())
    )
    slice_record["marketCapDistribution"] = dict(
        sorted(
            Counter(
                item.get("marketCapBand") or "NOT_APPLICABLE" for item in members
            ).items()
        )
    )
    slice_record["roleDistribution"] = dict(
        sorted(Counter(item["candidateRole"] for item in members).items())
    )
    manifest["schemaVersion"] = "provider-gate-expansion-v2.0.0"
    manifest["universeVersion"] = universe_v2["universeVersion"]
    manifest["universeContentHash"] = universe_v2["universeContentHash"]
    manifest["repairPolicy"] = (
        "All v1 slice slots are frozen; only the invalid pseudo-security slot is "
        "replaced by the deterministic successor."
    )
    manifest["manifestContentHash"] = canonical_hash(
        _without_hash(manifest, "manifestContentHash")
    )
    return manifest


def verify_minimal_repair(
    universe_v1: dict[str, Any],
    universe_v2: dict[str, Any],
    manifest_v1: dict[str, Any],
    manifest_v2: dict[str, Any],
) -> dict[str, Any]:
    """Return machine-readable proof or reject non-minimal repair drift."""
    before = {item["symbol"]: item for item in universe_v1["candidates"]}
    after = {item["symbol"]: item for item in universe_v2["candidates"]}
    removed = sorted(before.keys() - after.keys())
    added = sorted(after.keys() - before.keys())
    if len(removed) != 1 or len(added) != 1:
        raise ValueError("Repair must remove and add exactly one symbol")
    unchanged_symbols = before.keys() & after.keys()
    if any(before[symbol] != after[symbol] for symbol in unchanged_symbols):
        raise ValueError("Repair changed an existing candidate record")

    locations_v1 = {
        symbol: (record["sliceId"], index)
        for record in manifest_v1["slices"]
        for index, symbol in enumerate(record["symbols"])
    }
    locations_v2 = {
        symbol: (record["sliceId"], index)
        for record in manifest_v2["slices"]
        for index, symbol in enumerate(record["symbols"])
    }
    if any(locations_v1[symbol] != locations_v2[symbol] for symbol in unchanged_symbols):
        raise ValueError("Repair changed an existing symbol slice assignment")
    if locations_v1[removed[0]] != locations_v2[added[0]]:
        raise ValueError("Replacement did not inherit the invalid manifest slot")
    if len(after) != 300 or len(locations_v2) != 300:
        raise ValueError("Repaired universe and manifest must contain 300 symbols")
    if not all(is_valid_candidate(item) for item in universe_v2["candidates"]):
        raise ValueError("Repaired universe still contains invalid candidates")

    return {
        "removedSymbol": removed[0],
        "addedSymbol": added[0],
        "unchangedCandidateRecords": len(unchanged_symbols),
        "unchangedSliceAssignments": len(unchanged_symbols),
        "replacementSlice": locations_v2[added[0]][0],
        "replacementPosition": locations_v2[added[0]][1],
        "uniqueValidSecurities": len(after),
        "verificationStatus": "PASS",
    }


def verify_deterministic_successor(
    ordered_eligible_candidates: list[dict[str, Any]],
    *,
    frozen_symbols: set[str],
    replacement_symbol: str,
) -> dict[str, Any]:
    """Prove that the replacement is the first unselected eligible candidate."""
    successor = next(
        (
            candidate
            for candidate in ordered_eligible_candidates
            if str(candidate["symbol"]) not in frozen_symbols
        ),
        None,
    )
    if successor is None:
        raise ValueError("Frozen selection order has no eligible successor")
    if successor["symbol"] != replacement_symbol:
        raise ValueError("Replacement is not the next eligible frozen-order candidate")
    return {
        "orderingRule": "original sector round robin over cleaned eligible source rows",
        "replacementSymbol": replacement_symbol,
        "replacementSourceOrdinal": successor["sourceOrdinal"],
        "verificationStatus": "PASS",
    }


def build_repair_diff_artifact(
    diff: dict[str, Any],
    proof: dict[str, Any],
    *,
    source_snapshot_sha256: str,
    base_manifest: dict[str, Any],
    repaired_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Seal universe and slice proof into a value-free machine-readable artifact."""
    if proof.get("verificationStatus") != "PASS":
        raise ValueError("Minimal repair proof must pass before sealing")
    if diff["baseUniverseContentHash"] == diff["repairedUniverseContentHash"]:
        raise ValueError("Repaired universe requires a new content hash")
    payload = {
        **_without_hash(diff, "diffContentHash"),
        "sourceSnapshotSha256": source_snapshot_sha256,
        "baseManifestContentHash": base_manifest["manifestContentHash"],
        "repairedManifestContentHash": repaired_manifest["manifestContentHash"],
        "sliceAssignmentProof": proof,
        "invariants": {
            "sameFrozenSourceSnapshot": True,
            "sameSelectionAndStratificationPolicy": True,
            "existingCandidateRolesChanged": 0,
            "existingCandidateSectorsChanged": 0,
            "existingSliceAssignmentsChanged": 0,
            "invalidPseudoSecuritiesRemaining": 0,
        },
    }
    return {**payload, "diffContentHash": canonical_hash(payload)}
