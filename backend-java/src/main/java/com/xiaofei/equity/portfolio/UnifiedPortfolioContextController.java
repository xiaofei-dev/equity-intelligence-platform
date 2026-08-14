package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.UnifiedPortfolioContracts.*;

import java.net.URI;
import java.util.UUID;

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
@RequestMapping("/api/v1/me/portfolios/{portfolioId}/contexts")
public class UnifiedPortfolioContextController {
	private final ClosedTestIdentityResolver identityResolver;
	private final UnifiedPortfolioContextService service;

	public UnifiedPortfolioContextController(
			ClosedTestIdentityResolver identityResolver, UnifiedPortfolioContextService service) {
		this.identityResolver = identityResolver;
		this.service = service;
	}

	@PostMapping("/current-evidence")
	ResponseEntity<CurrentEvidenceContextResponse> createCurrentEvidence(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,@PathVariable UUID portfolioId,
			@Valid @RequestBody CreateCurrentEvidenceContextRequest request) {
		CurrentEvidenceContextResponse response=service.createCurrentEvidence(identityResolver.resolve(identity),portfolioId,
				idempotencyKey,request);
		return ResponseEntity.created(URI.create("/api/v1/me/portfolios/"+portfolioId+"/contexts/"+response.context().contextId()))
				.body(response);
	}

	@GetMapping("/latest")
	ContextResponse latest(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID portfolioId) {
		return service.latest(identityResolver.resolve(identity), portfolioId);
	}

	@GetMapping("/{contextId}")
	ContextResponse get(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID portfolioId,
			@PathVariable UUID contextId) {
		return service.get(identityResolver.resolve(identity), portfolioId, contextId);
	}

	@PostMapping("/{contextId}/reviews")
	ResponseEntity<ReviewResponse> review(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@PathVariable UUID portfolioId,
			@PathVariable UUID contextId,
			@Valid @RequestBody ReviewRequest request) {
		ReviewResponse response = service.review(
				identityResolver.resolve(identity), portfolioId, contextId, idempotencyKey, request);
		return ResponseEntity.created(URI.create(
				"/api/v1/me/portfolios/" + portfolioId + "/contexts/" + contextId + "/reviews/"
						+ response.reviewId())).body(response);
	}
}
