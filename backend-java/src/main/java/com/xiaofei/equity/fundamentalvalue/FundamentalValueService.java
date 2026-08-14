package com.xiaofei.equity.fundamentalvalue;

import java.math.BigDecimal;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.Map;
import java.util.TreeMap;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

import org.springframework.stereotype.Service;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import com.xiaofei.equity.fundamentalvalue.FundamentalValueContract.DecisionRequest;
import com.xiaofei.equity.fundamentalvalue.FundamentalValueContract.DecisionResponse;
import com.xiaofei.equity.fundamentalvalue.FundamentalValueContract.InternalDecision;

@Service
public class FundamentalValueService {

	private static final Pattern HASH = Pattern.compile("sha256:[0-9a-f]{64}");
	private static final Pattern DECIMAL = Pattern.compile("(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?");
	private static final Pattern SIGNED_DECIMAL = Pattern.compile("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?");
	private static final BigDecimal MAXIMUM_DCF_TERMINAL_VALUE_SHARE = new BigDecimal("0.80");
	private static final UUID URL_NAMESPACE = UUID.fromString(
			"6ba7b811-9dad-11d1-80b4-00c04fd430c8");
	private static final String ASSESSMENT_PERSISTENCE_VERSION =
			"fundamental-value-assessment-persistence-v1.0.0";
	private static final Set<String> STATES = Set.of(
			"VALID", "MISSING", "STALE", "INVALID", "NOT_APPLICABLE", "EXCLUDED");
	private static final Set<String> APPLICABILITY = Set.of(
			"APPLICABLE", "SPECIALIZED_MODEL_REQUIRED", "NOT_APPLICABLE",
			"INSUFFICIENT_EVIDENCE");
	private static final Set<String> CLAIMS = Set.of(
			"FULL_CURRENT_DECISION", "LIMITED_MISSING_ADVANCED_EVIDENCE",
			"BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY");
	private static final JsonMapper CANONICAL_MAPPER = JsonMapper.builder().build();

	private final FundamentalValueAnalyticsClient client;

	public FundamentalValueService(FundamentalValueAnalyticsClient client) {
		this.client = client;
	}

	public DecisionResponse create(DecisionRequest request, String idempotencyKey) {
		validateRequest(request);
		return project(client.create(request, idempotencyKey));
	}

	private static void validateRequest(DecisionRequest request) {
		if (request == null || !FundamentalValueContract.COMMAND_VERSION.equals(
				request.contractVersion()) || request.routingId() == null
				|| request.classificationRequestId() == null
				|| request.operandRequestIds() == null || request.operandRequestIds().size() > 34
				|| request.projectionYears() < 3 || request.projectionYears() > 10) {
			throw new FundamentalValueGatewayException("INVALID_FUNDAMENTAL_VALUE_REQUEST",
					"The Fundamental Value request is invalid.", 400);
		}
		Set<String> operands = new java.util.HashSet<>();
		Set<UUID> requests = new java.util.HashSet<>();
		for (var operand : request.operandRequestIds()) {
			if (operand == null || operand.requestId() == null || operand.operandCode() == null
					|| operand.operandCode().isBlank() || !operands.add(operand.operandCode())
					|| !requests.add(operand.requestId())) {
				throw new FundamentalValueGatewayException("INVALID_FUNDAMENTAL_VALUE_REQUEST",
						"The Fundamental Value request is invalid.", 400);
			}
		}
	}

	public DecisionResponse read(UUID assemblyId) {
		DecisionResponse response = project(client.read(assemblyId));
		if (!assemblyId.equals(response.assemblyId())) {
			throw upstreamInvalid();
		}
		return response;
	}

	private static DecisionResponse project(InternalDecision value) {
		try {
			return validateAndProject(value);
		}
		catch (FundamentalValueGatewayException exception) {
			throw exception;
		}
		catch (IllegalArgumentException | ArithmeticException | NullPointerException exception) {
			throw upstreamInvalid();
		}
	}

