package com.xiaofei.equity.portfolio;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.EvaluationResponse;
import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.RecordObservationRequest;
import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.RecordExternalCashFlowRequest;
import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.ProgressMaturityRequest;
import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.SealLongitudinalRequest;
import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.CreateThesisReviewRequest;
import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.LongitudinalProjectionResponse;
import com.xiaofei.equity.usercontext.CurrentUser;

import jakarta.validation.Valid;

/** Controlled server-to-server ingestion for simulated evaluation observations. */
@RestController
@RequestMapping("/internal/v1/portfolio-evaluations")
public class PortfolioEvaluationObservationController {
	static final String SERVICE_AUTH_HEADER = "X-Portfolio-Decision-Service-Token";
	private final PortfolioDecisionService service;
	private final byte[] serviceToken;

	public PortfolioEvaluationObservationController(PortfolioDecisionService service,
			@Value("${portfolio-decision.service-token:${PORTFOLIO_DECISION_SERVICE_TOKEN:}}")
			String serviceToken) {
		if (serviceToken == null || serviceToken.isBlank() || serviceToken.length() > 512) {
			throw new IllegalStateException("Portfolio decision service token is required.");
		}
		this.service = service;
		this.serviceToken = serviceToken.getBytes(StandardCharsets.UTF_8);
	}

	@PostMapping("/{evaluationId}/observations")
	@ResponseStatus(HttpStatus.CREATED)
	EvaluationResponse record(
			@RequestHeader(SERVICE_AUTH_HEADER) String suppliedToken,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@RequestHeader("X-Portfolio-Owner-Id") UUID ownerId,
			@RequestHeader("X-Portfolio-Id") UUID portfolioId,
			@PathVariable UUID evaluationId,
			@Valid @RequestBody RecordObservationRequest request) {
		if (!MessageDigest.isEqual(serviceToken,
				suppliedToken.getBytes(StandardCharsets.UTF_8))) {
			throw new ResponseStatusException(HttpStatus.FORBIDDEN,
					"Portfolio decision service authorization is invalid.");
		}
		return service.recordObservation(
				new CurrentUser(ownerId, ownerId, "internal-portfolio-observation"),
				portfolioId, evaluationId, idempotencyKey, request);
	}

	@PostMapping("/{evaluationId}/cash-flows")
	@ResponseStatus(HttpStatus.CREATED)
	EvaluationResponse recordCashFlow(@RequestHeader(SERVICE_AUTH_HEADER) String suppliedToken,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@RequestHeader("X-Portfolio-Owner-Id") UUID ownerId,
			@RequestHeader("X-Portfolio-Id") UUID portfolioId,@PathVariable UUID evaluationId,
			@Valid @RequestBody RecordExternalCashFlowRequest request) {
		authorize(suppliedToken);
		return service.recordCashFlow(new CurrentUser(ownerId,ownerId,"internal-portfolio-cash-flow"),
				portfolioId,evaluationId,idempotencyKey,request);
	}

	@PostMapping("/{evaluationId}/maturities")
	@ResponseStatus(HttpStatus.CREATED)
	EvaluationResponse progressMaturity(@RequestHeader(SERVICE_AUTH_HEADER) String suppliedToken,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@RequestHeader("X-Portfolio-Owner-Id") UUID ownerId,
			@RequestHeader("X-Portfolio-Id") UUID portfolioId,@PathVariable UUID evaluationId,
			@Valid @RequestBody ProgressMaturityRequest request) {
		authorize(suppliedToken);
		return service.progressMaturity(new CurrentUser(ownerId,ownerId,"internal-portfolio-maturity"),
				portfolioId,evaluationId,idempotencyKey,request);
	}

	@PostMapping("/{evaluationId}/longitudinal/seal")
	@ResponseStatus(HttpStatus.CREATED)
	LongitudinalProjectionResponse sealLongitudinal(
			@RequestHeader(SERVICE_AUTH_HEADER) String suppliedToken,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@RequestHeader("X-Portfolio-Owner-Id") UUID ownerId,
			@RequestHeader("X-Portfolio-Id") UUID portfolioId,
			@PathVariable UUID evaluationId,
			@Valid @RequestBody SealLongitudinalRequest request) {
		authorize(suppliedToken);
		return service.sealLongitudinal(new CurrentUser(ownerId, ownerId,
				"internal-portfolio-longitudinal"), portfolioId, evaluationId,
				idempotencyKey, request);
	}

	@PostMapping("/{evaluationId}/thesis-reviews")
	@ResponseStatus(HttpStatus.CREATED)
	LongitudinalProjectionResponse reviewThesis(
			@RequestHeader(SERVICE_AUTH_HEADER) String suppliedToken,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@RequestHeader("X-Portfolio-Owner-Id") UUID ownerId,
			@RequestHeader("X-Portfolio-Id") UUID portfolioId,
			@PathVariable UUID evaluationId,
			@Valid @RequestBody CreateThesisReviewRequest request) {
		authorize(suppliedToken);
		return service.reviewThesis(new CurrentUser(ownerId, ownerId,
				"internal-portfolio-thesis-review"), portfolioId, evaluationId,
				idempotencyKey, request);
	}

	private void authorize(String suppliedToken) {
		if (!MessageDigest.isEqual(serviceToken,suppliedToken.getBytes(StandardCharsets.UTF_8))) {
			throw new ResponseStatusException(HttpStatus.FORBIDDEN,
					"Portfolio decision service authorization is invalid.");
		}
	}
}
