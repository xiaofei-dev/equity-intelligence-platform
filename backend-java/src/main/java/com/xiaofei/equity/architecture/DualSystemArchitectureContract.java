package com.xiaofei.equity.architecture;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

public final class DualSystemArchitectureContract {

	public static final String CONTRACT_VERSION = "dual-system-architecture-v1.0.0";
	private static final List<String> LONG_TERM_BENCHMARKS =
			List.of("SPY", "DATED_SECTOR_BENCHMARK");
	private static final List<String> QUANT_BENCHMARKS =
			List.of("SPY", "DATED_SECTOR_BENCHMARK", "CASH");
	private static final Pattern DECIMAL_PATTERN =
			Pattern.compile("-?(?:0|[1-9]\\d*)(?:\\.\\d+)?");
	private static final Pattern RFC3339_INSTANT_PATTERN = Pattern.compile(
			"\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}"
			+ "(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})");

	private DualSystemArchitectureContract() {
	}

	public static DecisionContext decode(JsonMapper mapper, String json)
			throws Exception {
		JsonNode root = mapper.readTree(json);
		validateWireEnvelope(root);
		return mapper.treeToValue(root, DecisionContext.class);
	}

	public enum Sleeve {
		LONG_TERM_CORE,
		QUANT_TRADING
	}

	public enum DataState {
		VALID,
		MISSING,
		STALE,
		INVALID,
		NOT_APPLICABLE,
		EXCLUDED
	}

	public enum EvidenceStrictness {
		STRICT_IDENTITY_AND_CHRONOLOGY,
		DOMAIN_TOLERANT_NUMERIC,
		APPROXIMATE_HISTORICAL_RESEARCH
	}

	public enum EvidenceClaimClass {
		CURRENT_ONLY,
		APPROXIMATE_HISTORICAL,
		STRICT_PIT,
		SEALED_PROSPECTIVE
	}

	public enum ModelApplicability {
		APPLICABLE,
		SPECIALIZED_MODEL_REQUIRED,
		NOT_APPLICABLE,
		INSUFFICIENT_EVIDENCE
	}

	public enum ModelEvidenceLabel {
		NOT_VALIDATED,
		DEVELOPMENT_OBSERVED,
		BACKTEST_SUPPORTED,
		PIT_SUPPORTED,
		FORWARD_SUPPORTED
	}