	private static DecisionResponse validateAndProject(InternalDecision value) {
		boolean assessmentPresent = value.assessmentId() != null;
		boolean usable = "VALID".equals(value.state())
				&& "APPLICABLE".equals(value.applicability())
				&& "MATURE_OPERATING_COMPANY".equals(value.companyType());
		boolean routingValid = validRoutingOutcome(value);
		boolean nonUsableShape = !assessmentPresent
				&& value.modelEvidenceLabel() == null && value.claimCeiling() == null
				&& value.riskCapCeiling() == null
				&& (value.deterministicAssessment() == null
						|| value.deterministicAssessment().isNull());
		if (!FundamentalValueContract.RESULT_VERSION.equals(value.contractVersion())
				|| !STATES.contains(value.state())
				|| !APPLICABILITY.contains(value.applicability())
				|| !routingValid
				|| value.assemblyId() == null || !validIdentity(value.identity())
				|| value.decisionCutoff() == null
				|| value.sealedIngestionCutoff() == null
				|| value.identity().completedSessionDate().isAfter(
						java.time.LocalDate.ofInstant(value.decisionCutoff(), java.time.ZoneOffset.UTC))
				|| value.decisionCutoff().isAfter(value.sealedIngestionCutoff())
				|| value.manifestContentHash() == null
				|| !HASH.matcher(value.manifestContentHash()).matches()
				|| value.inputSealContentHash() == null
				|| !HASH.matcher(value.inputSealContentHash()).matches()
				|| value.finalPortfolioWeightAuthorized()
				|| value.automaticBrokerageExecutionAuthorized()
				|| assessmentPresent != value.coreInvocationAuthorized()
				|| value.coreInvocationAuthorized() != usable
				|| (!usable && "VALID".equals(value.state()))
				|| ("VALID".equals(value.state())
						&& value.reasonCodes() != null && !value.reasonCodes().isEmpty())
				|| (!"VALID".equals(value.state())
						&& (value.reasonCodes() == null || value.reasonCodes().isEmpty()))
				|| (!assessmentPresent && !nonUsableShape)
				|| (assessmentPresent && (!"NOT_VALIDATED".equals(value.modelEvidenceLabel())
						|| !CLAIMS.contains(value.claimCeiling())
						|| value.riskCapCeiling() == null
						|| !validCap(value.riskCapCeiling())
						|| !validClaimCap(value.claimCeiling(), value.riskCapCeiling())
						|| !validAssessmentId(value.deterministicAssessment(), value)
						|| !validAssessment(value.deterministicAssessment(), value)))) {
			throw upstreamInvalid();
		}
		return new DecisionResponse(
				value.contractVersion(), value.assemblyId(), value.assessmentId(), value.identity(), value.state(),
				value.applicability(), value.companyType(), ListCopy.of(value.reasonCodes()),
				value.coreInvocationAuthorized(), value.manifestContentHash(),
				value.inputSealContentHash(), value.decisionCutoff(),
				value.sealedIngestionCutoff(), value.modelEvidenceLabel(), value.claimCeiling(),
				value.riskCapCeiling(), assessmentPresent
						? value.deterministicAssessment().deepCopy() : null, false, false);
	}

	private static boolean validIdentity(FundamentalValueContract.DecisionIdentity identity) {
		return identity != null && identity.securityId() != null && identity.companyId() != null
				&& identity.instrumentId() != null && identity.shareClassId() != null
				&& identity.listingId() != null && identity.tickerAssignmentId() != null
				&& identity.completedSessionDate() != null && identity.ticker() != null
				&& identity.ticker().matches("[A-Z0-9][A-Z0-9.-]{0,31}")
				&& identity.mic() != null && identity.mic().matches("[A-Z0-9]{4}")
				&& identity.currency() != null && identity.currency().matches("[A-Z]{3}");
	}

