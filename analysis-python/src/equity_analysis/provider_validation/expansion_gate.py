import json
from collections import Counter
from datetime import UTC, date, datetime
from decimal import ROUND_CEILING, Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from pydantic import Field, model_validator

from equity_analysis.provider_validation.mature_gate import (
    BILLING_SAFETY_MULTIPLIER,
    LIVE_ENDPOINTS,
    REPORT_VERSION,
    projected_live_cost,
)
from equity_analysis.provider_validation.models import (
    NormalizedFinancialObservation,
    ValidationModel,
)

EXPANSION_SCHEMA_VERSION = "provider-gate-expansion-v1.0.0"
EXPANSION_AGGREGATE_SCHEMA_VERSION = "provider-gate-expansion-aggregate-v1.0.0"
PROVIDER_DAILY_LIMIT = 100_000
MINIMUM_PROVIDER_RESERVE = 20_000
MINIMUM_UNIVERSE_SIZE = 300
MAXIMUM_UNIVERSE_SIZE = 500
ELIGIBLE_ROLES = frozenset({"PRIMARY", "RESERVE"})
NON_SCORING_ROLES = frozenset({"REFERENCE_ONLY", "EXCLUDED"})
ELIGIBLE_COMPANY_TYPE = "MATURE_OPERATING_COMPANY"
MARKET_CAP_BANDS = frozenset({"MEGA", "LARGE", "MID", "SMALL"})
CONTROLLED_STORAGE_TYPES = frozenset({"POSTGRESQL", "GITIGNORED_LOCAL"})
SCORING_INPUT_CONTRACT_VERSION = "provider-neutral-scoring-input-v2.0.0"
SCORING_INPUT_MANIFEST_VERSION = "scoring-input-manifest-v1.0.0"
FORMULA_INPUT_FIELDS = frozenset(
    {
        "capital_expenditure",
        "cash_and_equivalents",
        "diluted_weighted_average_shares",
        "ebitda",
        "gross_profit",
        "income_tax",
        "interest_expense",
        "market_capitalization",
        "net_income",
        "operating_cash_flow",
        "operating_income",
        "pretax_income",
        "revenue",
        "stockholders_equity",
        "total_debt",
    }
)
FORMULA_HISTORY_REQUIREMENTS = {
    "quarterlyFinancialPeriods": 8,
    "historicalValuationObservations": 12,
}


class NormalizedScoringInputRecord(ValidationModel):
    symbol: str
    normalized_field: str
    value: Decimal
    unit: str
    currency: str | None = None
    observation_type: str = "FINANCIAL_STATEMENT"
    fiscal_period_end: date
    period_type: str
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    provider_code: str
    provider_symbol: str
    source_reference: str
    accession_number: str | None = None
    source_content_hash: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    provider_schema_version: str = "LEGACY_UNSPECIFIED"
    parser_version: str = "LEGACY_UNSPECIFIED"
    normalization_version: str = SCORING_INPUT_CONTRACT_VERSION
    content_hash: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_pit_and_source(self) -> "NormalizedScoringInputRecord":
        if self.available_at > self.ingested_at:
            raise ValueError("availableAt cannot be later than ingestedAt")
        if self.effective_at.date() != self.fiscal_period_end:
            raise ValueError("effectiveAt must represent the fiscal period end")
        if self.observation_type not in {
            "FINANCIAL_STATEMENT",
            "DAILY_PRICE",
            "HISTORICAL_MARKET_VALUE",
        }:
            raise ValueError("Unsupported scoring-input observation type")
        lowered = self.source_reference.lower()
        if "api_token=" in lowered or "api_key=" in lowered:
            raise ValueError("Source reference must not contain credentials")
        return self


class ScoringInputPersistenceReceipt(ValidationModel):
    symbol: str
    storage_type: str
    storage_reference: str
    normalized_payload_hash: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    record_count: int = Field(gt=0)
    normalized_fields: tuple[str, ...]
    minimum_available_at: datetime
    maximum_available_at: datetime
    source_hashes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_controlled_storage(self) -> "ScoringInputPersistenceReceipt":
        if self.storage_type not in CONTROLLED_STORAGE_TYPES:
            raise ValueError("Scoring inputs require controlled non-Git storage")
        if not self.normalized_fields or len(set(self.normalized_fields)) != len(
            self.normalized_fields
        ):
            raise ValueError("Receipt normalized fields must be non-empty and unique")
        if not self.source_hashes or any(len(item) != 64 for item in self.source_hashes):
            raise ValueError("Receipt requires source SHA-256 hashes")
        return self


