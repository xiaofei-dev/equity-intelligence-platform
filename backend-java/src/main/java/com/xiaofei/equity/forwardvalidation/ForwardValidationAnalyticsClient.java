package com.xiaofei.equity.forwardvalidation;

import java.time.Duration;
import java.util.Map;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.EnrollmentAccepted;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.EnrollmentRequest;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardExperimentAccepted;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardExperimentRequest;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardExperimentStatus;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardReport;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveEnrollmentAccepted;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveEnrollmentRequest;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@Service
public class ForwardValidationAnalyticsClient {

	private static final JsonMapper JSON_MAPPER = JsonMapper.builder().build();

	private final RestClient restClient;

	@Autowired
	public ForwardValidationAnalyticsClient(
			@Value("${analytics.base-url:${ANALYTICS_BASE_URL:http://localhost:8000}}")
			String analyticsBaseUrl,
			@Value("${analytics.connect-timeout:2s}") Duration connectTimeout,
			@Value("${analytics.read-timeout:30s}") Duration readTimeout) {
		var requestFactory = new SimpleClientHttpRequestFactory();
		requestFactory.setConnectTimeout(connectTimeout);
		requestFactory.setReadTimeout(readTimeout);
		this.restClient = RestClient.builder()
				.baseUrl(analyticsBaseUrl)
				.requestFactory(requestFactory)
				.build();
	}

	ForwardValidationAnalyticsClient(RestClient restClient) {
		this.restClient = restClient;
	}

	public ForwardExperimentAccepted createExperiment(
			ForwardExperimentRequest request, String idempotencyKey) {
		return call(() -> restClient.post()
				.uri("/internal/v1/forward-validation/experiments")
				.header("Idempotency-Key", idempotencyKey)
				.contentType(MediaType.APPLICATION_JSON)
				.body(request).retrieve().body(ForwardExperimentAccepted.class));
	}

	public ForwardExperimentStatus getExperiment(String experimentId) {
		return call(() -> restClient.get()
				.uri("/internal/v1/forward-validation/experiments/{id}", experimentId)
				.retrieve().body(ForwardExperimentStatus.class));
	}

	public EnrollmentAccepted createEnrollment(
			String experimentId, EnrollmentRequest request, String idempotencyKey) {
		return call(() -> restClient.post()
				.uri("/internal/v1/forward-validation/experiments/{id}/enrollments",
						experimentId)
				.header("Idempotency-Key", idempotencyKey)
				.contentType(MediaType.APPLICATION_JSON)
				.body(request).retrieve().body(EnrollmentAccepted.class));
	}

	public java.util.List<Map<String, Object>> getRows(String experimentId, String projection) {
		return call(() -> restClient.get()
				.uri("/internal/v1/forward-validation/experiments/{id}/{projection}",
						experimentId, projection)
				.retrieve().body(new ParameterizedTypeReference<>() {
				}));
	}

	public ForwardReport getReport(String experimentId, String reportType) {
		return call(() -> restClient.get()
				.uri("/internal/v1/forward-validation/experiments/{id}/reports/{type}",
						experimentId, reportType)
				.retrieve().body(ForwardReport.class));
	}

	public ProspectiveEnrollmentAccepted createProspectiveEnrollment(
			ProspectiveEnrollmentRequest request, String idempotencyKey) {
		return prospectiveCall(() -> restClient.post()
				.uri("/internal/v1/forward-validation/prospective-enrollments")
				.header("Idempotency-Key", idempotencyKey)
				.contentType(MediaType.APPLICATION_JSON)
				.body(request)
				.retrieve()
				.body(ProspectiveEnrollmentAccepted.class));
	}

	public ProspectiveEnrollmentAccepted getProspectiveEnrollment(UUID attemptId) {
		return prospectiveCall(() -> restClient.get()
				.uri("/internal/v1/forward-validation/prospective-enrollments/{attemptId}",
						attemptId)
				.retrieve()
				.body(ProspectiveEnrollmentAccepted.class));
	}

	public ProspectiveEnrollmentAccepted getLatestProspectiveEnrollment() {
		return prospectiveCall(() -> restClient.get()
				.uri("/internal/v1/forward-validation/prospective-enrollments/latest")
				.retrieve()
				.body(ProspectiveEnrollmentAccepted.class));
	}

	private <T> T call(AnalyticsCall<T> call) {
		try {
			T response = call.execute();
			if (response == null) {
				throw new IllegalStateException("Analytics service returned an empty response");
			}
			return response;
		}
		catch (RestClientException exception) {
			throw new IllegalStateException("Forward-validation analytics request failed", exception);
		}
	}

	private <T> T prospectiveCall(AnalyticsCall<T> call) {
		try {
			T response = call.execute();
			if (response == null) {
				throw unavailable();
			}
			return response;
		}
		catch (RestClientResponseException exception) {
			throw switch (exception.getStatusCode().value()) {
				case 400, 422 -> invalidProspectiveRequest(exception);
				case 404 -> new ForwardValidationGatewayException(
						"PROSPECTIVE_ENROLLMENT_NOT_FOUND",
						"The prospective-enrollment attempt was not found.",
						404);
				case 409 -> new ForwardValidationGatewayException(
						"IDEMPOTENCY_KEY_CONFLICT",
						"The idempotency key was already used for a different request.",
						409);
				default -> unavailable();
			};
		}
		catch (RestClientException exception) {
			throw unavailable();
		}
	}

	private static ForwardValidationGatewayException invalidProspectiveRequest(
			RestClientResponseException exception) {
		String upstreamCode = upstreamCode(exception);
		if ("INVALID_MARKET_INTELLIGENCE_DECISION_SNAPSHOT".equals(upstreamCode)) {
			return new ForwardValidationGatewayException(
					upstreamCode,
					"The prospective-enrollment snapshot is invalid.",
					400);
		}
		if ("IDEMPOTENCY_KEY_REQUIRED".equals(upstreamCode)) {
			return new ForwardValidationGatewayException(
					upstreamCode,
					"An idempotency key is required.",
					400);
		}
		return new ForwardValidationGatewayException(
				"INVALID_PROSPECTIVE_ENROLLMENT",
				"The prospective-enrollment request is invalid.",
				400);
	}

	private static String upstreamCode(RestClientResponseException exception) {
		try {
			JsonNode root = JSON_MAPPER.readTree(exception.getResponseBodyAsString());
			JsonNode detail = root.get("detail");
			JsonNode code = detail != null && detail.isObject()
					? detail.get("code") : root.get("code");
			return code != null && code.isString() ? code.stringValue() : null;
		}
		catch (RuntimeException ignored) {
			return null;
		}
	}

	private static ForwardValidationGatewayException unavailable() {
		return new ForwardValidationGatewayException(
				"ANALYTICS_SERVICE_UNAVAILABLE",
				"The analytics service is temporarily unavailable.",
				502);
	}

	@FunctionalInterface
	private interface AnalyticsCall<T> {
		T execute();
	}
}