	public record DecisionContext(
			String contractVersion,
			Map<String, String> versionSet,
			JsonNode security,
			DecisionTiming decisionTiming,
			Evidence evidence,
			JsonNode completedSession,
			EngineOutput fundamentalValueOutput,
			EngineOutput quantTradePlanOutput,
			PortfolioRiskView portfolioRiskView,
			AiNarrative aiNarrative,
			HumanControl humanControl,
			Compatibility compatibility,
			ValidationGovernance validationGovernance) {

		public DecisionContext {
			if (!CONTRACT_VERSION.equals(contractVersion)) {
				throw new IllegalArgumentException("Unsupported dual-system contract version");
			}
			for (String version : List.of(
					"evidenceSchemaVersion", "calendarVersion", "taxonomyVersion",
					"normalizationVersion", "benchmarkPolicyVersion",
					"riskPolicyVersion", "costPolicyVersion")) {
				requireText(versionSet == null ? null : versionSet.get(version), version);
			}
			if (decisionTiming == null) {
				throw new IllegalArgumentException("Decision timing is required");
			}
			requireSecurity(security);
			Instant decisionCutoff = instantNode(
					decisionTiming.decisionCutoff(), "decisionCutoff");
			Instant ingestionCutoff = instantNode(
					decisionTiming.sealedIngestionCutoff(), "sealedIngestionCutoff");
			if (decisionCutoff.isAfter(ingestionCutoff)) {
				throw new IllegalArgumentException(
						"Decision cutoff cannot exceed sealed ingestion cutoff");
			}
			if (instantNode(evidence.availableAt(), "availableAt").isAfter(
						decisionCutoff)
					|| instantNode(evidence.ingestedAt(), "ingestedAt").isAfter(
						ingestionCutoff)) {
				throw new IllegalArgumentException("Evidence exceeds a sealed cutoff");
			}
			requireCompletedSession(
					completedSession, decisionCutoff, ingestionCutoff);
			if (fundamentalValueOutput.sleeve() != Sleeve.LONG_TERM_CORE) {
				throw new IllegalArgumentException(
						"Fundamental value output must use LONG_TERM_CORE");
			}
			if (quantTradePlanOutput.sleeve() != Sleeve.QUANT_TRADING) {
				throw new IllegalArgumentException(
						"Quant trade plan must use QUANT_TRADING");
			}
			if (!portfolioRiskView.scoreAggregationPolicy()
					.equals("PROHIBITED_ACROSS_ENGINES")) {
				throw new IllegalArgumentException("Cross-engine score averaging is prohibited");
			}
			if (!Boolean.FALSE.equals(portfolioRiskView.automaticCashTransfersAllowed())) {
				throw new IllegalArgumentException("Automatic cash transfers are prohibited");
			}
			if (!Boolean.TRUE.equals(portfolioRiskView.sameSecurityAcrossSleevesAllowed())
					|| !"EXPLICIT_HUMAN_DECISION_ONLY".equals(
							portfolioRiskView.cashTransferAuthority())) {
				throw new IllegalArgumentException("Portfolio sleeve policy is invalid");
			}
			portfolioRiskView.validateSleeves();
			requireText(portfolioRiskView.contractVersion(), "portfolio contractVersion");
			portfolioRiskView.validateBindings(
					fundamentalValueOutput.outputId(), quantTradePlanOutput.outputId());
			if (!Boolean.FALSE.equals(aiNarrative.mayAffectDeterministicFields())
					|| !Boolean.FALSE.equals(aiNarrative.maySetWeightsOrTrades())) {
				throw new IllegalArgumentException("AI must remain narrative-only");
			}
			if (!Boolean.FALSE.equals(
					humanControl.automaticBrokerageExecutionAllowed())) {
				throw new IllegalArgumentException("Automatic brokerage execution is prohibited");
			}
			if (!Boolean.TRUE.equals(humanControl.decisionRequiredForFinalAllocation())) {
				throw new IllegalArgumentException("Final allocation requires a human decision");
			}
			if (!Boolean.TRUE.equals(humanControl.decisionRequiredForCashTransfer())
					|| !Boolean.TRUE.equals(humanControl.decisionRecordsAreImmutable())
					|| !Boolean.TRUE.equals(humanControl.correctionsUseSupersession())) {
				throw new IllegalArgumentException("All human-control invariants are required");
			}
			if (!"VALUATION_OPPORTUNITY".equals(compatibility.successorMetric())) {
				throw new IllegalArgumentException(
						"VALUATION_OPPORTUNITY is the required successor metric");
			}
			if (!"LONG_TERM_VALUATION_EVIDENCE".equals(
						compatibility.legacyBuyingOpportunityMeaning())
					|| !"COMPATIBILITY_SURFACE".equals(
						compatibility.legacyPublicMarketDataApiStatus())) {
				throw new IllegalArgumentException("Compatibility tuple is invalid");
			}
			if (validationGovernance == null
					|| !Boolean.FALSE.equals(
							validationGovernance.mayUpgradeModelEvidenceLabel())
					|| !"APPROXIMATE_HISTORICAL_BACKTEST".equals(
							validationGovernance.userFacingConcept())
					|| validationGovernance.internalApproximateHistoricalRepresentation()
							== null
					|| !validationGovernance.internalApproximateHistoricalRepresentation()
							.equals(List.of(
									"APPROXIMATE_HISTORICAL_RESEARCH",
									"APPROXIMATE_HISTORICAL"))) {
				throw new IllegalArgumentException(
						"Evidence usability cannot upgrade model evidence labels");
			}
			try {
				ModelEvidenceLabel.valueOf(validationGovernance.modelEvidenceLabel());
			} catch (RuntimeException error) {
				throw new IllegalArgumentException(
						"Unknown model evidence label", error);
			}
		}
	}

	public record DecisionTiming(
			JsonNode decisionCutoff,
			JsonNode sealedIngestionCutoff) {
		public DecisionTiming {
			instantNode(decisionCutoff, "decisionCutoff");
			instantNode(sealedIngestionCutoff, "sealedIngestionCutoff");
		}
	}

