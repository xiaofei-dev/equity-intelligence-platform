package com.xiaofei.equity.quanttrading;

import java.time.Duration;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import com.xiaofei.equity.quanttrading.QuantResearchContract.ResearchDecisionResponse;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

@Service
public class QuantResearchAnalyticsClient {

	static final String INTERNAL_ROOT = "/internal/v1/quant-trading/research-decisions";
	private static final JsonMapper STRICT_MAPPER = JsonMapper.builder()
			.enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
			.enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES)
			.enable(DeserializationFeature.FAIL_ON_NULL_FOR_PRIMITIVES).build();

	private final RestClient restClient;

	@Autowired
	public QuantResearchAnalyticsClient(
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

	QuantResearchAnalyticsClient(RestClient restClient) {
		this.restClient = restClient;
	}

	ResearchDecisionResponse read(UUID decisionId) {
		try {
			String body = restClient.get().uri(INTERNAL_ROOT + "/{decisionId}", decisionId)
					.retrieve().body(String.class);
			if (body == null) throw upstreamInvalid();
			return STRICT_MAPPER.readValue(body, ResearchDecisionResponse.class);
		}
		catch (RestClientResponseException exception) {
			int status = exception.getStatusCode().value();
			if (status == 404) {
				throw new QuantResearchGatewayException("QUANT_RESEARCH_REFERENCE_NOT_FOUND",
						"The Quant research decision was not found.", 404);
			}
			if (status == 409) {
				throw new QuantResearchGatewayException("QUANT_RESEARCH_INTEGRITY_CONFLICT",
						"The Quant research decision failed its integrity contract.", 409);
			}
			throw upstreamUnavailable();
		}
		catch (RuntimeException exception) {
			if (exception instanceof QuantResearchGatewayException gateway) throw gateway;
			throw upstreamUnavailable();
		}
	}

	private static QuantResearchGatewayException upstreamInvalid() {
		return new QuantResearchGatewayException("INVALID_QUANT_RESEARCH_UPSTREAM_RESPONSE",
				"The analytics service returned an invalid Quant research decision.", 502);
	}

	private static QuantResearchGatewayException upstreamUnavailable() {
		return new QuantResearchGatewayException("QUANT_RESEARCH_ANALYTICS_UNAVAILABLE",
				"The Quant research analytics service is unavailable.", 503);
	}
}
