package com.xiaofei.equity.fundamentalvalue;

import java.time.Duration;
import java.util.Set;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

import com.xiaofei.equity.fundamentalvalue.FundamentalValueContract.DecisionRequest;
import com.xiaofei.equity.fundamentalvalue.FundamentalValueContract.InternalDecision;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@Service
public class FundamentalValueAnalyticsClient {

	static final String INTERNAL_ROOT = "/internal/v1/fundamental-value/decisions";
	private static final JsonMapper STRICT_MAPPER = JsonMapper.builder()
			.enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES).build();

	private final RestClient restClient;

	@Autowired
	public FundamentalValueAnalyticsClient(
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

	FundamentalValueAnalyticsClient(RestClient restClient) {
		this.restClient = restClient;
	}

	InternalDecision create(DecisionRequest request, String idempotencyKey) {
		return call(() -> parse(restClient.post().uri(INTERNAL_ROOT)
				.header("Idempotency-Key", idempotencyKey)
				.contentType(MediaType.APPLICATION_JSON).body(request).retrieve()
				.body(String.class)), true);
	}

	InternalDecision read(UUID assemblyId) {
		return call(() -> parse(restClient.get()
				.uri(INTERNAL_ROOT + "/{assemblyId}", assemblyId)
				.retrieve().body(String.class)), false);
	}

	private static InternalDecision parse(String body) {
		if (body == null) {
			throw unavailable();
		}
		try {
			validateWire(STRICT_MAPPER.readTree(body));
			return STRICT_MAPPER.readValue(body, InternalDecision.class);
		}
		catch (RuntimeException exception) {
			throw new FundamentalValueGatewayException(
					"FUNDAMENTAL_VALUE_UPSTREAM_CONTRACT_INVALID",
					"The analytics response violates the Fundamental Value contract.", 502);
		}
	}

	private static void validateWire(JsonNode root) {
		Set<String> expected = Set.of("contractVersion", "assemblyId", "assessmentId",
				"identity",
				"state", "applicability", "companyType", "reasonCodes",
				"coreInvocationAuthorized", "manifestContentHash", "inputSealContentHash",
				"decisionCutoff", "sealedIngestionCutoff", "modelEvidenceLabel",
				"claimCeiling", "riskCapCeiling", "deterministicAssessment",
				"finalPortfolioWeightAuthorized", "automaticBrokerageExecutionAuthorized");
		if (!root.isObject() || !Set.copyOf(root.propertyNames()).equals(expected)
				|| !text(root, "contractVersion") || !uuid(root.get("assemblyId"))
				|| !(root.get("assessmentId").isNull() || root.get("assessmentId").isTextual())
				|| root.get("assessmentId").isTextual() && !uuid(root.get("assessmentId"))
				|| !text(root, "state") || !text(root, "applicability")
				|| !text(root, "companyType") || !text(root, "manifestContentHash")
				|| !text(root, "inputSealContentHash") || !text(root, "decisionCutoff")
				|| !text(root, "sealedIngestionCutoff")
				|| !nullableText(root, "modelEvidenceLabel")
				|| !nullableText(root, "claimCeiling")
				|| !root.get("coreInvocationAuthorized").isBoolean()
				|| !root.get("finalPortfolioWeightAuthorized").isBoolean()
				|| !root.get("automaticBrokerageExecutionAuthorized").isBoolean()
				|| !root.get("reasonCodes").isArray()
				|| !(root.get("riskCapCeiling").isNull()
						|| root.get("riskCapCeiling").isTextual())
				|| !identity(root.get("identity"))
				|| !(root.get("deterministicAssessment").isNull()
						|| root.get("deterministicAssessment").isObject())) {
			throw new IllegalArgumentException("Invalid Fundamental Value wire shape");
		}
		for (JsonNode reason : root.get("reasonCodes")) {
			if (!reason.isTextual() || reason.asText().isBlank()) {
				throw new IllegalArgumentException("Invalid Fundamental Value reason");
			}
		}
	}

	private static boolean identity(JsonNode value) {
		if (value == null || !value.isObject()
				|| !Set.copyOf(value.propertyNames()).equals(Set.of(
						"securityId", "companyId", "instrumentId", "shareClassId",
						"listingId", "tickerAssignmentId", "ticker", "mic", "currency",
						"completedSessionDate"))) return false;
		for (String field : Set.of("securityId", "companyId", "instrumentId", "shareClassId",
				"listingId", "tickerAssignmentId")) if (!uuid(value.get(field))) return false;
		if (!text(value, "ticker") || !text(value, "mic") || !text(value, "currency")
				|| !text(value, "completedSessionDate")
				|| !value.get("ticker").asText().matches("[A-Z0-9][A-Z0-9.-]{0,31}")
				|| !value.get("mic").asText().matches("[A-Z0-9]{4}")
				|| !value.get("currency").asText().matches("[A-Z]{3}")) return false;
		try {
			java.time.LocalDate parsed = java.time.LocalDate.parse(
					value.get("completedSessionDate").asText());
			return parsed.toString().equals(value.get("completedSessionDate").asText());
		}
		catch (java.time.format.DateTimeParseException exception) {
			return false;
		}
	}

	private static boolean text(JsonNode root, String field) {
		JsonNode value = root.get(field);
		return value != null && value.isTextual() && !value.asText().isBlank();
	}

	private static boolean nullableText(JsonNode root, String field) {
		JsonNode value = root.get(field);
		return value != null && (value.isNull()
				|| value.isTextual() && !value.asText().isBlank());
	}

	private static boolean uuid(JsonNode value) {
		if (value == null || !value.isTextual()) return false;
		try {
			UUID parsed = UUID.fromString(value.asText());
			return parsed.toString().equals(value.asText());
		}
		catch (IllegalArgumentException exception) {
			return false;
		}
	}

	private static InternalDecision call(AnalyticsCall call, boolean creating) {
		try {
			InternalDecision response = call.execute();
			if (response == null) {
				throw unavailable();
			}
			return response;
		}
		catch (RestClientResponseException exception) {
			throw switch (exception.getStatusCode().value()) {
				case 400, 422 -> new FundamentalValueGatewayException(
						"INVALID_FUNDAMENTAL_VALUE_REQUEST",
						"The Fundamental Value request is invalid.", 400);
				case 404 -> creating
						? new FundamentalValueGatewayException(
								"FUNDAMENTAL_VALUE_REFERENCE_NOT_FOUND",
								"A Fundamental Value evidence reference was not found.", 404)
						: new FundamentalValueGatewayException(
								"FUNDAMENTAL_VALUE_DECISION_NOT_FOUND",
								"The Fundamental Value decision was not found.", 404);
				case 409 -> new FundamentalValueGatewayException(
						"FUNDAMENTAL_VALUE_PERSISTENCE_CONFLICT",
						"The Fundamental Value immutable record conflicts.", 409);
				case 503 -> new FundamentalValueGatewayException(
						"FUNDAMENTAL_VALUE_EVIDENCE_UNAVAILABLE",
						"Fundamental Value evidence is unavailable.", 503);
				default -> unavailable();
			};
		}
		catch (RestClientException exception) {
			throw unavailable();
		}
	}

	private static FundamentalValueGatewayException unavailable() {
		return new FundamentalValueGatewayException(
				"ANALYTICS_SERVICE_UNAVAILABLE",
				"The analytics service is temporarily unavailable.", 502);
	}

	@FunctionalInterface
	private interface AnalyticsCall {
		InternalDecision execute();
	}
}