	public record Evidence(
			EvidenceStrictness strictnessClass,
			EvidenceClaimClass claimClass,
			DataState state,
			String reasonCode,
			String providerCode,
			String providerSchemaVersion,
			String adapterVersion,
			String normalizationVersion,
			String sourceRecordId,
			int sourceRevision,
			String sourceContentHash,
			String normalizedRecordHash,
			JsonNode effectiveAt,
			JsonNode availableAt,
			JsonNode retrievedAt,
			JsonNode ingestedAt,
			String freshnessPolicyVersion,
			JsonNode staleAfter,
			JsonNode fieldTolerancePolicy,
			JsonNode conflict) {

		public Evidence {
			if (strictnessClass == null || claimClass == null) {
				throw new IllegalArgumentException(
						"Evidence strictness and claim class are required");
			}
			if (strictnessClass == EvidenceStrictness.APPROXIMATE_HISTORICAL_RESEARCH
					&& (claimClass == EvidenceClaimClass.STRICT_PIT
					|| claimClass == EvidenceClaimClass.SEALED_PROSPECTIVE)) {
				throw new IllegalArgumentException(
						"Approximate historical evidence cannot claim PIT or prospective status");
			}
			if (state == null) {
				throw new IllegalArgumentException("Evidence state is required");
			}
			if (state != DataState.VALID && isBlank(reasonCode)) {
				throw new IllegalArgumentException("Non-VALID evidence requires a reason");
			}
			for (var entry : Map.of(
					"providerCode", providerCode,
					"providerSchemaVersion", providerSchemaVersion,
					"adapterVersion", adapterVersion,
					"normalizationVersion", normalizationVersion,
					"sourceRecordId", sourceRecordId,
					"sourceContentHash", sourceContentHash,
					"normalizedRecordHash", normalizedRecordHash,
					"freshnessPolicyVersion", freshnessPolicyVersion).entrySet()) {
				requireText(entry.getValue(), entry.getKey());
			}
			if (sourceRevision < 1) {
				throw new IllegalArgumentException(
						"sourceRevision must be a positive integer");
			}
			Instant effective = instantNode(effectiveAt, "effectiveAt");
			Instant available = instantNode(availableAt, "availableAt");
			Instant ingested = instantNode(ingestedAt, "ingestedAt");
			if (effective.isAfter(available) || available.isAfter(ingested)) {
				throw new IllegalArgumentException(
						"Evidence chronology must be effective <= available <= ingested");
			}
			if (retrievedAt != null && !retrievedAt.isNull()) {
				Instant retrieved = instantNode(retrievedAt, "retrievedAt");
				if (retrieved.isBefore(available) || retrieved.isAfter(ingested)) {
					throw new IllegalArgumentException(
							"Retrieved evidence chronology is invalid");
				}
			}
			if (staleAfter != null && !staleAfter.isNull()) {
				instantNode(staleAfter, "staleAfter");
			}
			if (conflict == null || !conflict.isObject()
					|| !textNode(conflict.get("status"))
					|| !textNode(conflict.get("criticality"))) {
				throw new IllegalArgumentException(
						"Evidence conflict status and criticality are required");
			}
			if (strictnessClass == EvidenceStrictness.DOMAIN_TOLERANT_NUMERIC
					&& (fieldTolerancePolicy == null
					|| !fieldTolerancePolicy.isObject()
					|| !fieldTolerancePolicy.path("alignmentSatisfied").isBoolean()
					|| !fieldTolerancePolicy.path("alignmentSatisfied").booleanValue()
					|| !textNode(fieldTolerancePolicy.get("policyVersion"))
					|| !textNode(fieldTolerancePolicy.get("fieldCode")))) {
				throw new IllegalArgumentException(
						"Numeric tolerance must be aligned, field-specific, and versioned");
			}
		}
	}

