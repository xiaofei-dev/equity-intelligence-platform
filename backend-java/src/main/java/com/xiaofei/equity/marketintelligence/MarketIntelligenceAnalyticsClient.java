package com.xiaofei.equity.marketintelligence;

import java.time.Duration;
import java.time.Instant;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.MarketIntelligenceFacets;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ProfileResponse;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ScreeningResultPage;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ScreeningRunMetadata;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ScreeningRunRequest;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.SecuritySearchPage;

@Service
public class MarketIntelligenceAnalyticsClient {

	static final String INTERNAL_ROOT = "/internal/v1/market-intelligence";

	private final RestClient restClient;

	@Autowired
	public MarketIntelligenceAnalyticsClient(
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

	MarketIntelligenceAnalyticsClient(RestClient restClient) {
		this.restClient = restClient;
	}

	public ScreeningRunMetadata createScreeningRun(
			ScreeningRunRequest request, String idempotencyKey) {
		return call("MARKET_INTELLIGENCE_RUN_NOT_FOUND",
				"INVALID_MARKET_INTELLIGENCE_REQUEST",
				() -> restClient.post()
					.uri(INTERNAL_ROOT + "/screening-runs")
					.header("Idempotency-Key", idempotencyKey)
					.contentType(MediaType.APPLICATION_JSON)
					.body(request)
					.retrieve()
					.body(ScreeningRunMetadata.class));
	}

	public ScreeningRunMetadata getScreeningRun(UUID runId) {
		return call("MARKET_INTELLIGENCE_RUN_NOT_FOUND",
				"INVALID_MARKET_INTELLIGENCE_REQUEST",
				() -> restClient.get()
					.uri(INTERNAL_ROOT + "/screening-runs/{runId}/metadata", runId)
					.retrieve()
					.body(ScreeningRunMetadata.class));
	}

	public ScreeningResultPage getScreeningResults(
			UUID runId, String cursor, int limit) {
		return call("MARKET_INTELLIGENCE_RUN_NOT_FOUND", "INVALID_CURSOR",
				() -> restClient.get()
					.uri(builder -> {
						var uri = builder.path(
								INTERNAL_ROOT + "/screening-runs/{runId}/results")
							.queryParam("limit", limit);
						if (cursor != null && !cursor.isBlank()) {
							uri.queryParam("cursor", cursor);
						}
						return uri.build(runId);
					})
					.retrieve()
					.body(ScreeningResultPage.class));
	}

	public ProfileResponse getProfile(UUID profileId) {
		return call("MARKET_INTELLIGENCE_PROFILE_NOT_FOUND",
				"INVALID_MARKET_INTELLIGENCE_REQUEST",
				() -> restClient.get()
					.uri(INTERNAL_ROOT + "/profiles/{profileId}", profileId)
					.retrieve()
					.body(ProfileResponse.class));
	}

	public ProfileResponse getLatestProfile(UUID securityId, Instant asOf) {
		return call("MARKET_INTELLIGENCE_PROFILE_NOT_FOUND",
				"INVALID_MARKET_INTELLIGENCE_REQUEST",
				() -> restClient.get()
					.uri(builder -> {
						var uri = builder.path(
								INTERNAL_ROOT
										+ "/securities/{securityId}/profiles/latest");
						if (asOf != null) {
							uri.queryParam("as_of", asOf);
						}
						return uri.build(securityId);
					})
					.retrieve()
					.body(ProfileResponse.class));
	}

	public SecuritySearchPage searchSecurities(
			String query, UUID dataSnapshotId, String cursor, int limit) {
		return call("MARKET_INTELLIGENCE_PROFILE_NOT_FOUND", "INVALID_CURSOR",
				() -> restClient.get()
					.uri(builder -> {
						var uri = builder.path(INTERNAL_ROOT + "/securities")
							.queryParam("data_snapshot_id", dataSnapshotId)
							.queryParam("limit", limit);
						if (query != null && !query.isBlank()) {
							uri.queryParam("query", query);
						}
						if (cursor != null && !cursor.isBlank()) {
							uri.queryParam("cursor", cursor);
						}
						return uri.build();
					})
					.retrieve()
					.body(SecuritySearchPage.class));
	}

	public MarketIntelligenceFacets getFacets(UUID dataSnapshotId) {
		return call("MARKET_INTELLIGENCE_SNAPSHOT_NOT_READY",
				"INVALID_MARKET_INTELLIGENCE_REQUEST",
				() -> restClient.get()
					.uri(builder -> builder.path(INTERNAL_ROOT + "/facets")
						.queryParam("data_snapshot_id", dataSnapshotId)
						.build())
					.retrieve()
					.body(MarketIntelligenceFacets.class));
	}

	private <T> T call(
			String notFoundCode,
			String invalidRequestCode,
			AnalyticsCall<T> call) {
		try {
			T response = call.execute();
			if (response == null) {
				throw unavailable();
			}
			return response;
		}
		catch (RestClientResponseException exception) {
			throw mapResponseError(exception, notFoundCode, invalidRequestCode);
		}
		catch (RestClientException exception) {
			throw unavailable();
		}
	}

	private static MarketIntelligenceGatewayException mapResponseError(
			RestClientResponseException exception,
			String notFoundCode,
			String invalidRequestCode) {
		return switch (exception.getStatusCode().value()) {
			case 400, 422 -> new MarketIntelligenceGatewayException(
					invalidRequestCode,
					"The market-intelligence request is invalid.",
					400);
			case 404 -> new MarketIntelligenceGatewayException(
					notFoundCode,
					"The requested market-intelligence resource was not found.",
					404);
			case 409 -> new MarketIntelligenceGatewayException(
					"IDEMPOTENCY_KEY_CONFLICT",
					"The idempotency key was already used for a different request.",
					409);
			default -> unavailable();
		};
	}

	private static MarketIntelligenceGatewayException unavailable() {
		return new MarketIntelligenceGatewayException(
				"ANALYTICS_SERVICE_UNAVAILABLE",
				"The analytics service is temporarily unavailable.",
				502);
	}

	@FunctionalInterface
	private interface AnalyticsCall<T> {
		T execute();
	}
}
