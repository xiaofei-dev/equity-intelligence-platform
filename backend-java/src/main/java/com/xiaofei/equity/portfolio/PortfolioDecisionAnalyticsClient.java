package com.xiaofei.equity.portfolio;

import java.time.Duration;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import tools.jackson.databind.JsonNode;

@Service
public class PortfolioDecisionAnalyticsClient {
	static final String INTERNAL_PATH = "/internal/v1/portfolio-decision-scenarios/projection-evaluations";
	static final String SERVICE_AUTH_HEADER = "X-Portfolio-Decision-Service-Token";
	private final RestClient restClient;
	private final String serviceAuthorization;

	@Autowired
	public PortfolioDecisionAnalyticsClient(
			@Value("${analytics.base-url:${ANALYTICS_BASE_URL:http://localhost:8000}}") String baseUrl,
			@Value("${analytics.connect-timeout:2s}") Duration connectTimeout,
			@Value("${analytics.read-timeout:30s}") Duration readTimeout,
			@Value("${portfolio-decision.service-token:${PORTFOLIO_DECISION_SERVICE_TOKEN:}}") String serviceAuthorization) {
		var requestFactory = new SimpleClientHttpRequestFactory();
		requestFactory.setConnectTimeout(connectTimeout);
		requestFactory.setReadTimeout(readTimeout);
		this.restClient = RestClient.builder().baseUrl(baseUrl).requestFactory(requestFactory).build();
		this.serviceAuthorization = requireServiceAuthorization(serviceAuthorization);
	}

	PortfolioDecisionAnalyticsClient(RestClient restClient) {
		this.restClient = restClient;
		this.serviceAuthorization = "test-only-service-authorization";
	}

	JsonNode evaluate(JsonNode input) {
		try {
			JsonNode body = restClient.post().uri(INTERNAL_PATH).header(SERVICE_AUTH_HEADER, serviceAuthorization)
					.contentType(MediaType.APPLICATION_JSON)
					.body(input).retrieve().body(JsonNode.class);
			if (body == null) throw unavailable();
			return body;
		}
		catch (RestClientResponseException exception) {
			if (exception.getStatusCode().value() == 422) {
				throw new PortfolioContextException("PORTFOLIO_SCENARIO_CONTRACT_REJECTED",
						"The portfolio scenario was rejected by analytics.", 409);
			}
			throw unavailable();
		}
		catch (RuntimeException exception) {
			if (exception instanceof PortfolioContextException known) throw known;
			throw unavailable();
		}
	}

	private static String requireServiceAuthorization(String value) {
		if (value == null || value.isBlank() || value.length() > 512) {
			throw new IllegalStateException("Analytics service authorization is required.");
		}
		return value;
	}

	private static PortfolioContextException unavailable() {
		return new PortfolioContextException("PORTFOLIO_SCENARIO_ANALYTICS_UNAVAILABLE",
				"The portfolio scenario analytics service is unavailable.", 502);
	}
}
