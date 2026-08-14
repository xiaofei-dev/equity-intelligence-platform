package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.PortfolioContracts.*;

import java.net.URI;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;
import com.xiaofei.equity.usercontext.CurrentUser;
import com.xiaofei.equity.usercontext.UserContextException;
import jakarta.validation.Valid;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

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

	@PostMapping("/accounts/{accountId}/snapshots/manual")
	ResponseEntity<SnapshotAccepted> createManualSnapshot(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@PathVariable UUID accountId,
			@Valid @RequestBody CreateManualSnapshotRequest request) {
		SnapshotAccepted response = portfolioService.createSnapshot(
				identityResolver.resolve(identity), accountId, idempotencyKey,
				request.asSnapshotRequest());
		return ResponseEntity.created(URI.create("/api/v1/me/accounts/" + accountId
				+ "/snapshots/" + response.snapshotId())).body(response);
	}

	@GetMapping("/accounts/{accountId}/snapshots/latest")
	SnapshotResponse latestSnapshot(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID accountId) {
		return portfolioService.latestSnapshot(identityResolver.resolve(identity), accountId);
	}

	@GetMapping("/accounts/{accountId}/snapshots/{snapshotId}")
	SnapshotResponse snapshot(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID accountId,
			@PathVariable UUID snapshotId) {
		return portfolioService.snapshot(identityResolver.resolve(identity), accountId, snapshotId);
	}

	@PostMapping(path = "/accounts/{accountId}/snapshots/csv/preview", consumes = "multipart/form-data")
	CsvSnapshotPreview previewCsv(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID accountId,
			@RequestParam("file") MultipartFile file) {
		return portfolioService.previewCsv(identityResolver.resolve(identity), accountId, bytes(file));
	}

	@PostMapping(path = "/accounts/{accountId}/snapshots/csv", consumes = "multipart/form-data")
	ResponseEntity<SnapshotAccepted> importCsv(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@RequestHeader("Expected-File-Sha256") String expectedFileSha256,
			@PathVariable UUID accountId,
			@RequestParam("asOfTime") Instant asOfTime,
			@RequestParam(value = "completeness", defaultValue = "COMPLETE") SnapshotCompleteness completeness,
			@RequestParam("file") MultipartFile file) {
		SnapshotAccepted response = portfolioService.importCsvSnapshot(
				identityResolver.resolve(identity), accountId, idempotencyKey, expectedFileSha256,
				asOfTime, completeness, bytes(file));
		return ResponseEntity.created(URI.create("/api/v1/me/accounts/" + accountId
				+ "/snapshots/" + response.snapshotId())).body(response);
	}

	private static byte[] bytes(MultipartFile file) {
		try { return file.getBytes(); }
		catch (java.io.IOException error) {
			throw new UserContextException("CSV_FILE_READ_FAILED", "The CSV file could not be read.", 422);
		}
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