	private static FundamentalValueGatewayException upstreamInvalid() {
		return new FundamentalValueGatewayException(
				"FUNDAMENTAL_VALUE_UPSTREAM_CONTRACT_INVALID",
				"The analytics response violates the Fundamental Value contract.", 502);
	}

	private static boolean validClaimCap(String claim, String capText) {
		BigDecimal cap = new BigDecimal(capText);
		if ("BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY".equals(claim)) {
			return cap.compareTo(BigDecimal.ZERO) == 0;
		}
		return !"LIMITED_MISSING_ADVANCED_EVIDENCE".equals(claim)
				|| cap.compareTo(new BigDecimal("0.01")) <= 0;
	}

	private static boolean validCap(String text) {
		if (!DECIMAL.matcher(text).matches()) {
			return false;
		}
		return Set.of("0", "0.01", "0.02").contains(text);
	}

	private static boolean validAssessment(JsonNode value, InternalDecision root) {
		if (value == null || !value.isObject()) {
			return false;
		}
		Set<String> top = Set.of("companyType", "applicability", "referencePrice",
				"currency", "projectionYears", "companyQuality", "financialResilience",
				"earningsAndCashFlowQuality", "capitalAllocationQuality", "valuations",
				"fairValue", "marginOfSafety", "expectedReturn", "downsideRisk",
				"claimCeiling", "thesisEvidence", "counterThesisEvidence",
				"invalidationConditions", "riskCap", "modelEvidenceLabel", "modelVersion",
				"strategyVersion", "formulaVersion", "aggregationVersion",
				"riskPolicyVersion", "assumptionPolicyVersion", "inputHash", "contentHash",
				"deterministicRankingAuthorized", "finalPortfolioWeightAuthorized",
				"automaticBrokerageExecutionAuthorized");
		if (!exact(value, top)
				|| !"MATURE_OPERATING_COMPANY".equals(text(value, "companyType"))
				|| !"APPLICABLE".equals(text(value, "applicability"))
				|| !value.get("currency").isTextual()
				|| !value.get("currency").asText().matches("[A-Z]{3}")
				|| !value.get("projectionYears").isIntegralNumber()
				|| !value.get("projectionYears").canConvertToInt()
				|| value.get("projectionYears").asInt() < 3
				|| value.get("projectionYears").asInt() > 10
				|| !"NOT_VALIDATED".equals(text(value, "modelEvidenceLabel"))
				|| !root.companyType().equals(text(value, "companyType"))
				|| !root.applicability().equals(text(value, "applicability"))
				|| !root.modelEvidenceLabel().equals(text(value, "modelEvidenceLabel"))
				|| !root.claimCeiling().equals(text(value, "claimCeiling"))
				|| !root.identity().currency().equals(text(value, "currency"))
				|| !"FUNDAMENTAL-VALUE-v1.0.0".equals(text(value, "modelVersion"))
				|| !"LONG-TERM-CORE-v1.0.0".equals(text(value, "strategyVersion"))
				|| !"fundamental-value-formulas-v1.1.0".equals(text(value, "formulaVersion"))
				|| !"FUNDAMENTAL-VALUE-WEIGHTED-MEDIAN-QUANTILE-v1.0.0"
						.equals(text(value, "aggregationVersion"))
				|| !"LONG-TERM-CORE-RISK-CAP-TIERS-v1.0.0"
						.equals(text(value, "riskPolicyVersion"))
				|| !"fundamental-value-assumptions-v1.1.0"
						.equals(text(value, "assumptionPolicyVersion"))
				|| !hash(value.get("inputHash")) || !hash(value.get("contentHash"))
				|| !validContentHash(value)
				|| !falseNode(value, "deterministicRankingAuthorized")
				|| !falseNode(value, "finalPortfolioWeightAuthorized")
				|| !falseNode(value, "automaticBrokerageExecutionAuthorized")) {
			return false;
		}
		return validPositiveReferencePrice(value.get("referencePrice"))
				&& dimensions(value)
				&& ranges(value)
				&& valuations(value.get("valuations"))
				&& conditions(value.get("thesisEvidence"), java.util.List.of(
						new ConditionSpec("QUALITY_AT_LEAST_65", "65", Comparison.AT_LEAST),
						new ConditionSpec("RESILIENCE_AT_LEAST_60", "60", Comparison.AT_LEAST),
						new ConditionSpec("CONSERVATIVE_MARGIN_OF_SAFETY_AT_LEAST_15_PERCENT",
								"0.15", Comparison.AT_LEAST)))
				&& conditions(value.get("counterThesisEvidence"), java.util.List.of(
						new ConditionSpec("DOWNSIDE_RISK_AT_LEAST_60", "60", Comparison.AT_LEAST),
						new ConditionSpec("NET_DEBT_TO_EBITDA_ABOVE_3", "3", Comparison.ABOVE)))
				&& conditions(value.get("invalidationConditions"), java.util.List.of(
						new ConditionSpec("ROIC_BELOW_8_PERCENT", "0.08", Comparison.BELOW),
						new ConditionSpec("INTEREST_COVERAGE_BELOW_3", "3", Comparison.BELOW),
						new ConditionSpec("CENTRAL_MARGIN_OF_SAFETY_BELOW_ZERO", "0",
								Comparison.BELOW)))
				&& conditionSources(value)
				&& validRiskCap(value.get("riskCap"), root.riskCapCeiling());
	}