	public record EngineOutput(
			String outputId,
			String decisionContractVersion,
			String modelId,
			String modelVersion,
			String strategyVersion,
			Sleeve sleeve,
			DataState state,
			ModelApplicability applicability,
			JsonNode fairValue,
			JsonNode referencePrice,
			JsonNode marginOfSafety,
			JsonNode maximumAllocationCap,
			String automaticFinalWeight,
			List<String> benchmarkCodes,
			String deterministicScore,
			String evidenceHash,
			String reasonCode,
			String market,
			String cadence,
			String direction,
			Boolean leverageAllowed,
			Boolean shortingAllowed,
			Boolean optionsAllowed,
			String setup,
			String entryRule,
			JsonNode entryRangeLow,
			JsonNode entryRangeHigh,
			JsonNode stop,
			List<JsonNode> targets,
			Integer expiresAfterCompletedSessions,
			JsonNode maximumPositionRisk,
			JsonNode liquidityAssumptions,
			JsonNode costAssumptions,
			Boolean brokerageExecutionAllowed) {

		public EngineOutput {
			benchmarkCodes = benchmarkCodes == null ? List.of() : List.copyOf(benchmarkCodes);
			targets = targets == null ? List.of() : List.copyOf(targets);
			if (sleeve == Sleeve.LONG_TERM_CORE && automaticFinalWeight != null) {
				throw new IllegalArgumentException(
						"Value engine cannot set an automatic final portfolio weight");
			}
			if (sleeve == null || state == null) {
				throw new IllegalArgumentException("Engine sleeve and state are required");
			}
			for (var entry : Map.of(
					"outputId", outputId,
					"decisionContractVersion", decisionContractVersion,
					"modelId", modelId,
					"modelVersion", modelVersion,
					"strategyVersion", strategyVersion,
					"evidenceHash", evidenceHash).entrySet()) {
				requireText(entry.getValue(), entry.getKey());
			}
			if (state != DataState.VALID && deterministicScore != null) {
				throw new IllegalArgumentException("Non-VALID engine output cannot carry a score");
			}
			if (state != DataState.VALID && isBlank(reasonCode)) {
				throw new IllegalArgumentException("Non-VALID engine output requires a reason");
			}
			if (sleeve == Sleeve.LONG_TERM_CORE) {
				if (applicability == null || fairValue == null || !fairValue.isObject()
						|| !textNode(fairValue.get("currency"))
						|| !textNode(fairValue.get("methodVersion"))
						|| !benchmarkCodes.equals(LONG_TERM_BENCHMARKS)) {
					throw new IllegalArgumentException("Fundamental value structure is incomplete");
				}
				BigDecimal central = decimalNode(fairValue.get("central"), "central");
				BigDecimal low = decimalNode(fairValue.get("rangeLow"), "rangeLow");
				BigDecimal high = decimalNode(fairValue.get("rangeHigh"), "rangeHigh");
				decimalNode(referencePrice, "referencePrice");
				decimalNode(marginOfSafety, "marginOfSafety");
				decimalNode(maximumAllocationCap, "maximumAllocationCap");
				if (low.compareTo(central) > 0 || central.compareTo(high) > 0) {
					throw new IllegalArgumentException(
							"Fair-value range must contain the central estimate");
				}
			}
			if (sleeve == Sleeve.QUANT_TRADING
					&& (!"US_EQUITIES".equals(market)
					|| !"DAILY".equals(cadence)
					|| !"LONG_ONLY".equals(direction)
					|| !Boolean.FALSE.equals(leverageAllowed)
					|| !Boolean.FALSE.equals(shortingAllowed)
					|| !Boolean.FALSE.equals(optionsAllowed)
					|| !Boolean.FALSE.equals(brokerageExecutionAllowed))) {
				throw new IllegalArgumentException(
						"Quant v1 cannot enable leverage, shorting, options, or execution");
			}
			if (sleeve == Sleeve.QUANT_TRADING
					&& (isBlank(entryRule)
					|| isBlank(setup)
					|| targets.isEmpty()
					|| expiresAfterCompletedSessions == null
					|| expiresAfterCompletedSessions < 1
					|| !benchmarkCodes.equals(QUANT_BENCHMARKS)
					|| !validAssumptions(liquidityAssumptions)
					|| !validAssumptions(costAssumptions))) {
				throw new IllegalArgumentException("Quant trade plan structure is incomplete");
			}
			if (sleeve == Sleeve.QUANT_TRADING) {
				decimalNode(entryRangeLow, "entryRangeLow");
				decimalNode(entryRangeHigh, "entryRangeHigh");
				decimalNode(stop, "stop");
				for (JsonNode target : targets) {
					decimalNode(target, "target");
				}
				decimalNode(maximumPositionRisk, "maximumPositionRisk");
			}
		}
	}

