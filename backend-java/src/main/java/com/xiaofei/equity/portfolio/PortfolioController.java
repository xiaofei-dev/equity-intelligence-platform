package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.PortfolioContracts.*;

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
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/me")
public class PortfolioController {

	private final ClosedTestIdentityResolver identityResolver;

	private final PortfolioService portfolioService;

	public PortfolioController(
			ClosedTestIdentityResolver identityResolver,
			PortfolioService portfolioService) {
		this.identityResolver = identityResolver;
		this.portfolioService = portfolioService;
	}

	@GetMapping("/accounts")
	List<AccountResponse> listAccounts(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity) {
		return portfolioService.listAccounts(identityResolver.resolve(identity));
	}

	@PostMapping("/accounts")
	ResponseEntity<AccountResponse> createAccount(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@Valid @RequestBody CreateAccountRequest request) {
		AccountResponse response = portfolioService.createAccount(
				identityResolver.resolve(identity), request);
		return ResponseEntity.created(URI.create("/api/v1/me/accounts/" + response.id()))
			.body(response);
	}

	@PostMapping("/accounts/{accountId}/snapshots")
	ResponseEntity<SnapshotAccepted> createSnapshot(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@PathVariable UUID accountId,
			@Valid @RequestBody CreateSnapshotRequest request) {
		SnapshotAccepted response = portfolioService.createSnapshot(
				identityResolver.resolve(identity), accountId, idempotencyKey, request);
		return ResponseEntity.accepted().body(response);
	}

	@GetMapping("/portfolios")
	List<PortfolioResponse> listPortfolios(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity) {
		return portfolioService.listPortfolios(identityResolver.resolve(identity));
	}

	@PostMapping("/portfolios")
	ResponseEntity<PortfolioResponse> createPortfolio(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@Valid @RequestBody CreatePortfolioRequest request) {
		PortfolioResponse response = portfolioService.createPortfolio(
				identityResolver.resolve(identity), request);
		return ResponseEntity.created(URI.create("/api/v1/me/portfolios/" + response.id()))
			.body(response);
	}

	@PutMapping("/portfolios/{portfolioId}/accounts")
	PortfolioResponse replacePortfolioAccounts(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID portfolioId,
			@Valid @RequestBody ReplacePortfolioAccountsRequest request) {
		return portfolioService.replacePortfolioAccounts(
				identityResolver.resolve(identity), portfolioId, request);
	}

	@PutMapping("/portfolios/{portfolioId}/liabilities")
	PortfolioLiabilityMembershipResponse replacePortfolioLiabilities(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID portfolioId,
			@Valid @RequestBody ReplacePortfolioLiabilitiesRequest request) {
		return portfolioService.replacePortfolioLiabilities(
				identityResolver.resolve(identity), portfolioId, request);
	}

	@PostMapping("/portfolios/{portfolioId}/scenarios")
	ResponseEntity<ScenarioAccepted> createScenario(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@PathVariable UUID portfolioId,
			@Valid @RequestBody CreateScenarioRequest request) {
		CurrentUser user = identityResolver.resolve(identity);
		ScenarioAccepted response = portfolioService.createScenario(
				user, portfolioId, idempotencyKey, request);
		return ResponseEntity.accepted().body(response);
	}
}