	private static boolean validAssessmentId(JsonNode value, InternalDecision root) {
		try {
			return root.assessmentId().equals(deterministicAssessmentId(
					root.assemblyId(), text(value, "contentHash")));
		}
		catch (NoSuchAlgorithmException | RuntimeException exception) {
			return false;
		}
	}

	private static boolean dimensions(JsonNode value) {
		Set<String> shape = Set.of("state", "score", "reasonCodes");
		return validDimension(value.get("companyQuality"), shape)
				&& validDimension(value.get("financialResilience"), shape)
				&& validDimension(value.get("earningsAndCashFlowQuality"), shape)
				&& validDimension(value.get("capitalAllocationQuality"), shape)
				&& validDimension(value.get("downsideRisk"), shape);
	}

	private static boolean ranges(JsonNode value) {
		Set<String> shape = Set.of("state", "low", "central", "high", "reasonCodes");
		return validPositiveRange(value.get("fairValue"), shape)
				&& validRange(value.get("marginOfSafety"), shape)
				&& validRange(value.get("expectedReturn"), shape);
	}

	private static boolean valuations(JsonNode values) {
		if (values == null || !values.isArray() || values.size() != 4) {
			return false;
		}
		Set<String> shape = Set.of("method", "state", "low", "central", "high",
				"reasonCodes", "terminalValueShare");
		java.util.List<String> expected = java.util.List.of("FCFF_DCF",
				"NORMALIZED_OWNER_EARNINGS", "EARNINGS_POWER", "COMPARABLE_CROSS_CHECK");
		for (int index = 0; index < expected.size(); index++) {
			JsonNode item = values.get(index);
			if (!exact(item, shape) || !expected.get(index).equals(text(item, "method"))
					|| !validValuationValues(item)
					|| !validTerminalShare(item, index == 0)) {
				return false;
			}
		}
		return true;
	}

