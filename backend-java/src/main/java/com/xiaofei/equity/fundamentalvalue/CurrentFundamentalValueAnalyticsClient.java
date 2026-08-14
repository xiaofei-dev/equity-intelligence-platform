package com.xiaofei.equity.fundamentalvalue;

import java.time.Duration;
import java.util.Set;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import com.xiaofei.equity.fundamentalvalue.CurrentFundamentalValueContract.InternalAssessment;

@Service
public class CurrentFundamentalValueAnalyticsClient {

	static final String INTERNAL_ROOT =
			"/internal/v1/fundamental-value/current-assessments";
	private static final JsonMapper STRICT_MAPPER = JsonMapper.builder()
			.enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES).build();

	private final RestClient restClient;

	@Autowired
	public CurrentFundamentalValueAnalyticsClient(
			@Value("${analytics.base-url:${ANALYTICS_BASE_URL:http://localhost:8000}}")
			String analyticsBaseUrl,
			@Value("${analytics.connect-timeout:2s}") Duration connectTimeout,
			@Value("${analytics.read-timeout:30s}") Duration readTimeout) {
		var requestFactory = new SimpleClientHttpRequestFactory();
		requestFactory.setConnectTimeout(connectTimeout);
		requestFactory.setReadTimeout(readTimeout);
		this.restClient = RestClient.builder().baseUrl(analyticsBaseUrl)
				.requestFactory(requestFactory).build();
	}

	CurrentFundamentalValueAnalyticsClient(RestClient restClient) {
		this.restClient = restClient;
	}

	InternalAssessment read(UUID assessmentId) {
		return readPath(INTERNAL_ROOT + "/{assessmentId}", assessmentId);
	}

	InternalAssessment readLatest(String symbol) {
		return readPath(INTERNAL_ROOT + "/latest/{symbol}", symbol);
	}

	private InternalAssessment readPath(String path, Object pathValue) {
		try {
			String body = restClient.get().uri(path, pathValue)
					.retrieve().body(String.class);
			if (body == null) throw unavailable();
			JsonNode root = STRICT_MAPPER.readTree(body);
			validateWire(root);
			return STRICT_MAPPER.readValue(body, InternalAssessment.class);
		}
		catch (RestClientResponseException exception) {
			throw switch (exception.getStatusCode().value()) {
				case 404 -> new FundamentalValueGatewayException(
						"CURRENT_FUNDAMENTAL_VALUE_ASSESSMENT_NOT_FOUND",
						"The current Fundamental Value assessment was not found.", 404);
				case 409 -> new FundamentalValueGatewayException(
						"CURRENT_FUNDAMENTAL_VALUE_INTEGRITY_CONFLICT",
						"The immutable current assessment conflicts.", 409);
				case 422 -> new FundamentalValueGatewayException(
						"INVALID_CURRENT_FUNDAMENTAL_VALUE_IDENTIFIER",
						"The current assessment identifier is invalid.", 400);
				default -> unavailable();
			};
		}
		catch (FundamentalValueGatewayException exception) {
			throw exception;
		}
		catch (RestClientException exception) {
			throw unavailable();
		}
		catch (RuntimeException exception) {
			throw invalidUpstream();
		}
	}

	private static void validateWire(JsonNode root) {
		Set<String> expected = Set.of(
				"contractVersion", "assessmentId", "assessmentContentHash", "identity",
				"decisionCutoff", "priceSessionDate", "latestFundamentalPeriodEnd",
				"evidenceTrack", "claimCeiling", "modelEvidenceLabel", "versions",
				"referencePrice", "companyQuality", "financialResilience",
				"earningsAndCashFlowQuality", "capitalAllocationQuality", "downsideRisk",
				"valuations", "fairValue", "marginOfSafety", "expectedReturn", "riskCap",
				"investmentView", "deterministicActionAuthorized",
				"deterministicRankingAuthorized", "finalPortfolioWeightAuthorized",
				"automaticBrokerageExecutionAuthorized");
		if (root == null || !root.isObject()
				|| !Set.copyOf(root.propertyNames()).equals(expected)
				|| !text(root, "contractVersion") || !uuid(root.get("assessmentId"))
				|| !text(root, "assessmentContentHash") || !identity(root.get("identity"))
				|| !text(root, "decisionCutoff") || !text(root, "priceSessionDate")
				|| !text(root, "latestFundamentalPeriodEnd") || !text(root, "evidenceTrack")
				|| !text(root, "claimCeiling") || !text(root, "modelEvidenceLabel")
				|| !object(root, "versions") || !object(root, "referencePrice")
				|| !object(root, "companyQuality") || !object(root, "financialResilience")
				|| !object(root, "earningsAndCashFlowQuality")
				|| !object(root, "capitalAllocationQuality") || !object(root, "downsideRisk")
				|| !root.get("valuations").isArray() || !object(root, "fairValue")
				|| !object(root, "marginOfSafety") || !object(root, "expectedReturn")
				|| !object(root, "riskCap") || !object(root, "investmentView")) {
			throw new IllegalArgumentException("Invalid current assessment wire shape");
		}
		for (String flag : Set.of("deterministicActionAuthorized",
				"deterministicRankingAuthorized", "finalPortfolioWeightAuthorized",
				"automaticBrokerageExecutionAuthorized")) {
			if (!root.get(flag).isBoolean()) throw new IllegalArgumentException("Invalid authority");
		}
	}

	private static boolean identity(JsonNode value) {
		if (value == null || !value.isObject() || !Set.copyOf(value.propertyNames()).equals(
				Set.of("securityId", "companyId", "instrumentId", "shareClassId",
						"listingId", "tickerAssignmentId", "ticker", "mic", "currency"))) return false;
		for (String field : Set.of("securityId", "companyId", "instrumentId", "shareClassId",
				"listingId", "tickerAssignmentId")) if (!uuid(value.get(field))) return false;
		return text(value, "ticker") && text(value, "mic") && text(value, "currency");
	}

	private static boolean object(JsonNode root, String field) {
		return root.get(field) != null && root.get(field).isObject();
	}

	private static boolean text(JsonNode root, String field) {
		return root.get(field) != null && root.get(field).isTextual()
				&& !root.get(field).asText().isBlank();
	}

	private static boolean uuid(JsonNode value) {
		if (value == null || !value.isTextual()) return false;
		try {
			return UUID.fromString(value.asText()).toString().equals(value.asText());
		}
		catch (IllegalArgumentException exception) {
			return false;
		}
	}

	private static FundamentalValueGatewayException invalidUpstream() {
		return new FundamentalValueGatewayException(
				"CURRENT_FUNDAMENTAL_VALUE_UPSTREAM_CONTRACT_INVALID",
				"The analytics response violates the current assessment contract.", 502);
	}

	private static FundamentalValueGatewayException unavailable() {
		return new FundamentalValueGatewayException(
				"ANALYTICS_SERVICE_UNAVAILABLE",
				"The analytics service is temporarily unavailable.", 502);
	}
}
