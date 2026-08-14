package com.xiaofei.equity.fundamentalvalue;

import java.math.BigDecimal;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

import org.springframework.stereotype.Service;

import tools.jackson.databind.JsonNode;

import com.xiaofei.equity.fundamentalvalue.CurrentFundamentalValueContract.AssessmentResponse;
import com.xiaofei.equity.fundamentalvalue.CurrentFundamentalValueContract.InternalAssessment;

@Service
public class CurrentFundamentalValueService {

	private static final Pattern HASH = Pattern.compile("sha256:[0-9a-f]{64}");
	private static final Pattern DECIMAL = Pattern.compile("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?");
	private static final UUID URL_NAMESPACE = UUID.fromString(
			"6ba7b811-9dad-11d1-80b4-00c04fd430c8");
	private static final String PERSISTENCE_VERSION =
			"FV-CURRENT-ASSESSMENT-PERSISTENCE-v1.0.0";
	private static final List<String> METHODS = List.of(
			"FCFF_DCF", "NORMALIZED_OWNER_EARNINGS", "EARNINGS_POWER",
			"COMPARABLE_CROSS_CHECK");
	private static final Set<String> CATEGORIES = Set.of(
			"ATTRACTIVE_FOR_FURTHER_RESEARCH",
			"WATCHLIST_QUALITY_PRICE_NOT_ATTRACTIVE", "HIGH_RISK_OR_WEAK_QUALITY",
			"NEUTRAL_RESEARCH_REQUIRED", "INSUFFICIENT_EVIDENCE");

	private final CurrentFundamentalValueAnalyticsClient client;

	public CurrentFundamentalValueService(CurrentFundamentalValueAnalyticsClient client) {
		this.client = client;
	}

	public AssessmentResponse read(UUID assessmentId) {
		return project(client.read(assessmentId), assessmentId, null);
	}

	public AssessmentResponse readLatest(String symbol) {
		if (symbol == null || !symbol.matches("[A-Z][A-Z0-9.-]{0,31}")) {
			throw new FundamentalValueGatewayException(
					"INVALID_CURRENT_FUNDAMENTAL_VALUE_SYMBOL",
					"The current assessment symbol is invalid.", 400);
		}
		return project(client.readLatest(symbol), null, symbol);
	}

	private static AssessmentResponse project(
			InternalAssessment value, UUID requestedId, String expectedSymbol) {
		try {
			validate(value, requestedId, expectedSymbol);
			return new AssessmentResponse(
					value.contractVersion(), value.assessmentId(), value.assessmentContentHash(),
					value.identity(), value.decisionCutoff(), value.priceSessionDate(),
					value.latestFundamentalPeriodEnd(), value.evidenceTrack(), value.claimCeiling(),
					value.modelEvidenceLabel(), copy(value.versions()), copy(value.referencePrice()),
					copy(value.companyQuality()), copy(value.financialResilience()),
					copy(value.earningsAndCashFlowQuality()),
					copy(value.capitalAllocationQuality()), copy(value.downsideRisk()),
					copy(value.valuations()), copy(value.fairValue()), copy(value.marginOfSafety()),
					copy(value.expectedReturn()), copy(value.riskCap()), copy(value.investmentView()),
					false, false, false, false);
		}
		catch (RuntimeException | NoSuchAlgorithmException exception) {
			throw invalidUpstream();
		}
	}