	private static boolean conditions(JsonNode values, java.util.List<ConditionSpec> specs) {
		if (values == null || !values.isArray() || values.size() != specs.size()) {
			return false;
		}
		Set<String> shape = Set.of("code", "state", "observedValue", "threshold",
				"satisfied", "reasonCodes");
		for (int index = 0; index < specs.size(); index++) {
			JsonNode item = values.get(index);
			ConditionSpec spec = specs.get(index);
			if (!exact(item, shape) || !textNode(item.get("code"))
					|| !spec.code().equals(item.get("code").asText())
					|| !validStateValues(item, "observedValue", "satisfied")
					|| !textNode(item.get("threshold"))
					|| !spec.threshold().equals(item.get("threshold").asText())) {
				return false;
			}
			if ("VALID".equals(text(item, "state"))) {
				BigDecimal observed = new BigDecimal(item.get("observedValue").asText());
				BigDecimal threshold = new BigDecimal(spec.threshold());
				boolean expected = spec.comparison().test(observed, threshold);
				if (item.get("satisfied").asBoolean() != expected) return false;
			}
		}
		return true;
	}

	private static boolean conditionSources(JsonNode value) {
		JsonNode thesis = value.get("thesisEvidence");
		JsonNode counter = value.get("counterThesisEvidence");
		JsonNode invalidations = value.get("invalidationConditions");
		return conditionSource(thesis.get(0), value.get("companyQuality"), "score")
				&& conditionSource(thesis.get(1), value.get("financialResilience"), "score")
				&& conditionSource(thesis.get(2), value.get("marginOfSafety"), "low")
				&& conditionSource(counter.get(0), value.get("downsideRisk"), "score")
				&& conditionSource(invalidations.get(2), value.get("marginOfSafety"), "central");
	}

	private static boolean conditionSource(JsonNode condition, JsonNode source,
			String sourceField) {
		return condition.get("state").equals(source.get("state"))
				&& condition.get("observedValue").equals(source.get(sourceField))
				&& condition.get("reasonCodes").equals(source.get("reasonCodes"));
	}

	private record ConditionSpec(String code, String threshold, Comparison comparison) {
	}

	private enum Comparison {
		AT_LEAST, ABOVE, BELOW;

		boolean test(BigDecimal observed, BigDecimal threshold) {
			int comparison = observed.compareTo(threshold);
			return switch (this) {
				case AT_LEAST -> comparison >= 0;
				case ABOVE -> comparison > 0;
				case BELOW -> comparison < 0;
			};
		}
	}

	private static boolean validRoutingOutcome(InternalDecision value) {
		String companyType = value.companyType();
		String applicability = value.applicability();
		if (companyType == null) return false;
		return switch (companyType) {
			case "MATURE_OPERATING_COMPANY" -> "APPLICABLE".equals(applicability);
			case "BANK", "INSURER", "REIT", "RESOURCE", "BIOTECHNOLOGY", "FINANCIAL",
					"INCOMPATIBLE_CONGLOMERATE" ->
					"SPECIALIZED_MODEL_REQUIRED".equals(applicability)
							&& "NOT_APPLICABLE".equals(value.state())
							&& exactReasons(value, "APPLICABILITY_SPECIALIZED_MODEL_REQUIRED");
			case "BENCHMARK" -> "NOT_APPLICABLE".equals(applicability)
					&& "NOT_APPLICABLE".equals(value.state())
					&& exactReasons(value, "APPLICABILITY_NOT_APPLICABLE");
			case "INSUFFICIENT_PUBLIC_HISTORY" -> "INSUFFICIENT_EVIDENCE".equals(applicability)
					&& "MISSING".equals(value.state())
					&& exactReasons(value, "APPLICABILITY_INSUFFICIENT_EVIDENCE");
			default -> false;
		};
	}

	private static boolean exactReasons(InternalDecision value, String reason) {
		return value.reasonCodes() != null && value.reasonCodes().equals(java.util.List.of(reason));
	}

	private static boolean validMetric(JsonNode value) {
		if (!exact(value, Set.of("state", "value", "reasonCode"))) return false;
		if (!validState(value)) return false;
		boolean valid = "VALID".equals(text(value, "state"));
		return valid ? decimalNode(value.get("value"), true) && value.get("reasonCode").isNull()
				: value.get("value").isNull() && textNode(value.get("reasonCode"));
	}

