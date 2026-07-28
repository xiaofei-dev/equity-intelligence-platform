from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)
from equity_analysis.screening.config import QC_VERSION, QC_WEIGHTS
from equity_analysis.screening.models import (
    CompanyType,
    FactorInput,
    FactorStatus,
    SecurityObservation,
    SizeCohort,
)
from equity_analysis.screening.normalization import normalize_observations

GATE_VERSION = "objective-rating-current-snapshot-algorithm-gate-v1.0.0"
SCORE_QUANTUM = Decimal("0.0001")
VALUATION_INPUTS = ("earnings_yield", "fcf_yield")
QC_RAW_FACTORS = tuple(
    name for name in QC_WEIGHTS if name != "valuation_guardrail"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def _q(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)


def valuation_guardrail_score(
    earnings_yield_percentile: Decimal,
    fcf_yield_percentile: Decimal,
) -> Decimal:
    if earnings_yield_percentile <= 10 and fcf_yield_percentile <= 10:
        return Decimal("0")
    return _q((earnings_yield_percentile + fcf_yield_percentile) / Decimal(2))


def _classification_map(path: Path) -> dict[str, dict[str, Any]]:
    universe = _load(path)
    return {item["symbol"]: item for item in universe["candidates"]}


def build_current_snapshot_algorithm_gate(
    *,
    repository_root: Path,
    input_manifest_path: Path,
    universe_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    manifest = _load(input_manifest_path)
    if manifest["gateStatus"] != "READY_FOR_OFFLINE_QC_SCORING":
        raise ValueError("CURRENT_SNAPSHOT_INPUT_GATE_NOT_READY")
    classifications = _classification_map(universe_path)
    observations: list[SecurityObservation] = []
    source_by_symbol: dict[str, dict[str, Any]] = {}
    as_of = datetime.fromisoformat(manifest["cutoff"].replace("Z", "+00:00"))
    for item in manifest["securities"]:
        if item["status"] != "CURRENT_QC_INPUT_READY":
            continue
        symbol = item["symbol"]
        classification = classifications.get(symbol)
        if classification is None:
            raise ValueError(f"UNIVERSE_CLASSIFICATION_MISSING[{symbol}]")
        if classification["companyType"] != "MATURE_OPERATING_COMPANY":
            raise ValueError(f"UNSUPPORTED_COMPANY_TYPE_IN_QC_COHORT[{symbol}]")
        payload = _load(repository_root / item["storageReference"])
        if payload.get("contentHash") != item["payloadContentHash"]:
            raise ValueError(f"INPUT_PAYLOAD_HASH_MISMATCH[{symbol}]")
        raw = payload.get("qcRawFactors")
        if not isinstance(raw, dict):
            raise ValueError(f"QC_RAW_FACTORS_MISSING[{symbol}]")
        factor_names = (*QC_RAW_FACTORS, *VALUATION_INPUTS)
        factors = tuple(
            FactorInput(
                name=name,
                value=Decimal(str(raw[name])),
                status=FactorStatus.VALID,
            )
            for name in factor_names
        )
        observations.append(
            SecurityObservation(
                security_id=f"US:{symbol}",
                symbol=symbol,
                as_of_time=as_of,
                sector=classification["sector"],
                size_cohort=SizeCohort(classification["marketCapBand"]),
                company_type=CompanyType.MATURE_OPERATING_COMPANY,
                factors=factors,
            )
        )
        source_by_symbol[symbol] = item
    normalized = normalize_observations(observations)
    securities: list[dict[str, Any]] = []
    for observation in observations:
        results = {
            result.name: result
            for result in normalized[observation.security_id]
        }
        required = (*QC_RAW_FACTORS, *VALUATION_INPUTS)
        invalid = [
            name
            for name in required
            if results[name].status != FactorStatus.VALID
            or results[name].normalized_score is None
        ]
        if invalid:
            raise ValueError(
                f"NORMALIZED_FACTOR_NOT_VALID[{observation.symbol}:{','.join(invalid)}]"
            )
        valuation = valuation_guardrail_score(
            results["earnings_yield"].normalized_score,
            results["fcf_yield"].normalized_score,
        )
        contributions = {
            name: _q(results[name].normalized_score * QC_WEIGHTS[name])
            for name in QC_RAW_FACTORS
        }
        contributions["valuation_guardrail"] = _q(
            valuation * QC_WEIGHTS["valuation_guardrail"]
        )
        score = _q(sum(contributions.values(), Decimal(0)))
        securities.append(
            {
                "symbol": observation.symbol,
                "securityId": observation.security_id,
                "status": "SCORED",
                "strategyVersion": QC_VERSION,
                "score": format(score, "f"),
                "rank": None,
                "sector": observation.sector,
                "sizeCohort": observation.size_cohort.value,
                "factorScores": {
                    name: {
                        "normalizedScore": format(
                            results[name].normalized_score, "f"
                        ),
                        "cohortLevel": results[name].cohort_level.value,
                        "cohortSize": results[name].cohort_size,
                        "contribution": format(contributions[name], "f"),
                    }
                    for name in QC_RAW_FACTORS
                }
                | {
                    "valuation_guardrail": {
                        "normalizedScore": format(valuation, "f"),
                        "earningsYieldPercentile": format(
                            results["earnings_yield"].normalized_score, "f"
                        ),
                        "fcfYieldPercentile": format(
                            results["fcf_yield"].normalized_score, "f"
                        ),
                        "contribution": format(
                            contributions["valuation_guardrail"], "f"
                        ),
                    }
                },
                "inputPayloadHash": source_by_symbol[observation.symbol][
                    "payloadContentHash"
                ],
            }
        )
    ranked = sorted(securities, key=lambda item: (-Decimal(item["score"]), item["symbol"]))
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    artifact = {
        "artifactType": "OBJECTIVE_RATING_CURRENT_SNAPSHOT_ALGORITHM_GATE",
        "schemaVersion": GATE_VERSION,
        "strategyVersion": QC_VERSION,
        "scope": "CURRENT_DECISION_ONLY",
        "asOfTime": manifest["cutoff"],
        "status": "PASS",
        "inputManifestPath": input_manifest_path.relative_to(
            repository_root
        ).as_posix(),
        "inputManifestContentHash": manifest["artifactContentHash"],
        "universePath": universe_path.relative_to(repository_root).as_posix(),
        "scoredSecurityCount": len(ranked),
        "cohortMinimums": {
            "sectorSize": 20,
            "sector": 30,
            "general": 100,
        },
        "valuationGuardrailRule": {
            "inputs": list(VALUATION_INPUTS),
            "score": "MEAN_OF_CURRENT_COHORT_YIELD_PERCENTILES",
            "expensiveDecileRule": (
                "ZERO_WHEN_EARNINGS_AND_FCF_YIELD_PERCENTILES_ARE_BOTH_AT_OR_BELOW_10"
            ),
        },
        "weights": {
            name: format(weight, "f") for name, weight in QC_WEIGHTS.items()
        },
        "securities": ranked,
        "methodologyBoundaries": {
            "formulaOrWeightChanges": False,
            "historicalPitClaim": False,
            "historicalBacktestAuthorized": False,
            "forwardDecisionQualityValidationExecuted": False,
            "automaticTradingAuthorized": False,
        },
        "networkRequestsExecuted": False,
        "licensedProviderValuesIncluded": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    if output_path.exists():
        existing = _load(output_path)
        if existing != artifact:
            raise ValueError("CURRENT_SNAPSHOT_ALGORITHM_GATE_CONFLICT")
    else:
        write_immutable_json(output_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the offline current-snapshot Objective Rating QC gate."
    )
    parser.add_argument(
        "--input-manifest",
        type=Path,
        default=Path(
            "docs/generated/objective-rating-v1-current-decision-input-manifest-v1.json"
        ),
    )
    parser.add_argument(
        "--universe",
        type=Path,
        default=Path(
            "analysis-python/tests/fixtures/provider_expansion_universe_v2.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/objective-rating-v1-current-snapshot-algorithm-gate-v1.json"
        ),
    )
    arguments = parser.parse_args()
    root = Path.cwd().resolve()
    artifact = build_current_snapshot_algorithm_gate(
        repository_root=root,
        input_manifest_path=(root / arguments.input_manifest).resolve(),
        universe_path=(root / arguments.universe).resolve(),
        output_path=(root / arguments.output).resolve(),
    )
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "scored": artifact["scoredSecurityCount"],
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
