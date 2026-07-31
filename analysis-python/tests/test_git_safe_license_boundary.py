from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_DERIVED_METRIC_KEYS = {
    "annualizedinformationratio",
    "averageexcessreturn",
    "averagemaximumadverseexcursion",
    "averagemaximumfavorableexcursion",
    "averagenetreturn",
    "averagerankinformationcoefficient",
    "averagetopminusbottomnetreturn",
    "bottomnetexcessreturn",
    "hitRate".lower(),
    "maximumdrawdown",
    "meanexcessreturn",
    "meanmaximumadverseexcursion",
    "meanmaximumdrawdown",
    "meanmaximumfavorableexcursion",
    "meannetreturn",
    "meantopminusbottomnetspread",
    "medianrankinformationcoefficient",
    "rankinformationcoefficient",
    "scorerankedmodelminusbenchmark",
    "topnetexcessreturn",
    "worstmaximumdrawdown",
}


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _walk(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, str(key))
            yield child_path, child
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, (*path, str(index)))


def test_git_safe_generated_artifacts_do_not_publish_licensed_values() -> None:
    generated = _root() / "docs/generated"
    for artifact_path in sorted(generated.glob("*.json")):
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        walked = tuple(_walk(payload))

        raw_value_paths = [
            path
            for path, value in walked
            if path[-1] in {"rawProviderValuesIncluded", "licensedProviderValuesIncluded"}
            and value is True
        ]
        assert not raw_value_paths, (
            f"{artifact_path.name} publishes provider values at {raw_value_paths}"
        )

        controlled_flags = [
            path
            for path, value in walked
            if path[-1] == "derivedLicensedMetricsIncluded" and value is True
        ]
        if not controlled_flags:
            continue

        assert controlled_flags == [
            ("controlledResult", "derivedLicensedMetricsIncluded")
        ], (
            f"{artifact_path.name} may reference licensed derived metrics only "
            "through controlledResult"
        )
        controlled = payload["controlledResult"]
        assert controlled["storageType"] == "GITIGNORED_LOCAL"
        assert str(controlled["path"]).replace("\\", "/").startswith("storage/")
        assert payload.get("derivedLicensedMetricsIncluded") is not True

        exposed_metric_paths = [
            path
            for path, value in walked
            if "controlledResult" not in path
            and path[-1].lower() in _DERIVED_METRIC_KEYS
            and isinstance(value, int | float | str)
        ]
        assert not exposed_metric_paths, (
            f"{artifact_path.name} exposes licensed derived metrics at "
            f"{exposed_metric_paths[:5]}"
        )