	private static boolean validDimension(JsonNode value, Set<String> shape) {
		if (!exact(value, shape) || !validState(value)) return false;
		boolean valid = "VALID".equals(text(value, "state"));
		return valid ? boundedDecimal(value.get("score"), BigDecimal.ZERO, new BigDecimal("100"))
				&& emptyReasons(value.get("reasonCodes"))
				: value.get("score").isNull() && nonemptyReasons(value.get("reasonCodes"));
	}

	private static boolean validRange(JsonNode value, Set<String> shape) {
		return exact(value, shape) && validState(value) && validRangeValues(value);
	}

	private static boolean validPositiveRange(JsonNode value, Set<String> shape) {
		return validRange(value, shape) && (!"VALID".equals(text(value, "state"))
				|| new BigDecimal(value.get("low").asText()).compareTo(BigDecimal.ZERO) > 0);
	}

	private static boolean validValuationValues(JsonNode value) {
		return validState(value) && validRangeValues(value)
				&& (!"VALID".equals(text(value, "state"))
						|| new BigDecimal(value.get("low").asText()).compareTo(BigDecimal.ZERO) > 0);
	}

	private static boolean validRangeValues(JsonNode value) {
		boolean valid = "VALID".equals(text(value, "state"));
		if (!valid) return value.get("low").isNull() && value.get("central").isNull()
				&& value.get("high").isNull() && nonemptyReasons(value.get("reasonCodes"));
		if (!decimalNode(value.get("low"), true) || !decimalNode(value.get("central"), true)
				|| !decimalNode(value.get("high"), true) || !emptyReasons(value.get("reasonCodes"))) {
			return false;
		}
		BigDecimal low = new BigDecimal(value.get("low").asText());
		BigDecimal central = new BigDecimal(value.get("central").asText());
		BigDecimal high = new BigDecimal(value.get("high").asText());
		return low.compareTo(central) <= 0 && central.compareTo(high) <= 0;
	}

	private static boolean validTerminalShare(JsonNode value, boolean fcff) {
		JsonNode share = value.get("terminalValueShare");
		if (!"VALID".equals(text(value, "state"))) return share.isNull();
		return fcff
				? boundedDecimal(share, BigDecimal.ZERO, MAXIMUM_DCF_TERMINAL_VALUE_SHARE)
				: share.isNull();
	}

	private static boolean validStateValues(JsonNode value, String numeric, String bool) {
		if (!validState(value)) return false;
		boolean valid = "VALID".equals(text(value, "state"));
		return valid ? decimalNode(value.get(numeric), true) && value.get(bool).isBoolean()
				&& emptyReasons(value.get("reasonCodes"))
				: value.get(numeric).isNull() && value.get(bool).isNull()
				&& nonemptyReasons(value.get("reasonCodes"));
	}

	private static boolean validState(JsonNode value) {
		return value != null && STATES.contains(text(value, "state"));
	}

	private static boolean validPositiveReferencePrice(JsonNode value) {
		return validMetric(value) && "VALID".equals(text(value, "state"))
				&& new BigDecimal(value.get("value").asText()).compareTo(BigDecimal.ZERO) > 0;
	}

	private static boolean validRiskCap(JsonNode value, String rootCap) {
		return exact(value, Set.of("ceiling", "bindingReasons"))
				&& rootCap.equals(text(value, "ceiling"))
				&& nonemptyReasons(value.get("bindingReasons"));
	}

	private static boolean decimalNode(JsonNode value, boolean signed) {
		if (value == null || !value.isTextual()) return false;
		String text = value.asText();
		if (!(signed ? SIGNED_DECIMAL : DECIMAL).matcher(text).matches()) return false;
		return new BigDecimal(text).compareTo(BigDecimal.ZERO) != 0 || "0".equals(text);
	}