	public record PortfolioRiskView(
			String contractVersion,
			String scoreAggregationPolicy,
			Boolean sameSecurityAcrossSleevesAllowed,
			Boolean automaticCashTransfersAllowed,
			String cashTransferAuthority,
			List<JsonNode> sleeves) {

		public PortfolioRiskView {
			sleeves = sleeves == null ? List.of() : List.copyOf(sleeves);
		}

		void validateSleeves() {
			if (sleeves.size() != 2) {
				throw new IllegalArgumentException("Exactly two sleeve entries are required");
			}
			var names = Set.of(
					strictTextValue(sleeves.get(0).get("sleeve"), "sleeve"),
					strictTextValue(sleeves.get(1).get("sleeve"), "sleeve"));
			if (!names.equals(Set.of("LONG_TERM_CORE", "QUANT_TRADING"))) {
				throw new IllegalArgumentException("Distinct approved sleeves are required");
			}
			for (JsonNode entry : sleeves) {
				List<String> expected = strictTextValue(
						entry.get("sleeve"), "sleeve").equals("LONG_TERM_CORE")
						? LONG_TERM_BENCHMARKS : QUANT_BENCHMARKS;
				if (!jsonStringList(entry.path("benchmarkCodes")).equals(expected)) {
					throw new IllegalArgumentException("Sleeve benchmarks are invalid");
				}
			}
		}

		void validateBindings(String fundamentalOutputId, String quantOutputId) {
			for (JsonNode entry : sleeves) {
				String expected = strictTextValue(
						entry.get("sleeve"), "sleeve").equals("LONG_TERM_CORE")
						? fundamentalOutputId : quantOutputId;
				if (!expected.equals(strictTextValue(
						entry.get("engineOutputId"), "engineOutputId"))) {
					throw new IllegalArgumentException(
							"Sleeve engine-output binding is invalid");
				}
			}
		}
	}

	public record AiNarrative(
			String status,
			String narrative,
			List<String> sourceReferences,
			String promptVersion,
			String modelVersion,
			Boolean mayAffectDeterministicFields,
			Boolean maySetWeightsOrTrades) {

		public AiNarrative {
			sourceReferences = sourceReferences == null
					? List.of() : List.copyOf(sourceReferences);
		}
	}

	public record HumanControl(
			Boolean decisionRequiredForFinalAllocation,
			Boolean decisionRequiredForCashTransfer,
			Boolean automaticBrokerageExecutionAllowed,
			Boolean decisionRecordsAreImmutable,
			Boolean correctionsUseSupersession) {
	}

	public record Compatibility(
			String legacyBuyingOpportunityMeaning,
			String successorMetric,
			String legacyPublicMarketDataApiStatus) {
	}

	public record ValidationGovernance(
			List<String> internalApproximateHistoricalRepresentation,
			String userFacingConcept,
			String modelEvidenceLabel,
			Boolean mayUpgradeModelEvidenceLabel) {
	}

	private static void requireCompletedSession(
			JsonNode session, Instant decisionCutoff, Instant ingestionCutoff) {
		if (session == null || !"COMPLETED".equals(
				strictTextValue(session.get("status"), "status"))) {
			throw new IllegalArgumentException("Completed session status must be COMPLETED");
		}
		for (String field : List.of(
				"calendarId", "calendarVersion", "mic", "sessionDate", "timezone",
				"scheduledOpen", "scheduledClose", "completedAt")) {
			strictTextValue(session.get(field), field);
		}
		LocalDate.parse(strictTextValue(session.get("sessionDate"), "sessionDate"));
		Instant open = instantNode(session.get("scheduledOpen"), "scheduledOpen");
		Instant close = instantNode(session.get("scheduledClose"), "scheduledClose");
		Instant completed = instantNode(session.get("completedAt"), "completedAt");
		if (!open.isBefore(close)
				|| close.isAfter(completed)
				|| completed.isAfter(decisionCutoff)
				|| decisionCutoff.isAfter(ingestionCutoff)) {
			throw new IllegalArgumentException("Completed-session chronology is invalid");
		}
		if (!session.path("earlyClose").isBoolean()) {
			throw new IllegalArgumentException("earlyClose must be Boolean");
		}
	}

