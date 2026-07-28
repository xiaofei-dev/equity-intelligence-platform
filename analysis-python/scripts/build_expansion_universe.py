"""Build the deterministic 300-security provider expansion universe."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict, deque
from hashlib import sha256
from pathlib import Path

from bs4 import BeautifulSoup

REFERENCE_SECTORS = {"Energy", "Financials", "Real Estate"}
REFERENCE_SUBINDUSTRY_TERMS = (
    "Biotechnology",
    "Coal",
    "Copper",
    "Diversified Metals",
    "Gold",
    "Oil & Gas",
    "Precious Metals",
    "Silver",
)
TARGET_TOTAL = 300
NEW_PRIMARY_COUNT = 140
NEW_RESERVE_COUNT = 10
NEW_REFERENCE_COUNT = 30
REQUIRED_SOURCE_FIELDS = ("symbol", "name", "sector", "subIndustry", "cik")
HEADER_LITERALS = {
    "symbol",
    "security",
    "gics sector",
    "gics sub-industry",
    "cik",
}
VALID_PROVIDER_SYMBOL = re.compile(
    r"^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?$",
)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-html", type=Path, required=True)
    parser.add_argument(
        "--base-universe",
        type=Path,
        default=Path(
            "analysis-python/tests/fixtures/provider_acceptance_universe_v3.json"
        ),
    )
    parser.add_argument(
        "--base-report",
        type=Path,
        default=Path(
            "docs/generated/"
            "mature-company-data-gate-20260727T074150Z-50407538afa9.json"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def source_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def normalize_constituent_cells(cells: list[str]) -> dict[str, str] | None:
    """Return a normalized constituent, or reject a non-security table row."""
    if len(cells) < 7:
        return None
    candidate = {
        "symbol": cells[0].strip(),
        "name": cells[1].strip(),
        "sector": cells[2].strip(),
        "subIndustry": cells[3].strip(),
        "cik": cells[6].strip(),
    }
    if any(not candidate[field] for field in REQUIRED_SOURCE_FIELDS):
        return None
    if any(value.casefold() in HEADER_LITERALS for value in candidate.values()):
        return None
    if not VALID_PROVIDER_SYMBOL.fullmatch(candidate["symbol"]):
        return None
    if not candidate["cik"].isascii() or not candidate["cik"].isdigit():
        return None
    if len(candidate["cik"]) > 10:
        return None
    candidate["symbol"] = candidate["symbol"].replace(".", "-")
    candidate["cik"] = candidate["cik"].zfill(10)
    return candidate


def parse_constituents(
    path: Path,
    *,
    minimum_count: int = 500,
) -> list[dict[str, str]]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    table = soup.find("table", id="constituents")
    if table is None:
        raise ValueError("S&P constituent table was not found")
    rows = []
    for row in table.select("tbody tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.select("th, td")]
        candidate = normalize_constituent_cells(cells)
        if candidate is not None:
            rows.append(candidate)
    symbols = [item["symbol"] for item in rows]
    if len(symbols) != len(set(symbols)):
        raise ValueError("S&P constituent snapshot contains duplicate symbols")
    if len(rows) < minimum_count:
        raise ValueError("S&P constituent snapshot is unexpectedly incomplete")
    return rows


def is_reference_only(candidate: dict[str, str]) -> bool:
    return candidate["sector"] in REFERENCE_SECTORS or any(
        term in candidate["subIndustry"] for term in REFERENCE_SUBINDUSTRY_TERMS
    )


def round_robin_by_sector(
    candidates: list[dict[str, str]],
    count: int,
) -> list[dict[str, str]]:
    by_sector: dict[str, deque[dict[str, str]]] = defaultdict(deque)
    for candidate in sorted(candidates, key=lambda item: (item["sector"], item["symbol"])):
        by_sector[candidate["sector"]].append(candidate)
    selected: list[dict[str, str]] = []
    sectors = sorted(by_sector)
    while len(selected) < count:
        progressed = False
        for sector in sectors:
            if by_sector[sector] and len(selected) < count:
                selected.append(by_sector[sector].popleft())
                progressed = True
        if not progressed:
            raise ValueError("Not enough candidates to satisfy the deterministic quota")
    return selected


def existing_candidates(
    universe_path: Path,
    report_path: Path,
) -> list[dict[str, object]]:
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result_by_symbol = {item["symbol"]: item for item in report["results"]}
    records = []
    for ordinal, item in enumerate(universe["candidates"], start=1):
        result = result_by_symbol[item["symbol"]]
        band = result.get("marketCapBand") or "LARGE"
        records.append(
            {
                "symbol": item["symbol"],
                "securityName": item["symbol"],
                "sector": item["sector"],
                "subIndustry": "LEGACY_120_CLASSIFICATION",
                "cik": item.get("cik"),
                "marketCapBand": band,
                "marketCapBandStatus": (
                    "LIVE_VERIFIED" if result.get("marketCapBand") else "PROVISIONAL"
                ),
                "candidateRole": item["candidateRole"],
                "companyType": "MATURE_OPERATING_COMPANY",
                "selectionReason": (
                    "Retained from the immutable 120-security mature-company universe."
                ),
                "sourceOrdinal": ordinal,
            }
        )
    return records


def new_candidate(
    item: dict[str, str],
    *,
    role: str,
    ordinal: int,
) -> dict[str, object]:
    reference = role == "REFERENCE_ONLY"
    record: dict[str, object] = {
        "symbol": item["symbol"],
        "securityName": item["name"],
        "sector": item["sector"],
        "subIndustry": item["subIndustry"],
        "cik": item["cik"],
        "marketCapBand": None if reference else "LARGE",
        "marketCapBandStatus": "NOT_APPLICABLE" if reference else "PROVISIONAL",
        "candidateRole": role,
        "companyType": (
            "REFERENCE_COMPANY" if reference else "MATURE_OPERATING_COMPANY"
        ),
        "selectionReason": (
            "Deterministic sector-stratified selection from the frozen constituent "
            "snapshot."
        ),
        "sourceOrdinal": ordinal,
    }
    if reference:
        record["classificationReason"] = (
            "Sector or sub-industry requires a specialized model or reference-only "
            "treatment under the frozen expansion rules."
        )
    return record


def main() -> None:
    options = arguments()
    existing = existing_candidates(options.base_universe, options.base_report)
    existing_symbols = {str(item["symbol"]) for item in existing}
    source = parse_constituents(options.source_html)
    source_ordinals = {
        item["symbol"]: ordinal for ordinal, item in enumerate(source, start=1)
    }
    available = [item for item in source if item["symbol"] not in existing_symbols]
    reference_pool = [item for item in available if is_reference_only(item)]
    eligible_pool = [item for item in available if not is_reference_only(item)]

    eligible_selected = round_robin_by_sector(
        eligible_pool,
        NEW_PRIMARY_COUNT + NEW_RESERVE_COUNT,
    )
    primary = eligible_selected[:NEW_PRIMARY_COUNT]
    reserve = eligible_selected[NEW_PRIMARY_COUNT:]
    reference = round_robin_by_sector(reference_pool, NEW_REFERENCE_COUNT)

    candidates = [
        *existing,
        *[
            new_candidate(
                item,
                role="PRIMARY",
                ordinal=source_ordinals[item["symbol"]],
            )
            for item in primary
        ],
        *[
            new_candidate(
                item,
                role="RESERVE",
                ordinal=source_ordinals[item["symbol"]],
            )
            for item in reserve
        ],
        *[
            new_candidate(
                item,
                role="REFERENCE_ONLY",
                ordinal=source_ordinals[item["symbol"]],
            )
            for item in reference
        ],
    ]
    if len(candidates) != TARGET_TOTAL:
        raise ValueError("Expansion universe did not produce exactly 300 securities")
    if len({str(item["symbol"]) for item in candidates}) != TARGET_TOTAL:
        raise ValueError("Expansion universe contains duplicate symbols")

    payload = {
        "universeVersion": "provider-expansion-us-v1.0.0",
        "selectionAsOf": "2026-07-27",
        "source": {
            "name": "Wikipedia List of S&P 500 companies",
            "sourceReference": (
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            ),
            "retrievedAt": "2026-07-27",
            "sourceContentSha256": source_hash(options.source_html),
            "licenseNote": (
                "Constituent identifiers and classifications are factual selection "
                "metadata; attribution is retained by source reference."
            ),
        },
        "selectionPolicy": {
            "existingUniverseCount": 120,
            "newPrimaryCount": NEW_PRIMARY_COUNT,
            "newReserveCount": NEW_RESERVE_COUNT,
            "newReferenceOnlyCount": NEW_REFERENCE_COUNT,
            "eligibleOrdering": "sector then symbol with deterministic round robin",
            "referenceRules": {
                "sectors": sorted(REFERENCE_SECTORS),
                "subIndustryTerms": list(REFERENCE_SUBINDUSTRY_TERMS),
            },
            "outcomeBlindSelection": True,
            "provisionalMarketCapRule": (
                "New eligible constituents use provisional LARGE until live metadata "
                "preflight verifies the band. Existing candidates retain the original "
                "live gate band where available."
            ),
        },
        "candidates": candidates,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    output = {
        **payload,
        "universeContentHash": sha256(canonical).hexdigest().upper(),
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    with options.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(output, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