	private static boolean boundedDecimal(JsonNode value, BigDecimal low, BigDecimal high) {
		if (!decimalNode(value, false)) return false;
		BigDecimal number = new BigDecimal(value.asText());
		return number.compareTo(low) >= 0 && number.compareTo(high) <= 0;
	}

	private static boolean textNode(JsonNode value) {
		return value != null && value.isTextual() && !value.asText().isBlank();
	}

	private static boolean emptyReasons(JsonNode value) {
		return value != null && value.isArray() && value.isEmpty();
	}

	private static boolean nonemptyReasons(JsonNode value) {
		if (value == null || !value.isArray() || value.isEmpty()) return false;
		for (JsonNode item : value) if (!textNode(item)) return false;
		return true;
	}

	private static boolean exact(JsonNode value, Set<String> fields) {
		return value != null && value.isObject()
				&& Set.copyOf(value.propertyNames()).equals(fields);
	}

	private static String text(JsonNode value, String field) {
		JsonNode node = value.get(field);
		return node != null && node.isTextual() ? node.asText() : null;
	}

	private static boolean hash(JsonNode value) {
		return value != null && value.isTextual() && HASH.matcher(value.asText()).matches();
	}

	private static boolean falseNode(JsonNode value, String field) {
		JsonNode node = value.get(field);
		return node != null && node.isBoolean() && !node.asBoolean();
	}

	private static boolean validContentHash(JsonNode value) {
		try {
			return canonicalContentHash(value).equals(value.get("contentHash").asText());
		}
		catch (NoSuchAlgorithmException | RuntimeException exception) {
			return false;
		}
	}

	static String canonicalContentHash(JsonNode value) throws NoSuchAlgorithmException {
		Object canonical = canonical(value, true);
		byte[] encoded = CANONICAL_MAPPER.writeValueAsBytes(canonical);
		return "sha256:" + HexFormat.of().formatHex(
				MessageDigest.getInstance("SHA-256").digest(encoded));
	}

	static UUID deterministicAssessmentId(UUID assemblyId, String contentHash)
			throws NoSuchAlgorithmException {
		MessageDigest digest = MessageDigest.getInstance("SHA-1");
		ByteBuffer namespace = ByteBuffer.allocate(16);
		namespace.putLong(URL_NAMESPACE.getMostSignificantBits());
		namespace.putLong(URL_NAMESPACE.getLeastSignificantBits());
		digest.update(namespace.array());
		digest.update((ASSESSMENT_PERSISTENCE_VERSION + ":" + assemblyId + ":" + contentHash)
				.getBytes(StandardCharsets.UTF_8));
		byte[] bytes = digest.digest();
		bytes[6] = (byte) ((bytes[6] & 0x0f) | 0x50);
		bytes[8] = (byte) ((bytes[8] & 0x3f) | 0x80);
		ByteBuffer result = ByteBuffer.wrap(bytes);
		return new UUID(result.getLong(), result.getLong());
	}

	private static Object canonical(JsonNode value, boolean root) {
		if (value.isObject()) {
			Map<String, Object> result = new TreeMap<>();
			for (var entry : value.properties()) {
				if (root && "contentHash".equals(entry.getKey())) continue;
				result.put(snake(entry.getKey()), canonical(entry.getValue(), false));
			}
			return result;
		}
		if (value.isArray()) {
			var result = new ArrayList<>();
			value.forEach(item -> result.add(canonical(item, false)));
			return result;
		}
		if (value.isTextual()) return value.asText();
		if (value.isBoolean()) return value.asBoolean();
		if (value.isIntegralNumber()) return value.asInt();
		if (value.isNull()) return null;
		throw new IllegalArgumentException("Non-canonical assessment scalar");
	}

	private static String snake(String value) {
		return value.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase(java.util.Locale.ROOT);
	}

	private static final class ListCopy {
		private ListCopy() {
		}

		static <T> java.util.List<T> of(java.util.List<T> values) {
			return values == null ? java.util.List.of() : java.util.List.copyOf(values);
		}
	}
}