	private static void validate(
			InternalAssessment value, UUID requestedId, String expectedSymbol)
			throws NoSuchAlgorithmException {
		if (value == null || !CurrentFundamentalValueContract.RESULT_VERSION.equals(
				value.contractVersion()) || value.assessmentId() == null
				|| requestedId != null && !value.assessmentId().equals(requestedId)
				|| value.assessmentContentHash() == null
				|| !HASH.matcher(value.assessmentContentHash()).matches()
				|| !value.assessmentId().equals(deterministicId(value.assessmentContentHash()))
				|| !validIdentity(value.identity())
				|| expectedSymbol != null && !expectedSymbol.equals(value.identity().ticker())
				|| value.decisionCutoff() == null
				|| value.priceSessionDate() == null || value.latestFundamentalPeriodEnd() == null
				|| value.latestFundamentalPeriodEnd().isAfter(value.priceSessionDate())
				|| value.priceSessionDate().isAfter(java.time.LocalDate.ofInstant(
						value.decisionCutoff(), java.time.ZoneOffset.UTC))
				|| !"EODHD_PROVIDER_NORMALIZED_CURRENT_REVISION_APPROXIMATION".equals(
						value.evidenceTrack())
				|| !"DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION".equals(
						value.claimCeiling())
				|| !"NOT_VALIDATED".equals(value.modelEvidenceLabel())
				|| value.deterministicActionAuthorized()
				|| value.deterministicRankingAuthorized()
				|| value.finalPortfolioWeightAuthorized()
				|| value.automaticBrokerageExecutionAuthorized()
				|| !versions(value.versions()) || !reference(value.referencePrice())
				|| !dimension(value.companyQuality()) || !dimension(value.financialResilience())
				|| !dimension(value.earningsAndCashFlowQuality())
				|| !dimension(value.capitalAllocationQuality()) || !dimension(value.downsideRisk())
				|| !valuations(value.valuations()) || !range(value.fairValue(), true, false)
				|| !range(value.marginOfSafety(), false, false)
				|| !range(value.expectedReturn(), false, false)
				|| !riskCap(value.riskCap()) || !investmentView(value.investmentView())) {
			throw new IllegalArgumentException("Invalid current assessment contract");
		}
	}

	private static boolean validIdentity(CurrentFundamentalValueContract.Identity identity) {
		return identity != null && identity.securityId() != null && identity.companyId() != null
				&& identity.instrumentId() != null && identity.shareClassId() != null
				&& identity.listingId() != null && identity.tickerAssignmentId() != null
				&& identity.ticker() != null
				&& identity.ticker().matches("[A-Z0-9][A-Z0-9.-]{0,31}")
				&& identity.mic() != null && identity.mic().matches("[A-Z0-9]{4}")
				&& identity.currency() != null && identity.currency().matches("[A-Z]{3}");
	}

	private static boolean versions(JsonNode value) {
		return exact(value, Set.of("producerVersion", "policyVersion", "modelVersion",
				"strategyVersion", "formulaVersion", "aggregationVersion",
				"riskPolicyVersion", "assumptionPolicyVersion"))
				&& text(value, "producerVersion", "FV-CURRENT-REVISION-PRODUCER-v1.0.0")
				&& text(value, "policyVersion", "FV-CURRENT-INVESTMENT-POLICY-v1.0.0")
				&& text(value, "modelVersion", "FUNDAMENTAL-VALUE-v1.0.0")
				&& text(value, "strategyVersion", "LONG-TERM-CORE-v1.0.0")
				&& text(value, "formulaVersion", "fundamental-value-formulas-v1.1.0")
				&& text(value, "aggregationVersion",
						"FUNDAMENTAL-VALUE-WEIGHTED-MEDIAN-QUANTILE-v1.0.0")
				&& text(value, "riskPolicyVersion",
						"LONG-TERM-CORE-RISK-CAP-TIERS-v1.0.0")
				&& text(value, "assumptionPolicyVersion",
						"fundamental-value-assumptions-v1.1.0");
	}

	private static boolean reference(JsonNode value) {
		return exact(value, Set.of("state", "value", "reasonCode"))
				&& text(value, "state", "VALID") && decimal(value.get("value"))
				&& new BigDecimal(value.get("value").asText()).signum() > 0
				&& value.get("reasonCode").isNull();
	}

	private static boolean dimension(JsonNode value) {
		if (!exact(value, Set.of("state", "score", "reasonCodes"))
				|| !text(value, "state", "VALID") || !decimal(value.get("score"))
				|| !emptyArray(value.get("reasonCodes"))) return false;
		BigDecimal score = new BigDecimal(value.get("score").asText());
		return score.signum() >= 0 && score.compareTo(new BigDecimal("100")) <= 0;
	}