	private static void requireText(String value, String field) {
		if (isBlank(value)) {
			throw new IllegalArgumentException(field + " is required");
		}
	}

	private static boolean isBlank(String value) {
		return value == null || value.isBlank();
	}

	private static boolean validAssumptions(JsonNode assumptions) {
		if (assumptions == null || !assumptions.isObject()
				|| !textNode(assumptions.get("version"))
				|| !textNode(assumptions.get("state"))) {
			return false;
		}
		try {
			DataState state = DataState.valueOf(assumptions.get("state").textValue());
			if (state != DataState.VALID && !textNode(assumptions.get("reasonCode"))) {
				return false;
			}
			String[] numericFields = assumptions.has("averageDailyDollarVolume")
					? new String[] {"averageDailyDollarVolume", "maximumParticipationRate"}
					: new String[] {"transactionCostBps", "slippageBps"};
			for (String field : numericFields) {
				decimalNode(assumptions.get(field), field);
			}
			return true;
		} catch (IllegalArgumentException error) {
			return false;
		}
	}

	private static Instant instantNode(JsonNode node, String field) {
		if (!textNode(node)) {
			throw new IllegalArgumentException(field + " must be a string");
		}
		String value = node.textValue();
		if (!RFC3339_INSTANT_PATTERN.matcher(value).matches()) {
			throw new IllegalArgumentException(
					field + " must be an RFC 3339 instant with timezone");
		}
		try {
			return OffsetDateTime.parse(value).toInstant();
		} catch (RuntimeException error) {
			throw new IllegalArgumentException(
					field + " must be an RFC 3339 instant with timezone", error);
		}
	}

	private static BigDecimal decimalNode(JsonNode node, String field) {
		if (!textNode(node)) {
			throw new IllegalArgumentException(field + " must be a decimal string");
		}
		String value = node.textValue();
		if (!DECIMAL_PATTERN.matcher(value).matches()) {
			throw new IllegalArgumentException(
					field + " must be an ordinary base-10 decimal string");
		}
		try {
			return new BigDecimal(value);
		} catch (NumberFormatException error) {
			throw new IllegalArgumentException(field + " must be a decimal string", error);
		}
	}

	private static boolean textNode(JsonNode node) {
		return node != null && node.isString() && !node.textValue().isBlank();
	}

	private static List<String> jsonStringList(JsonNode node) {
		if (!node.isArray()) {
			return List.of();
		}
		var result = new java.util.ArrayList<String>();
		node.forEach(item -> result.add(strictTextValue(item, "list item")));
		return List.copyOf(result);
	}

	private static void requireSecurity(JsonNode security) {
		if (security == null || !security.isObject()) {
			throw new IllegalArgumentException("Security object is required");
		}
		for (String field : List.of(
				"securityId", "companyId", "instrumentId", "shareClassId",
				"listingId", "tickerAssignmentId", "ticker", "mic", "currency")) {
			strictTextValue(security.get(field), field);
		}
	}

