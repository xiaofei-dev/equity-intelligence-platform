package com.xiaofei.equity.forwardvalidation;

import java.time.Duration;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.EnrollmentAccepted;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.EnrollmentRequest;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardExperimentAccepted;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardExperimentRequest;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardExperimentStatus;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardReport;

@Service
public class ForwardValidationAnalyticsClient {

	private final RestClient restClient;

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

	@FunctionalInterface
	private interface AnalyticsCall<T> {
		T execute();
	}
}
