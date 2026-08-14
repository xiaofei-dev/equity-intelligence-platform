import hashlib
import json
from pathlib import Path

from equity_analysis.fundamental_value.historical_quarterly_semantics_support_v1 import (
    canonical_hash,
)

REPOSITORY = Path(__file__).resolve().parents[2]


def test_c9_acceptance_preserves_frozen_source_and_runtime_identity() -> None:
    contract = json.loads(
        (
            REPOSITORY
            / "contracts/fundamental-value-historical-validation-v1"
            / "stage7c9-post-closeout-replay-acceptance.json"
        ).read_text()
    )
    body = dict(contract)
    assert body.pop("contentHash") == canonical_hash(body)
    sources = contract["retainedSource"]
    source_paths = {
        "confirmationSourceSha256": REPOSITORY
        / "analysis-python/src/equity_analysis/fundamental_value/historical_confirmation_v1.py",
        "runnerSourceSha256": REPOSITORY
        / "analysis-python/src/equity_analysis/fundamental_value"
        / "historical_confirmation_runner_v1.py",
        "acceptanceEvaluatorSourceSha256": REPOSITORY
        / "analysis-python/src/equity_analysis/fundamental_value"
        / "historical_confirmation_acceptance_v1.py",
        "focusedTestSourceSha256": REPOSITORY
        / "analysis-python/tests/test_fundamental_value_historical_confirmation_v1.py",
    }
    for field, path in source_paths.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest().upper() == sources[field]
    assert contract["runtimeSeal"] == {
        "pythonImplementation": "cpython",
        "pythonVersion": "3.14.2",
        "pythonCacheTag": "cpython-314",
        "decimalModule": "decimal",
        "decimalVersion": "1.70",
        "libmpdecVersion": "4.0.0",
    }
    limitation = contract["originalIntentRuntimeLimitation"]
    assert limitation["originalPreOutcomeProvenance"] == "FAIL_PARTIAL"
    assert limitation["currentPostCloseoutReplayProvenance"] == (
        "PASS_ENGINEERING_REPRODUCIBILITY_ONLY"
    )
    assert limitation["evidenceUpgradeAllowed"] is False
    assert contract["evidenceLabelChangeAllowed"] is False