class ScoringInputPersistence(Protocol):
    def persist(
        self,
        records: tuple[NormalizedScoringInputRecord, ...],
        *,
        run_id: str,
    ) -> ScoringInputPersistenceReceipt: ...


class GitignoredLocalScoringInputStore:
    def __init__(
        self,
        root: Path = Path("storage/provider-validation/scoring-inputs"),
    ) -> None:
        self._root = root

    def persist(
        self,
        records: tuple[NormalizedScoringInputRecord, ...],
        *,
        run_id: str,
    ) -> ScoringInputPersistenceReceipt:
        if not records:
            raise ValueError("Scoring-input persistence requires records")
        symbols = {item.symbol for item in records}
        if len(symbols) != 1:
            raise ValueError("A scoring-input payload must contain exactly one symbol")
        symbol = next(iter(symbols))
        if not symbol.replace(".", "").replace("-", "").isalnum():
            raise ValueError("Symbol is unsafe for a storage path")
        ordered = sorted(
            records,
            key=lambda item: (
                item.normalized_field,
                item.fiscal_period_end,
                item.period_type,
                item.available_at,
                item.content_hash,
            ),
        )
        payload = {
            "inputContractVersion": SCORING_INPUT_CONTRACT_VERSION,
            "symbol": symbol,
            "formulaHistoryRequirements": FORMULA_HISTORY_REQUIREMENTS,
            "missingNormalizedFields": sorted(
                FORMULA_INPUT_FIELDS - {item.normalized_field for item in ordered}
            ),
            "records": [item.model_dump(mode="json", by_alias=True) for item in ordered],
        }
        payload_hash = canonical_hash(payload)
        output = self._root / symbol / f"{payload_hash}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        serialized = (
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=True,
            )
            + "\n"
        )
        try:
            with output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized)
        except FileExistsError:
            if output.read_text(encoding="utf-8") != serialized:
                raise RuntimeError("CONTENT_ADDRESSED_SCORING_INPUT_COLLISION") from None
        available_at = [item.available_at for item in records]
        return ScoringInputPersistenceReceipt(
            symbol=symbol,
            storageType="GITIGNORED_LOCAL",
            storageReference=output.as_posix(),
            normalizedPayloadHash=payload_hash,
            recordCount=len(records),
            normalizedFields=tuple(sorted({item.normalized_field for item in records})),
            minimumAvailableAt=min(available_at),
            maximumAvailableAt=max(available_at),
            sourceHashes=tuple(sorted({item.source_content_hash.upper() for item in records})),
        )


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest().upper()


def file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def new_run_id(now: datetime | None = None) -> str:
    generated_at = now or datetime.now(UTC)
    return f"{generated_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:12]}"


def financial_observations_to_scoring_inputs(
    observations: tuple[NormalizedFinancialObservation, ...],
    accession_by_period: dict[tuple[str, str, date], str],
    *,
    provider_code: str,
    unit_by_field: dict[str, str] | None = None,
) -> tuple[NormalizedScoringInputRecord, ...]:
    if not provider_code:
        raise ValueError("Scoring input requires a provider code")
    units = unit_by_field or {}
    records = []
    for observation in observations:
        if observation.available_at is None:
            raise ValueError("Scoring input requires PIT availableAt")
        period_identity = (
            observation.statement_type,
            observation.period_type,
            observation.fiscal_period_end,
        )
        accession = accession_by_period.get(period_identity)
        if not accession:
            raise ValueError("Scoring input requires a matched PIT accession")
        for field, value in sorted(observation.values.items()):
            if value is None:
                continue
            unit = units.get(
                field,
                "SHARES" if field == "shares_outstanding" else observation.currency,
            )
            record_without_hash = {
                "symbol": observation.symbol,
                "normalizedField": field,
                "value": str(value),
                "unit": unit,
                "currency": (
                    None if unit == "SHARES" else observation.currency
                ),
                "observationType": "FINANCIAL_STATEMENT",
                "fiscalPeriodEnd": observation.fiscal_period_end.isoformat(),
                "periodType": observation.period_type,
                "effectiveAt": observation.effective_at.isoformat(),
                "availableAt": observation.available_at.isoformat(),
                "ingestedAt": observation.ingested_at.isoformat(),
                "providerCode": provider_code,
                "providerSymbol": observation.provider_symbol,
                "sourceReference": observation.source_reference,
                "accessionNumber": accession,
                "sourceContentHash": observation.content_hash.upper(),
                "providerSchemaVersion": observation.provider_schema_version,
                "parserVersion": observation.parser_version,
                "normalizationVersion": SCORING_INPUT_CONTRACT_VERSION,
            }
            records.append(
                NormalizedScoringInputRecord.model_validate(
                    {
                        **record_without_hash,
                        "contentHash": canonical_hash(record_without_hash),
                    }
                )
            )
    return tuple(
        sorted(
            records,
            key=lambda item: (
                item.symbol,
                item.normalized_field,
                item.fiscal_period_end,
                item.period_type,
            ),
        )
    )


