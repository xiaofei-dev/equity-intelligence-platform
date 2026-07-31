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
EXPECTED_FALSE_POSITIVE_FINGERPRINTS = [
    (
        "bfbb13d874b07fee0f347f2b9bc9d452c9042c56:"
        "analysis-python/tests/test_daily_refresh_postgres_v16.py:"
        "generic-api-key:152"
    ),
    (
        "bfbb13d874b07fee0f347f2b9bc9d452c9042c56:"
        "analysis-python/tests/test_daily_refresh_postgres_v16.py:"
        "generic-api-key:243"
    ),
]


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
    assert len(config["rules"]) == 2
    square_rule, generic_api_key_rule = config["rules"]
    assert square_rule["id"] == "square-access-token"
    assert len(square_rule["allowlists"]) == 1
    allowlist = square_rule["allowlists"][0]
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

    assert generic_api_key_rule["id"] == "generic-api-key"
    assert len(generic_api_key_rule["allowlists"]) == 1
    sha256_allowlist = generic_api_key_rule["allowlists"][0]
    assert sha256_allowlist["condition"] == "AND"
    assert sha256_allowlist["regexTarget"] == "match"
    assert sha256_allowlist["regexes"] == [
        r'''(?i)liveConfirmationTokenSha256["']?\s*:\s*["']?[0-9a-f]{64}["']?'''
    ]
    assert sha256_allowlist["paths"] == [
        (
            r"^docs/generated/"
            r"future-completed-session-price-evidence-preflight-v1\.json$"
        )
    ]


def test_allowlisted_square_like_hashes_are_only_candidate_source_hashes() -> None:
    for relative_path in REPORT_PATHS:
        payload = json.loads((ROOT / relative_path).read_text(encoding="utf-8"))
        matches = [path for path, value in _strings(payload) if SQUARE_LIKE_SHA256.fullmatch(value)]

        assert len(matches) == 5
        assert all(
            len(path) >= 2 and path[-2] == "candidateSourceContentHashes" for path in matches
        )


def test_historical_false_positive_fingerprints_are_exact_and_file_scoped() -> None:
    fingerprints = (ROOT / ".gitleaksignore").read_text(encoding="utf-8").splitlines()

    assert fingerprints == EXPECTED_FALSE_POSITIVE_FINGERPRINTS
    assert all(
        ":analysis-python/tests/test_daily_refresh_postgres_v16.py:"
        "generic-api-key:" in fingerprint
        for fingerprint in fingerprints
    )
