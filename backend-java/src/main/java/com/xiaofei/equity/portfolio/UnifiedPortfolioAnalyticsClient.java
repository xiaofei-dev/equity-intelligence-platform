package com.xiaofei.equity.portfolio;

import java.time.Duration;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import com.xiaofei.equity.portfolio.UnifiedPortfolioContracts.RiskInput;

import tools.jackson.databind.JsonNode;

@Service
public class UnifiedPortfolioAnalyticsClient {

	static final String INTERNAL_PATH = "/internal/v1/portfolio-context/risk-evaluations";
	static final String CURRENT_EVIDENCE_PATH = "/internal/v1/portfolio-context/current-evidence-assemblies/by-id";
	static final String SERVICE_AUTH_HEADER = "X-Portfolio-Decision-Service-Token";
	private final RestClient restClient;
	private final String serviceToken;

	@Autowired
	public UnifiedPortfolioAnalyticsClient(
			@Value("${analytics.base-url:${ANALYTICS_BASE_URL:http://localhost:8000}}")
			String analyticsBaseUrl,
			@Value("${analytics.connect-timeout:2s}") Duration connectTimeout,
			@Value("${analytics.read-timeout:30s}") Duration readTimeout,
			@Value("${portfolio-decision.service-token:${PORTFOLIO_DECISION_SERVICE_TOKEN:}}") String serviceToken) {
		var requestFactory = new SimpleClientHttpRequestFactory();
		requestFactory.setConnectTimeout(connectTimeout);
		requestFactory.setReadTimeout(readTimeout);
		this.restClient = RestClient.builder().baseUrl(analyticsBaseUrl)
				.requestFactory(requestFactory).build();
		this.serviceToken = requireToken(serviceToken);
	}

	UnifiedPortfolioAnalyticsClient(RestClient restClient) {
		this.restClient = restClient;
		this.serviceToken = "test-only-service-authorization";
	}

	JsonNode assembleCurrentEvidence(JsonNode input) {
		try {
			JsonNode body=restClient.post().uri(CURRENT_EVIDENCE_PATH).header(SERVICE_AUTH_HEADER,serviceToken)
					.contentType(MediaType.APPLICATION_JSON).body(input).retrieve().body(JsonNode.class);
			if(body==null)throw unavailable(); return body;
		} catch(RestClientResponseException exception) {
			if(exception.getStatusCode().value()==409)throw new PortfolioContextException(
					"CURRENT_PORTFOLIO_EVIDENCE_INTEGRITY_ERROR","Current portfolio evidence failed integrity replay.",409);
			throw unavailable();
		} catch(RuntimeException exception) {if(exception instanceof PortfolioContextException known)throw known;throw unavailable();}
	}

	JsonNode evaluate(RiskInput input) {
		try {
			JsonNode body = restClient.post().uri(INTERNAL_PATH)
					.header(SERVICE_AUTH_HEADER, serviceToken)
					.contentType(MediaType.APPLICATION_JSON).body(input)
					.retrieve().body(JsonNode.class);
			if (body == null) throw unavailable();
			return body;
		}
		catch (RestClientResponseException exception) {
			if (exception.getStatusCode().value() == 422) {
				throw new PortfolioContextException("INVALID_PORTFOLIO_RISK_CONTRACT",
						"The portfolio risk input was rejected by analytics.", 422);
			}
			throw unavailable();
		}
		catch (RuntimeException exception) {
			if (exception instanceof PortfolioContextException known) throw known;
			throw unavailable();
		}
	}

	private static PortfolioContextException unavailable() {
		return new PortfolioContextException("PORTFOLIO_ANALYTICS_UNAVAILABLE",
				"The portfolio analytics service is unavailable.", 503);
	}
	private static String requireToken(String value) {if(value==null||value.isBlank()||value.length()>512)
		throw new IllegalStateException("Portfolio decision service token is required.");return value;}
}