def market_and_price_observations_to_scoring_inputs(
    prices,
    market_values,
) -> tuple[NormalizedScoringInputRecord, ...]:
    records: list[NormalizedScoringInputRecord] = []
    currency = prices.security.currency
    for bar in prices.bars:
        values = {
            "unadjusted_close": (bar.close_price, f"{currency}/SHARE"),
            "adjusted_close": (bar.adjusted_close, f"{currency}/SHARE"),
        }
        for field, (value, unit) in values.items():
            if value is None:
                continue
            effective_at = datetime.combine(bar.trading_date, datetime.min.time(), tzinfo=UTC)
            raw = {
                "symbol": prices.requested_symbol,
                "normalizedField": field,
                "value": str(value),
                "unit": unit,
                "currency": currency,
                "observationType": "DAILY_PRICE",
                "fiscalPeriodEnd": bar.trading_date.isoformat(),
                "periodType": "DAILY",
                "effectiveAt": effective_at.isoformat(),
                "availableAt": prices.available_at.isoformat(),
                "ingestedAt": prices.retrieved_at.isoformat(),
                "providerCode": prices.provider_descriptor.code,
                "providerSymbol": prices.provider_symbol,
                "sourceReference": prices.source_reference,
                "accessionNumber": None,
                "sourceContentHash": prices.content_hash.removeprefix("sha256:").upper(),
                "providerSchemaVersion": prices.provider_descriptor.provider_schema_version,
                "parserVersion": prices.provider_descriptor.parser_version,
                "normalizationVersion": SCORING_INPUT_CONTRACT_VERSION,
            }
            records.append(
                NormalizedScoringInputRecord.model_validate(
                    {**raw, "contentHash": canonical_hash(raw)}
                )
            )
    for observation in market_values:
        effective_at = datetime.combine(
            observation.effective_at, datetime.min.time(), tzinfo=UTC
        )
        raw = {
            "symbol": observation.symbol,
            "normalizedField": "market_capitalization",
            "value": str(observation.market_capitalization),
            "unit": currency,
            "currency": currency,
            "observationType": "HISTORICAL_MARKET_VALUE",
            "fiscalPeriodEnd": observation.effective_at.isoformat(),
            "periodType": "DAILY",
            "effectiveAt": effective_at.isoformat(),
            "availableAt": observation.ingested_at.isoformat(),
            "ingestedAt": observation.ingested_at.isoformat(),
            "providerCode": prices.provider_descriptor.code,
            "providerSymbol": observation.provider_symbol,
            "sourceReference": observation.source_reference,
            "accessionNumber": None,
            "sourceContentHash": observation.content_hash.upper(),
            "providerSchemaVersion": observation.provider_schema_version,
            "parserVersion": observation.parser_version,
            "normalizationVersion": SCORING_INPUT_CONTRACT_VERSION,
        }
        records.append(
            NormalizedScoringInputRecord.model_validate(
                {**raw, "contentHash": canonical_hash(raw)}
            )
        )
    return tuple(
        sorted(
            records,
            key=lambda item: (
                item.normalized_field,
                item.fiscal_period_end,
                item.available_at,
            ),
        )
    )