	private static boolean valuations(JsonNode value) {
		if (value == null || !value.isArray() || value.size() != METHODS.size()) return false;
		for (int index = 0; index < METHODS.size(); index++) {
			JsonNode item = value.get(index);
			if (!exact(item, Set.of("method", "state", "low", "central", "high",
					"reasonCodes", "terminalValueShare"))
					|| !text(item, "method", METHODS.get(index))
					|| !range(item, true, true)) return false;
			JsonNode share = item.get("terminalValueShare");
			if (index == 0) {
				if (!decimal(share) || new BigDecimal(share.asText()).signum() < 0
						|| new BigDecimal(share.asText()).compareTo(new BigDecimal("0.80")) > 0) return false;
			}
			else if (!share.isNull()) return false;
		}
		return true;
	}

	private static boolean range(JsonNode value, boolean positive, boolean valuation) {
		Set<String> fields = valuation
				? Set.of("method", "state", "low", "central", "high", "reasonCodes",
						"terminalValueShare")
				: Set.of("state", "low", "central", "high", "reasonCodes");
		if (!exact(value, fields)
				|| !text(value, "state", "VALID") || !emptyArray(value.get("reasonCodes"))
				|| !decimal(value.get("low")) || !decimal(value.get("central"))
				|| !decimal(value.get("high"))) return false;
		BigDecimal low = new BigDecimal(value.get("low").asText());
		BigDecimal central = new BigDecimal(value.get("central").asText());
		BigDecimal high = new BigDecimal(value.get("high").asText());
		return low.compareTo(central) <= 0 && central.compareTo(high) <= 0
				&& (!positive || low.signum() > 0);
	}

	private static boolean riskCap(JsonNode value) {
		return exact(value, Set.of("ceiling", "bindingReasons"))
				&& value.get("ceiling").isTextual()
				&& Set.of("0", "0.01", "0.02").contains(value.get("ceiling").asText())
				&& nonBlankArray(value.get("bindingReasons"));
	}

	private static boolean investmentView(JsonNode value) {
		return exact(value, Set.of("state", "category", "reasonCodes"))
				&& text(value, "state", "VALID") && value.get("category").isTextual()
				&& CATEGORIES.contains(value.get("category").asText())
				&& nonBlankArray(value.get("reasonCodes"));
	}

	private static boolean exact(JsonNode value, Set<String> fields) {
		return value != null && value.isObject()
				&& Set.copyOf(value.propertyNames()).equals(fields);
	}

	private static boolean text(JsonNode value, String field, String expected) {
		return value.get(field) != null && value.get(field).isTextual()
				&& expected.equals(value.get(field).asText());
	}

	private static boolean decimal(JsonNode value) {
		return value != null && value.isTextual() && DECIMAL.matcher(value.asText()).matches()
				&& !(value.asText().startsWith("-0")
						&& new BigDecimal(value.asText()).signum() == 0);
	}

	private static boolean emptyArray(JsonNode value) {
		return value != null && value.isArray() && value.isEmpty();
	}

	private static boolean nonBlankArray(JsonNode value) {
		if (value == null || !value.isArray() || value.isEmpty()) return false;
		for (JsonNode item : value) if (!item.isTextual() || item.asText().isBlank()) return false;
		return true;
	}

	private static JsonNode copy(JsonNode value) {
		return value == null ? null : value.deepCopy();
	}

	static UUID deterministicId(String contentHash) throws NoSuchAlgorithmException {
		MessageDigest digest = MessageDigest.getInstance("SHA-1");
		ByteBuffer namespace = ByteBuffer.allocate(16);
		namespace.putLong(URL_NAMESPACE.getMostSignificantBits());
		namespace.putLong(URL_NAMESPACE.getLeastSignificantBits());
		digest.update(namespace.array());
		digest.update((PERSISTENCE_VERSION + ":" + contentHash).getBytes(StandardCharsets.UTF_8));
		byte[] bytes = digest.digest();
		bytes[6] = (byte) ((bytes[6] & 0x0f) | 0x50);
		bytes[8] = (byte) ((bytes[8] & 0x3f) | 0x80);
		ByteBuffer result = ByteBuffer.wrap(bytes);
		return new UUID(result.getLong(), result.getLong());
	}

	private static FundamentalValueGatewayException invalidUpstream() {
		return new FundamentalValueGatewayException(
				"CURRENT_FUNDAMENTAL_VALUE_UPSTREAM_CONTRACT_INVALID",
				"The analytics response violates the current assessment contract.", 502);
	}
}
