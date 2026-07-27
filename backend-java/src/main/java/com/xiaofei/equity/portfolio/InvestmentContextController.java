package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.InvestmentContextContracts.*;

import java.net.URI;
import java.util.List;
import java.util.UUID;

import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;
import com.xiaofei.equity.usercontext.CurrentUser;
import jakarta.validation.Valid;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/me")
public class InvestmentContextController {

	private final ClosedTestIdentityResolver identityResolver;

	private final InvestmentContextService investmentContextService;

	public InvestmentContextController(
			ClosedTestIdentityResolver identityResolver,
			InvestmentContextService investmentContextService) {
		this.identityResolver = identityResolver;
		this.investmentContextService = investmentContextService;
	}

	@GetMapping("/investment-profile")
	InvestmentProfileResponse latestProfile(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity) {
		return investmentContextService.latestProfile(identityResolver.resolve(identity));
	}

	@PostMapping("/investment-profile")
	ResponseEntity<InvestmentProfileResponse> createProfile(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@Valid @RequestBody CreateInvestmentProfileRequest request) {
		InvestmentProfileResponse response = investmentContextService.createProfile(
				identityResolver.resolve(identity), idempotencyKey, request);
		return ResponseEntity.created(
				URI.create("/api/v1/me/investment-profile?version=" + response.versionNumber()))
			.body(response);
	}

	@GetMapping("/liabilities")
	List<LiabilityResponse> listLiabilities(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity) {
		return investmentContextService.listLiabilities(identityResolver.resolve(identity));
	}

	@PostMapping("/liabilities")
	ResponseEntity<LiabilityResponse> createLiability(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@Valid @RequestBody CreateLiabilityRequest request) {
		LiabilityResponse response = investmentContextService.createLiability(
				identityResolver.resolve(identity), request);
		return ResponseEntity.created(URI.create("/api/v1/me/liabilities/" + response.id()))
			.body(response);
	}

	@PostMapping("/liabilities/{liabilityId}/balances")
	ResponseEntity<LiabilityBalanceAccepted> recordLiabilityBalance(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@PathVariable UUID liabilityId,
			@Valid @RequestBody CreateLiabilityBalanceRequest request) {
		LiabilityBalanceAccepted response = investmentContextService.recordLiabilityBalance(
				identityResolver.resolve(identity), liabilityId, idempotencyKey, request);
		return ResponseEntity.accepted().body(response);
	}

	@PostMapping("/constraints")
	ResponseEntity<ConstraintPolicyResponse> createConstraintPolicy(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@Valid @RequestBody CreateConstraintPolicyRequest request) {
		ConstraintPolicyResponse response = investmentContextService.createConstraintPolicy(
				identityResolver.resolve(identity), idempotencyKey, request);
		return ResponseEntity.created(
				URI.create("/api/v1/me/constraints/" + response.id()))
			.body(response);
	}

	@GetMapping("/constraints/resolved")
	ResolvedPortfolioConstraints resolvedConstraints(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestParam UUID portfolioId) {
		CurrentUser user = identityResolver.resolve(identity);
		return investmentContextService.resolvePortfolioConstraints(user, portfolioId);
	}
}