def validate_expansion_universe(universe: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    candidates = tuple(universe["candidates"])
    if not MINIMUM_UNIVERSE_SIZE <= len(candidates) <= MAXIMUM_UNIVERSE_SIZE:
        raise ValueError("Expansion universe must contain between 300 and 500 securities")
    symbols = [item["symbol"].upper() for item in candidates]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Expansion universe symbols must be unique")
    for item in candidates:
        role = item["candidateRole"]
        if role not in ELIGIBLE_ROLES | NON_SCORING_ROLES:
            raise ValueError(f"Unsupported candidate role: {role}")
        if not item.get("selectionReason"):
            raise ValueError("Every expansion candidate requires a selection reason")
        if role in ELIGIBLE_ROLES:
            if item.get("companyType") != ELIGIBLE_COMPANY_TYPE:
                raise ValueError("Eligible candidates must use the mature company model")
            if item.get("marketCapBand") not in MARKET_CAP_BANDS:
                raise ValueError("Eligible candidates require a supported market-cap band")
        elif not item.get("classificationReason"):
            raise ValueError("Non-scoring candidates require a classification reason")
    eligible = [item for item in candidates if item["candidateRole"] in ELIGIBLE_ROLES]
    if len({item["sector"] for item in eligible}) < 8:
        raise ValueError("Expansion universe must cover at least eight sectors")
    if set(item["marketCapBand"] for item in eligible) != MARKET_CAP_BANDS:
        raise ValueError("Expansion universe must cover all four market-cap bands")
    return candidates


def build_slice_manifest(
    universe: dict[str, Any],
    *,
    slice_size: int,
) -> dict[str, Any]:
    candidates = validate_expansion_universe(universe)
    if slice_size < 1:
        raise ValueError("Slice size must be positive")
    slice_count = (len(candidates) + slice_size - 1) // slice_size
    ordered = sorted(
        candidates,
        key=lambda item: (
            item["candidateRole"],
            item["sector"],
            item.get("marketCapBand") or "",
            item["symbol"],
        ),
    )
    assigned: list[list[dict[str, Any]]] = [[] for _ in range(slice_count)]
    stratum_counts: list[Counter[tuple[str, str, str]]] = [
        Counter() for _ in range(slice_count)
    ]
    for candidate in ordered:
        stratum = (
            candidate["candidateRole"],
            candidate["sector"],
            candidate.get("marketCapBand") or "NOT_APPLICABLE",
        )
        available_slices = [
            index for index, members in enumerate(assigned) if len(members) < slice_size
        ]
        selected_index = min(
            available_slices,
            key=lambda index: (
                stratum_counts[index][stratum],
                len(assigned[index]),
                index,
            ),
        )
        assigned[selected_index].append(candidate)
        stratum_counts[selected_index][stratum] += 1

    slices = []
    for slice_index, members in enumerate(assigned, start=1):
        slices.append(
            {
                "sliceId": f"slice-{slice_index:03d}",
                "symbols": [item["symbol"] for item in members],
                "symbolCount": len(members),
                "sectorDistribution": dict(
                    sorted(Counter(item["sector"] for item in members).items())
                ),
                "marketCapDistribution": dict(
                    sorted(
                        Counter(
                            item.get("marketCapBand") or "NOT_APPLICABLE" for item in members
                        ).items()
                    )
                ),
                "roleDistribution": dict(
                    sorted(Counter(item["candidateRole"] for item in members).items())
                ),
            }
        )
    manifest_without_hash = {
        "schemaVersion": EXPANSION_SCHEMA_VERSION,
        "universeVersion": universe["universeVersion"],
        "universeContentHash": canonical_hash(universe),
        "deterministicOrdering": (
            "Candidates sort by candidateRole, sector, marketCapBand, and symbol. "
            "Each candidate is assigned to the slice with the lowest count for its "
            "role-sector-band stratum, then the lowest total count, then slice number."
        ),
        "sliceSize": slice_size,
        "slices": slices,
    }
    return {
        **manifest_without_hash,
        "manifestContentHash": canonical_hash(manifest_without_hash),
    }


def build_slice_preflight(
    slice_record: dict[str, Any],
    *,
    dashboard_before: int,
    output_directory: Path,
    run_id: str | None = None,
    dashboard_counter_status: str = "CONFIRMED",
) -> dict[str, Any]:
    if not 0 <= dashboard_before <= PROVIDER_DAILY_LIMIT:
        raise ValueError("Dashboard counter is outside the provider daily limit")
    symbols = tuple(slice_record["symbols"])
    if len(symbols) != len(set(symbols)) or not symbols:
        raise ValueError("Slice symbols must be non-empty and unique")
    if dashboard_counter_status not in {"CONFIRMED", "PROJECTED_WORST_CASE"}:
        raise ValueError("Unsupported dashboard counter status")
    cost = projected_live_cost(len(symbols), rerun_count=0)
    safety_ceiling = int(
        (
            Decimal(cost["observedProvisionalProviderCalls"]) * BILLING_SAFETY_MULTIPLIER
        ).to_integral_value(rounding=ROUND_CEILING)
    )
    maximum_allowed_delta = PROVIDER_DAILY_LIMIT - MINIMUM_PROVIDER_RESERVE - dashboard_before
    identifier = run_id or new_run_id()
    report_path = output_directory / f"expansion-provider-gate-{identifier}.json"
    diagnostics_path = output_directory / f"expansion-provider-gate-{identifier}-diagnostics.json"
    resumability_path = output_directory / f"expansion-provider-gate-{identifier}-checkpoint.json"
    scoring_manifest_path = (
        output_directory
        / f"expansion-provider-gate-{identifier}-scoring-input-manifest.json"
    )
    return {
        "schemaVersion": EXPANSION_SCHEMA_VERSION,
        "runId": identifier,
        "sliceId": slice_record["sliceId"],
        "symbols": symbols,
        "symbolCount": len(symbols),
        "endpoints": LIVE_ENDPOINTS,
        "dashboardBefore": dashboard_before,
        "dashboardCounterStatus": dashboard_counter_status,
        "providerDailyLimit": PROVIDER_DAILY_LIMIT,
        "minimumProviderReserve": MINIMUM_PROVIDER_RESERVE,
        "maximumAllowedObservedDelta": maximum_allowed_delta,
        "eodhdPhysicalAttemptCeiling": cost["eodhdAttemptCeiling"],
        "secPhysicalAttemptCeiling": cost["secHttpRequests"],
        "totalPhysicalAttemptCeiling": cost["totalHttpRequests"],
        "configuredLocalWeightCeiling": cost["configuredLocalWeightedCalls"],
        "provisionalProviderBilling": cost["observedProvisionalProviderCalls"],
        "providerBilledSafetyCeiling": safety_ceiling,
        "safeToExecute": safety_ceiling <= maximum_allowed_delta,
        "networkRerunSample": 0,
        "reportPath": str(report_path),
        "diagnosticPath": str(diagnostics_path),
        "checkpointPath": str(resumability_path),
        "scoringInputManifestPath": str(scoring_manifest_path),
        "immutableOutputs": True,
        "liveConfirmationRequired": True,
        "networkRequestsExecuted": False,
    }


def write_immutable_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def build_expansion_aggregate(
    universe: dict[str, Any],
    sources: tuple[dict[str, Any], ...],
    *,
    minimum_scoring_ready: int = MINIMUM_UNIVERSE_SIZE,
) -> dict[str, Any]:
    candidates = validate_expansion_universe(universe)
    candidate_by_symbol = {item["symbol"]: item for item in candidates}
    ledger: dict[str, dict[str, Any]] = {}
    component_runs = []
    billing = []
    for source in sorted(sources, key=lambda item: item["sequence"]):
        if source.get("evidenceType") != "LIVE_IMMUTABLE_REPORT":
            raise ValueError("Expansion statuses require immutable live evidence")
        report_path = Path(source["reportPath"])
        if not report_path.is_file():
            raise ValueError(f"Expansion source report is missing: {report_path}")
        if file_hash(report_path) != source["reportSha256"].upper():
            raise ValueError(f"Expansion source hash mismatch: {report_path}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("runId") != source["runId"]:
            raise ValueError("Expansion source run ID mismatch")
        if report.get("reportVersion") != REPORT_VERSION:
            raise ValueError("Expansion source gate standard mismatch")
        symbols = [item["symbol"] for item in report["results"]]
        if len(symbols) != len(set(symbols)):
            raise ValueError("Expansion source contains duplicate symbols")
        for result in report["results"]:
            symbol = result["symbol"]
            candidate = candidate_by_symbol.get(symbol)
            if candidate is None:
                raise ValueError("Expansion source contains an unknown symbol")
            ledger[symbol] = {
                "symbol": symbol,
                "sector": candidate["sector"],
                "marketCapBand": candidate.get("marketCapBand"),
                "companyType": candidate["companyType"],
                "candidateRole": candidate["candidateRole"],
                "status": result["status"],
                "reasonCodes": result["reasonCodes"],
                "fieldCoverage": result.get("fieldCoverage", {}),
                "scoringInputReady": result.get("scoringInputReady") is True,
                "sourceRunId": source["runId"],
                "sourceReportSha256": source["reportSha256"].upper(),
                "liveConfirmed": True,
            }
        observed_delta = source["dashboardAfter"] - source["dashboardBefore"]
        billing.append(
            {
                "runId": source["runId"],
                "dashboardBefore": source["dashboardBefore"],
                "dashboardAfter": source["dashboardAfter"],
                "observedDelta": observed_delta,
                "provisionalProviderBilling": source["provisionalProviderBilling"],
                "providerBilledSafetyCeiling": source["providerBilledSafetyCeiling"],
                "runLevelStatus": (
                    "PROVISIONALLY_RECONCILED"
                    if observed_delta <= source["provisionalProviderBilling"]
                    and observed_delta <= source["providerBilledSafetyCeiling"]
                    else "NOT_RECONCILED"
                ),
                "endpointLevelStatus": "NOT_RECONCILED",
            }
        )
        component_runs.append(source["runId"])
    records = []
    for candidate in sorted(candidates, key=lambda item: item["symbol"]):
        symbol = candidate["symbol"]
        record = ledger.get(symbol)
        if record is not None:
            records.append(record)
        else:
            records.append(
                {
                    "symbol": symbol,
                    "sector": candidate["sector"],
                    "marketCapBand": candidate.get("marketCapBand"),
                    "companyType": candidate["companyType"],
                    "candidateRole": candidate["candidateRole"],
                    "status": (
                        "NOT_EVALUATED"
                        if candidate["candidateRole"] in ELIGIBLE_ROLES
                        else candidate["candidateRole"]
                    ),
                    "reasonCodes": [candidate.get("classificationReason", "NOT_FETCHED")],
                    "fieldCoverage": {},
                    "scoringInputReady": False,
                    "sourceRunId": None,
                    "sourceReportSha256": None,
                    "liveConfirmed": False,
                }
            )
    scoring_ready = [
        item
        for item in records
        if item["candidateRole"] in ELIGIBLE_ROLES
        and item["status"] == "PASS"
        and item["liveConfirmed"]
        and item["scoringInputReady"]
    ]
    status_distribution = dict(sorted(Counter(item["status"] for item in records).items()))
    payload = {
        "artifactType": "CROSS_SLICE_PROVIDER_GATE_SCORING_READY_LEDGER",
        "schemaVersion": EXPANSION_AGGREGATE_SCHEMA_VERSION,
        "isSingleLiveRun": False,
        "networkRequestsExecutedDuringAggregation": False,
        "universeVersion": universe["universeVersion"],
        "universeContentHash": canonical_hash(universe),
        "gateReportVersion": REPORT_VERSION,
        "coverageRule": (
            "Each universe symbol appears once. Later sequence live evidence replaces "
            "earlier live evidence. Offline evidence cannot upgrade a status."
        ),
        "componentRunIds": component_runs,
        "billingEvidence": billing,
        "endpointLevelBillingStatus": "NOT_RECONCILED",
        "uniqueSecurityCount": len(records),
        "statusDistribution": status_distribution,
        "scoringReadyCount": len(scoring_ready),
        "scoringReadyGateStatus": (
            "PASS" if len(scoring_ready) >= minimum_scoring_ready else "FAIL"
        ),
        "scoringReadyDefinition": (
            "Live provider PASS plus a controlled-storage scoring-input receipt; "
            "no Objective Rating was executed."
        ),
        "ledger": records,
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def build_scoring_input_manifest(
    receipts: tuple[ScoringInputPersistenceReceipt, ...],
    *,
    aggregate_artifact_path: str,
    aggregate_artifact_sha256: str,
) -> dict[str, Any]:
    symbols = [item.symbol for item in receipts]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Scoring-input receipts must contain unique symbols")
    if len(aggregate_artifact_sha256) != 64:
        raise ValueError("Aggregate artifact requires a SHA-256 hash")
    records = [
        {
            "symbol": item.symbol,
            "storageType": item.storage_type,
            "storageReference": item.storage_reference,
            "normalizedPayloadHash": item.normalized_payload_hash.upper(),
            "recordCount": item.record_count,
            "normalizedFields": sorted(item.normalized_fields),
            "minimumAvailableAt": item.minimum_available_at.isoformat(),
            "maximumAvailableAt": item.maximum_available_at.isoformat(),
            "sourceHashes": sorted(value.upper() for value in item.source_hashes),
        }
        for item in sorted(receipts, key=lambda value: value.symbol)
    ]
    field_coverage = Counter(field for receipt in receipts for field in receipt.normalized_fields)
    payload = {
        "artifactType": "PROVIDER_NEUTRAL_SCORING_INPUT_MANIFEST",
        "schemaVersion": SCORING_INPUT_MANIFEST_VERSION,
        "inputContractVersion": SCORING_INPUT_CONTRACT_VERSION,
        "aggregateArtifactPath": aggregate_artifact_path,
        "aggregateArtifactSha256": aggregate_artifact_sha256.upper(),
        "securityCount": len(records),
        "fieldCoverageCounts": dict(sorted(field_coverage.items())),
        "storagePolicy": (
            "Normalized values are stored only in PostgreSQL or controlled "
            "gitignored local storage. This Git-safe manifest contains no values "
            "or licensed provider payloads."
        ),
        "licensedRawValuesIncluded": False,
        "records": records,
    }
    serialized = json.dumps(payload, ensure_ascii=True)
    forbidden = ("api_token=", "api_key=", '"value":', '"providerPayload":')
    if any(item in serialized for item in forbidden):
        raise ValueError("Scoring-input manifest contains prohibited material")
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def build_existing_pass_backfill_plan(
    aggregate: dict[str, Any],
    persisted_receipts: tuple[ScoringInputPersistenceReceipt, ...],
) -> dict[str, Any]:
    pass_records = [
        item
        for item in aggregate["passRecords"]
        if item["status"] == "PASS" and item.get("liveConfirmed") is True
    ]
    symbols = [item["symbol"] for item in pass_records]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Aggregate PASS records must be unique")
    receipts_by_symbol = {item.symbol: item for item in persisted_receipts}
    if len(receipts_by_symbol) != len(persisted_receipts):
        raise ValueError("Persisted receipts must contain unique symbols")
    unknown = set(receipts_by_symbol) - set(symbols)
    if unknown:
        raise ValueError("Persisted receipt is outside the live PASS population")
    actions = []
    for item in sorted(pass_records, key=lambda record: record["symbol"]):
        receipt = receipts_by_symbol.get(item["symbol"])
        if receipt is None:
            actions.append(
                {
                    "symbol": item["symbol"],
                    "action": "CONTROLLED_SOURCE_RECOVERY_REQUIRED",
                    "networkFetchAuthorized": False,
                    "sourceRunId": item["sourceRunId"],
                    "sourceReportSha256": item["sourceReportSha256"],
                }
            )
        else:
            actions.append(
                {
                    "symbol": item["symbol"],
                    "action": "IDEMPOTENT_PERSISTENCE_REPLAY",
                    "networkFetchAuthorized": False,
                    "sourceRunId": item["sourceRunId"],
                    "sourceReportSha256": item["sourceReportSha256"],
                    "normalizedPayloadHash": receipt.normalized_payload_hash.upper(),
                    "storageType": receipt.storage_type,
                    "storageReference": receipt.storage_reference,
                }
            )
    counts = Counter(item["action"] for item in actions)
    payload = {
        "artifactType": "EXISTING_PASS_SCORING_INPUT_BACKFILL_PLAN",
        "schemaVersion": SCORING_INPUT_MANIFEST_VERSION,
        "inputContractVersion": SCORING_INPUT_CONTRACT_VERSION,
        "sourceAggregateContentHash": aggregate["artifactContentHash"],
        "uniqueLivePassCount": len(actions),
        "actionCounts": dict(sorted(counts.items())),
        "networkRequestsAuthorized": False,
        "recoveryRule": (
            "Replay normalized immutable payloads when a controlled-storage receipt "
            "exists. Missing local payloads require a separately approved recovery; "
            "this plan never converts absence into an automatic provider refetch."
        ),
        "actions": actions,
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}