	private static void validateWireEnvelope(JsonNode root) {
		JsonNode rootObject = objectNode(root, "decision context");
		strictTextValue(rootObject.get("contractVersion"), "contractVersion");
		JsonNode versions = objectNode(rootObject.get("versionSet"), "versionSet");
		for (String field : List.of(
				"evidenceSchemaVersion", "calendarVersion", "taxonomyVersion",
				"normalizationVersion", "benchmarkPolicyVersion",
				"riskPolicyVersion", "costPolicyVersion")) {
			strictTextValue(versions.get(field), field);
		}
		requireSecurity(objectNode(rootObject.get("security"), "security"));

		JsonNode evidence = objectNode(rootObject.get("evidence"), "evidence");
		for (String field : List.of(
				"strictnessClass", "claimClass", "state", "reasonCode",
				"providerCode", "providerSchemaVersion", "adapterVersion",
				"normalizationVersion", "sourceRecordId", "sourceContentHash",
				"normalizedRecordHash", "freshnessPolicyVersion")) {
			if (!field.equals("reasonCode") || evidence.hasNonNull(field)) {
				strictTextValue(evidence.get(field), field);
			}
		}
		if (evidence.get("sourceRevision") == null
				|| !evidence.get("sourceRevision").isIntegralNumber()) {
			throw new IllegalArgumentException("sourceRevision must be an integer");
		}
		JsonNode conflict = objectNode(evidence.get("conflict"), "conflict");
		strictTextValue(conflict.get("status"), "conflict status");
		strictTextValue(conflict.get("criticality"), "conflict criticality");
		if (evidence.hasNonNull("fieldTolerancePolicy")) {
			JsonNode tolerance = objectNode(
					evidence.get("fieldTolerancePolicy"), "fieldTolerancePolicy");
			strictTextValue(tolerance.get("policyVersion"), "tolerance policyVersion");
			strictTextValue(tolerance.get("fieldCode"), "tolerance fieldCode");
			strictBooleanNode(tolerance.get("alignmentSatisfied"), "alignmentSatisfied");
		}

		JsonNode session = objectNode(rootObject.get("completedSession"), "completedSession");
		for (String field : List.of(
				"calendarId", "calendarVersion", "mic", "sessionDate", "timezone",
				"scheduledOpen", "scheduledClose", "status", "completedAt")) {
			strictTextValue(session.get(field), field);
		}
		strictBooleanNode(session.get("earlyClose"), "earlyClose");

		JsonNode fundamental = objectNode(
				rootObject.get("fundamentalValueOutput"), "fundamentalValueOutput");
		JsonNode quant = objectNode(
				rootObject.get("quantTradePlanOutput"), "quantTradePlanOutput");
		for (JsonNode output : List.of(fundamental, quant)) {
			for (String field : List.of(
					"outputId", "decisionContractVersion", "modelId", "modelVersion",
					"strategyVersion", "sleeve", "state", "evidenceHash")) {
				strictTextValue(output.get(field), field);
			}
			if (output.hasNonNull("reasonCode")) {
				strictTextValue(output.get("reasonCode"), "reasonCode");
			}
			if (output.hasNonNull("deterministicScore")) {
				strictTextValue(output.get("deterministicScore"), "deterministicScore");
			}
			strictStringArray(output.get("benchmarkCodes"), "benchmarkCodes");
		}
		strictTextValue(fundamental.get("applicability"), "applicability");
		JsonNode fairValue = objectNode(fundamental.get("fairValue"), "fairValue");
		for (String field : List.of(
				"central", "rangeLow", "rangeHigh", "currency", "methodVersion")) {
			strictTextValue(fairValue.get(field), field);
		}
		for (String field : List.of(
				"referencePrice", "marginOfSafety", "maximumAllocationCap")) {
			strictTextValue(fundamental.get(field), field);
		}

		for (String field : List.of(
				"market", "cadence", "direction", "setup", "entryRule",
				"entryRangeLow", "entryRangeHigh", "stop", "maximumPositionRisk")) {
			strictTextValue(quant.get(field), field);
		}
		for (String field : List.of(
				"leverageAllowed", "shortingAllowed", "optionsAllowed",
				"brokerageExecutionAllowed")) {
			strictBooleanNode(quant.get(field), field);
		}
		strictStringArray(quant.get("targets"), "targets");
		validateAssumptionWire(
				objectNode(quant.get("liquidityAssumptions"), "liquidityAssumptions"),
				List.of("averageDailyDollarVolume", "maximumParticipationRate"));
		validateAssumptionWire(
				objectNode(quant.get("costAssumptions"), "costAssumptions"),
				List.of("transactionCostBps", "slippageBps"));

		JsonNode portfolio = objectNode(
				rootObject.get("portfolioRiskView"), "portfolioRiskView");
		for (String field : List.of(
				"contractVersion", "scoreAggregationPolicy", "cashTransferAuthority")) {
			strictTextValue(portfolio.get(field), field);
		}
		strictBooleanNode(
				portfolio.get("sameSecurityAcrossSleevesAllowed"),
				"sameSecurityAcrossSleevesAllowed");
		strictBooleanNode(
				portfolio.get("automaticCashTransfersAllowed"),
				"automaticCashTransfersAllowed");
		JsonNode sleeveEntries = portfolio.get("sleeves");
		if (sleeveEntries == null || !sleeveEntries.isArray()) {
			throw new IllegalArgumentException("sleeves must be an array");
		}
		sleeveEntries.forEach(entry -> {
			JsonNode sleeve = objectNode(entry, "sleeve");
			strictTextValue(sleeve.get("sleeve"), "sleeve");
			strictTextValue(sleeve.get("engineOutputId"), "engineOutputId");
			strictStringArray(sleeve.get("benchmarkCodes"), "benchmarkCodes");
			for (String field : List.of("cash", "costBasis")) {
				strictTextValue(sleeve.get(field), field);
			}
		});

		JsonNode ai = objectNode(rootObject.get("aiNarrative"), "aiNarrative");
		strictTextValue(ai.get("status"), "AI status");
		for (String field : List.of(
				"narrative", "promptVersion", "modelVersion")) {
			if (ai.hasNonNull(field)) {
				strictTextValue(ai.get(field), field);
			}
		}
		strictStringArray(ai.get("sourceReferences"), "sourceReferences");
		strictBooleanNode(
				ai.get("mayAffectDeterministicFields"), "mayAffectDeterministicFields");
		strictBooleanNode(ai.get("maySetWeightsOrTrades"), "maySetWeightsOrTrades");

		JsonNode human = objectNode(rootObject.get("humanControl"), "humanControl");
		for (String field : List.of(
				"decisionRequiredForFinalAllocation", "decisionRequiredForCashTransfer",
				"automaticBrokerageExecutionAllowed", "decisionRecordsAreImmutable",
				"correctionsUseSupersession")) {
			strictBooleanNode(human.get(field), field);
		}
		JsonNode compatibility = objectNode(
				rootObject.get("compatibility"), "compatibility");
		for (String field : List.of(
				"legacyBuyingOpportunityMeaning", "successorMetric",
				"legacyPublicMarketDataApiStatus")) {
			strictTextValue(compatibility.get(field), field);
		}
		JsonNode governance = objectNode(
				rootObject.get("validationGovernance"), "validationGovernance");
		strictStringArray(
				governance.get("internalApproximateHistoricalRepresentation"),
				"internalApproximateHistoricalRepresentation");
		for (String field : List.of(
				"userFacingConcept", "modelEvidenceLabel")) {
			strictTextValue(governance.get(field), field);
		}
		strictBooleanNode(
				governance.get("mayUpgradeModelEvidenceLabel"),
				"mayUpgradeModelEvidenceLabel");
	}

