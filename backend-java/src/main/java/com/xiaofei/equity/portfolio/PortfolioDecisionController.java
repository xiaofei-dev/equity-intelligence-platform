package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.PortfolioDecisionContracts.*;

import java.net.URI;
import java.util.UUID;
import java.util.List;

import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;
import jakarta.validation.Valid;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/me/portfolios/{portfolioId}/decision-scenarios")
public class PortfolioDecisionController {
	private final ClosedTestIdentityResolver identityResolver;
	private final PortfolioDecisionService service;

	public PortfolioDecisionController(
			ClosedTestIdentityResolver identityResolver, PortfolioDecisionService service) {
		this.identityResolver = identityResolver;
		this.service = service;
	}

	@PostMapping
	ResponseEntity<ScenarioResponse> create(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@PathVariable UUID portfolioId,
			@Valid @RequestBody CreateScenarioRequest request) {
		ScenarioResponse response = service.create(
				identityResolver.resolve(identity), portfolioId, idempotencyKey, request);
		return ResponseEntity.created(URI.create("/api/v1/me/portfolios/" + portfolioId
				+ "/decision-scenarios/" + response.scenarioId())).body(response);
	}

	@PostMapping("/comparisons")
	ResponseEntity<ScenarioComparisonResponse> createComparison(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@PathVariable UUID portfolioId,
			@Valid @RequestBody CreateScenarioComparisonRequest request) {
		ScenarioComparisonResponse response = service.createComparison(
				identityResolver.resolve(identity), portfolioId, idempotencyKey, request);
		return ResponseEntity.created(URI.create("/api/v1/me/portfolios/" + portfolioId
				+ "/decision-scenarios/comparisons/" + response.comparisonId())).body(response);
	}

	@PostMapping("/comparisons/{comparisonId}/selection")
	ScenarioComparisonResponse selectComparison(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@PathVariable UUID portfolioId,
			@PathVariable UUID comparisonId,
			@Valid @RequestBody SelectScenarioComparisonRequest request) {
		return service.selectComparison(identityResolver.resolve(identity), portfolioId,
				comparisonId, idempotencyKey, request);
	}

	@GetMapping("/{scenarioId}")
	ScenarioResponse get(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID portfolioId,
			@PathVariable UUID scenarioId) {
		return service.get(identityResolver.resolve(identity), portfolioId, scenarioId);
	}

	@GetMapping
	List<ScenarioResponse> list(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID portfolioId) {
		return service.list(identityResolver.resolve(identity), portfolioId);
	}

	@GetMapping("/comparison/latest")
	ScenarioComparisonResponse latestComparison(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID portfolioId) {
		return service.latestComparison(identityResolver.resolve(identity), portfolioId);
	}

	@PostMapping("/{scenarioId}/decisions")
	ResponseEntity<HumanDecisionResponse> decide(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@PathVariable UUID portfolioId,
			@PathVariable UUID scenarioId,
			@Valid @RequestBody HumanDecisionRequest request) {
		HumanDecisionResponse response = service.decide(identityResolver.resolve(identity), portfolioId,
				scenarioId, idempotencyKey, request);
		return ResponseEntity.created(URI.create("/api/v1/me/portfolios/" + portfolioId
				+ "/decision-scenarios/" + scenarioId + "/decisions/" + response.decisionId()))
				.body(response);
	}

	@PostMapping("/{scenarioId}/evaluations")
	ResponseEntity<EvaluationResponse> createEvaluation(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@PathVariable UUID portfolioId,
			@PathVariable UUID scenarioId,
			@Valid @RequestBody CreateEvaluationRequest request) {
		EvaluationResponse response = service.createEvaluation(identityResolver.resolve(identity),
				portfolioId, scenarioId, idempotencyKey, request);
		return ResponseEntity.created(URI.create("/api/v1/me/portfolios/" + portfolioId
				+ "/decision-scenarios/" + scenarioId + "/evaluations/" + response.evaluationId()))
				.body(response);
	}

	@GetMapping("/{scenarioId}/evaluations/latest")
	EvaluationResponse latestEvaluation(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID portfolioId, @PathVariable UUID scenarioId) {
		return service.latestEvaluation(identityResolver.resolve(identity), portfolioId, scenarioId);
	}

	@GetMapping("/{scenarioId}/evaluations/{evaluationId}")
	EvaluationResponse getEvaluation(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID portfolioId, @PathVariable UUID scenarioId,
			@PathVariable UUID evaluationId) {
		return service.getEvaluation(identityResolver.resolve(identity), portfolioId, scenarioId, evaluationId);
	}

	@GetMapping("/{scenarioId}/evaluations/{evaluationId}/longitudinal")
	LongitudinalProjectionResponse longitudinal(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID portfolioId, @PathVariable UUID scenarioId,
			@PathVariable UUID evaluationId) {
		service.getEvaluation(identityResolver.resolve(identity), portfolioId, scenarioId, evaluationId);
		return service.longitudinalProjection(identityResolver.resolve(identity), portfolioId, evaluationId);
	}

	@PostMapping("/{scenarioId}/evaluations/{evaluationId}/longitudinal/seal")
	LongitudinalProjectionResponse sealLongitudinal(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@PathVariable UUID portfolioId, @PathVariable UUID scenarioId,
			@PathVariable UUID evaluationId,
			@Valid @RequestBody SealLongitudinalByHorizonRequest request) {
		var user=identityResolver.resolve(identity);
		service.getEvaluation(user,portfolioId,scenarioId,evaluationId);
		return service.sealLongitudinalByHorizon(user,portfolioId,evaluationId,idempotencyKey,request);
	}

	@PostMapping("/{scenarioId}/evaluations/{evaluationId}/thesis-reviews")
	LongitudinalProjectionResponse reviewThesis(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@PathVariable UUID portfolioId, @PathVariable UUID scenarioId,
			@PathVariable UUID evaluationId,
			@Valid @RequestBody CreateThesisReviewRequest request) {
		var user=identityResolver.resolve(identity);
		service.getEvaluation(user,portfolioId,scenarioId,evaluationId);
		return service.reviewThesis(user,portfolioId,evaluationId,idempotencyKey,request);
	}
}
