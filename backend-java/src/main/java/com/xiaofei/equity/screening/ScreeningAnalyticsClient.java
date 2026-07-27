package com.xiaofei.equity.screening;

import java.time.Duration;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import com.xiaofei.equity.screening.ScreeningRatingContract.RatingPage;
import com.xiaofei.equity.screening.ScreeningRatingContract.ScreeningRunAccepted;
import com.xiaofei.equity.screening.ScreeningRatingContract.ScreeningRunRequest;
import com.xiaofei.equity.screening.ScreeningRatingContract.ScreeningRunStatus;

@Service
public class ScreeningAnalyticsClient {

	private final RestClient restClient;

	public ScreeningAnalyticsClient(
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

	public ScreeningRunAccepted createRun(
			ScreeningRunRequest request,
			String idempotencyKey) {
		return call(() -> restClient.post()
				.uri("/internal/v1/screening/runs")
				.header("Idempotency-Key", idempotencyKey)
				.contentType(MediaType.APPLICATION_JSON)
				.body(request)
				.retrieve()
				.body(ScreeningRunAccepted.class));
	}

	public ScreeningRunStatus getRun(String runId) {
		return call(() -> restClient.get()
				.uri("/internal/v1/screening/runs/{runId}", runId)
				.retrieve()
				.body(ScreeningRunStatus.class));
	}

	public RatingPage getRatings(String runId, String cursor) {
		return call(() -> restClient.get()
				.uri(builder -> {
					var uri = builder.path("/internal/v1/screening/runs/{runId}/ratings");
					if (cursor != null && !cursor.isBlank()) {
						uri.queryParam("cursor", cursor);
					}
					return uri.build(runId);
				})
				.retrieve()
				.body(RatingPage.class));
	}

	private <T> T call(AnalyticsCall<T> call) {
		try {
			T response = call.execute();
			if (response == null) {
				throw new ScreeningGatewayException("Analytics service returned an empty response");
			}
			return response;
		}
		catch (RestClientException exception) {
			throw new ScreeningGatewayException("Analytics service request failed", exception);
		}
	}

	@FunctionalInterface
	private interface AnalyticsCall<T> {
		T execute();
	}
}
