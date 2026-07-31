package com.xiaofei.equity.marketintelligence;

import java.net.URI;
import java.time.Instant;
import java.util.UUID;

import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.MarketIntelligenceFacets;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.EligibilityRecoveryStatusResponse;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ProfileResponse;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ScreeningResultPage;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ScreeningRunMetadata;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ScreeningRunRequest;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.SecuritySearchPage;
import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;

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
@RequestMapping("/api/v1/market-intelligence")
public class MarketIntelligenceController {

	private final ClosedTestIdentityResolver identityResolver;

	private final MarketIntelligenceAnalyticsClient analyticsClient;

	public MarketIntelligenceController(
			ClosedTestIdentityResolver identityResolver,
			MarketIntelligenceAnalyticsClient analyticsClient) {
		this.identityResolver = identityResolver;
		this.analyticsClient = analyticsClient;
	}

	@PostMapping("/screening-runs")
	public ResponseEntity<ScreeningRunMetadata> createScreeningRun(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@RequestBody ScreeningRunRequest request) {
		identityResolver.resolve(identity);
		ScreeningRunMetadata response = analyticsClient.createScreeningRun(
				request, idempotencyKey);
		return ResponseEntity.created(
				URI.create("/api/v1/market-intelligence/screening-runs/"
						+ response.runId()))
			.body(response);
	}

	@GetMapping("/screening-runs/{runId}")
	public ScreeningRunMetadata getScreeningRun(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID runId) {
		identityResolver.resolve(identity);
		return analyticsClient.getScreeningRun(runId);
	}

	@GetMapping("/screening-runs/{runId}/results")
	public ScreeningResultPage getScreeningResults(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID runId,
			@RequestParam(required = false) String cursor,
			@RequestParam(defaultValue = "20") int limit) {
		identityResolver.resolve(identity);
		requirePageLimit(limit);
		return analyticsClient.getScreeningResults(runId, cursor, limit);
	}

	@GetMapping("/profiles/{profileId}")
	public ProfileResponse getProfile(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID profileId) {
		identityResolver.resolve(identity);
		return analyticsClient.getProfile(profileId);
	}

	@GetMapping("/securities/{securityId}/profiles/latest")
	public ProfileResponse getLatestProfile(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID securityId,
			@RequestParam(required = false) Instant asOf) {
		identityResolver.resolve(identity);
		return analyticsClient.getLatestProfile(securityId, asOf);
	}

	@GetMapping("/securities")
	public SecuritySearchPage searchSecurities(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestParam(required = false) String query,
			@RequestParam UUID dataSnapshotId,
			@RequestParam(required = false) String cursor,
			@RequestParam(defaultValue = "20") int limit) {
		identityResolver.resolve(identity);
		requirePageLimit(limit);
		return analyticsClient.searchSecurities(
				query, dataSnapshotId, cursor, limit);
	}

	@GetMapping("/facets")
	public MarketIntelligenceFacets getFacets(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestParam UUID dataSnapshotId) {
		identityResolver.resolve(identity);
		return analyticsClient.getFacets(dataSnapshotId);
	}

	@GetMapping("/eligibility-recovery/status/latest")
	public EligibilityRecoveryStatusResponse getLatestEligibilityRecoveryStatus(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestParam UUID dataSnapshotId,
			@RequestParam String universeVersion,
			@RequestParam Instant asOf) {
		identityResolver.resolve(identity);
		return analyticsClient.getLatestEligibilityRecoveryStatus(
				dataSnapshotId, universeVersion, asOf);
	}

	private static void requirePageLimit(int limit) {
		if (limit < 1 || limit > 100) {
			throw new MarketIntelligenceGatewayException(
					"INVALID_MARKET_INTELLIGENCE_REQUEST",
					"Page limit must be between 1 and 100.",
					400);
		}
	}
}
