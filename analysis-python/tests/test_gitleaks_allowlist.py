import json
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATHS = (
    "docs/generated/objective-rating-v1-qc-cohort-completion-feasibility-v1.json",
    "docs/generated/objective-rating-v1-qc-cohort-completion-feasibility-v1-1.json",
)
SQUARE_LIKE_SHA256 = re.compile(r"^EAAA[0-9A-F]{60}$")


def _strings(
    value: Any,
    path: tuple[str | int, ...] = (),
) -> Iterator[tuple[tuple[str | int, ...], str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _strings(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _strings(child, (*path, index))
    elif isinstance(value, str):
        yield path, value


def test_square_token_allowlist_is_rule_path_and_format_scoped() -> None:
    config = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))

    assert config["extend"] == {"useDefault": True}
    assert len(config["rules"]) == 1
    rule = config["rules"][0]
    assert rule["id"] == "square-access-token"
    assert len(rule["allowlists"]) == 1
    allowlist = rule["allowlists"][0]
    assert allowlist["condition"] == "AND"
    assert allowlist["regexTarget"] == "secret"
    assert allowlist["regexes"] == [r"^EAAA[0-9A-F]{60}$"]
    assert allowlist["paths"] == [
        (
            r"^docs/generated/"
            r"objective-rating-v1-qc-cohort-completion-feasibility-v1\.json$"
        ),
        (
            r"^docs/generated/"
            r"objective-rating-v1-qc-cohort-completion-feasibility-v1-1\.json$"
        ),
    ]


def test_allowlisted_square_like_hashes_are_only_candidate_source_hashes() -> None:
    for relative_path in REPORT_PATHS:
        payload = json.loads((ROOT / relative_path).read_text(encoding="utf-8"))
        matches = [path for path, value in _strings(payload) if SQUARE_LIKE_SHA256.fullmatch(value)]

        assert len(matches) == 5
        assert all(
            len(path) >= 2 and path[-2] == "candidateSourceContentHashes" for path in matches
        )