	private static void validateAssumptionWire(
			JsonNode assumptions, List<String> numericFields) {
		strictTextValue(assumptions.get("version"), "assumption version");
		strictTextValue(assumptions.get("state"), "assumption state");
		if (assumptions.hasNonNull("reasonCode")) {
			strictTextValue(assumptions.get("reasonCode"), "assumption reasonCode");
		}
		for (String field : numericFields) {
			strictTextValue(assumptions.get(field), field);
		}
	}

	private static JsonNode objectNode(JsonNode node, String field) {
		if (node == null || !node.isObject()) {
			throw new IllegalArgumentException(field + " must be a JSON object");
		}
		return node;
	}

	private static void strictBooleanNode(JsonNode node, String field) {
		if (node == null || !node.isBoolean()) {
			throw new IllegalArgumentException(field + " must be a JSON Boolean");
		}
	}

	private static void strictStringArray(JsonNode node, String field) {
		if (node == null || !node.isArray()) {
			throw new IllegalArgumentException(field + " must be a JSON string array");
		}
		node.forEach(item -> strictTextValue(item, field + " item"));
	}

	private static String strictTextValue(JsonNode node, String field) {
		if (!textNode(node)) {
			throw new IllegalArgumentException(field + " must be a nonblank JSON string");
		}
		return node.textValue();
	}
}
