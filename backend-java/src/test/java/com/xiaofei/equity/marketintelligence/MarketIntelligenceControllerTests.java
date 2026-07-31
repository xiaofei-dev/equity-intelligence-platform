package com.xiaofei.equity.marketintelligence;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.UUID;

import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.MarketIntelligenceFacets;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.EligibilityRecoveryStatusResponse;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ProfileResponse;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.RankMetric;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.RunState;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ScreeningResultPage;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ScreeningRunMetadata;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.SecuritySearchPage;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.SortDirection;
import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;
import com.xiaofei.equity.usercontext.CurrentUser;
import com.xiaofei.equity.usercontext.UserContextExceptionHandler;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import tools.jackson.databind.json.JsonMapper;

@WebMvcTest({
	MarketIntelligenceController.class,
	MarketIntelligenceExceptionHandler.class,
	UserContextExceptionHandler.class
})
class MarketIntelligenceControllerTests {

	private static final UUID USER_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000001");

	private static final UUID IDENTITY_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000002");

	private static final UUID SNAPSHOT_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000010");

	private static final UUID RUN_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000020");

	private static final UUID SECURITY_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000001");

	private static final UUID PROFILE_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000002");

	@Autowired
	private MockMvc mockMvc;

	@MockitoBean
	private ClosedTestIdentityResolver identityResolver;

	@MockitoBean
	private MarketIntelligenceAnalyticsClient analyticsClient;

	@BeforeEach
	void resolveIdentity() {
		when(identityResolver.resolve("tester-one")).thenReturn(
				new CurrentUser(USER_ID, IDENTITY_ID, "tester-one"));
	}

	@Test
	void createsSealedRunWithIdentityAndIdempotencyBoundaries() throws Exception {
		when(analyticsClient.createScreeningRun(any(), eq("market-run-1")))
			.thenReturn(new ScreeningRunMetadata(
					RUN_ID,
					RunState.SEALED,
					SNAPSHOT_ID,
					"market-intelligence-closed-test-us-v1.0.0",
					Instant.parse("2026-07-28T02:00:00Z"),
					RankMetric.BUYING_OPPORTUNITY,
					SortDirection.DESCENDING,
					0,
					66,
					"NO_ELIGIBLE_RESULTS",
					"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
					"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
					Instant.parse("2026-07-28T02:00:01Z")));

		mockMvc.perform(post("/api/v1/market-intelligence/screening-runs")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "market-run-1")
				.contentType(MediaType.APPLICATION_JSON)
				.content("""
						{
						  "dataSnapshotId":"00000000-0000-0000-0000-000000000010",
						  "universeVersion":"market-intelligence-closed-test-us-v1.0.0",
						  "asOf":"2026-07-28T02:00:00Z",
						  "filters":{"sectors":["TECH"],"requireRankingEligible":true},
						  "rankBy":"BUYING_OPPORTUNITY",
						  "direction":"DESCENDING",
						  "limit":50
						}
						"""))
			.andExpect(status().isCreated())
			.andExpect(header().string(
					"Location",
					"/api/v1/market-intelligence/screening-runs/" + RUN_ID))
			.andExpect(jsonPath("$.runId").value(RUN_ID.toString()))
			.andExpect(jsonPath("$.state").value("SEALED"));

		verify(identityResolver).resolve("tester-one");
		verify(analyticsClient).createScreeningRun(any(), eq("market-run-1"));
	}

	@Test
	void requiresClosedTestIdentityBeforeProxying() throws Exception {
		mockMvc.perform(get("/api/v1/market-intelligence/facets")
				.queryParam("dataSnapshotId", SNAPSHOT_ID.toString()))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.code").value("USER_CONTEXT_MISSING"));
	}

	@Test
	void requiresIdempotencyKeyBeforeCreatingScreeningRun() throws Exception {
		mockMvc.perform(post("/api/v1/market-intelligence/screening-runs")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.contentType(MediaType.APPLICATION_JSON)
				.content("{}"))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.code").value("IDEMPOTENCY_KEY_REQUIRED"));
	}

	@Test
	void validatesPublicPaginationLimit() throws Exception {
		mockMvc.perform(get(
					"/api/v1/market-intelligence/screening-runs/{runId}/results",
					RUN_ID)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.queryParam("limit", "101"))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.code")
					.value("INVALID_MARKET_INTELLIGENCE_REQUEST"));
	}

	@Test
	void proxiesCursorResultsAndFacets() throws Exception {
		when(analyticsClient.getScreeningResults(RUN_ID, "cursor-1", 20))
			.thenReturn(new ScreeningResultPage(metadata(), List.of(), null));
		when(analyticsClient.getFacets(SNAPSHOT_ID)).thenReturn(
				new MarketIntelligenceFacets(
						SNAPSHOT_ID,
						"market-intelligence-closed-test-us-v1.0.0",
						List.of("Technology"),
						List.of(),
						List.of(),
						List.of("PRIMARY", "REFERENCE_ONLY")));

		mockMvc.perform(get(
					"/api/v1/market-intelligence/screening-runs/{runId}/results",
					RUN_ID)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.queryParam("cursor", "cursor-1"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.run.runId").value(RUN_ID.toString()))
			.andExpect(jsonPath("$.items").isArray());

		mockMvc.perform(get("/api/v1/market-intelligence/facets")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.queryParam("dataSnapshotId", SNAPSHOT_ID.toString()))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.sectors[0]").value("Technology"))
			.andExpect(jsonPath("$.membershipStatuses.length()").value(2));
	}

	@Test
	void proxiesMetadataProfilesAndSecuritySearchWithCanonicalParameters()
			throws Exception {
		ProfileResponse profile = profileFixture();
		Instant asOf = Instant.parse("2026-07-28T02:00:00Z");
		when(analyticsClient.getScreeningRun(RUN_ID)).thenReturn(metadata());
		when(analyticsClient.getProfile(PROFILE_ID)).thenReturn(profile);
		when(analyticsClient.getLatestProfile(SECURITY_ID, asOf))
			.thenReturn(profile);
		when(analyticsClient.searchSecurities(
				"AAP", SNAPSHOT_ID, "cursor-2", 25))
			.thenReturn(new SecuritySearchPage(
					SNAPSHOT_ID,
					"market-intelligence-closed-test-us-v1.0.0",
					List.of(),
					null));

		mockMvc.perform(get(
					"/api/v1/market-intelligence/screening-runs/{runId}",
					RUN_ID)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runId").value(RUN_ID.toString()));

		mockMvc.perform(get(
					"/api/v1/market-intelligence/profiles/{profileId}",
					PROFILE_ID)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.profileId").value(profile.profileId().toString()));

		mockMvc.perform(get(
					"/api/v1/market-intelligence/securities/{securityId}/profiles/latest",
					SECURITY_ID)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.queryParam("asOf", asOf.toString()))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.securityId").value(profile.securityId().toString()));

		mockMvc.perform(get("/api/v1/market-intelligence/securities")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.queryParam("query", "AAP")
				.queryParam("dataSnapshotId", SNAPSHOT_ID.toString())
				.queryParam("cursor", "cursor-2")
				.queryParam("limit", "25"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.dataSnapshotId").value(SNAPSHOT_ID.toString()))
			.andExpect(jsonPath("$.items").isArray());

		verify(analyticsClient).getScreeningRun(RUN_ID);
		verify(analyticsClient).getProfile(PROFILE_ID);
		verify(analyticsClient).getLatestProfile(SECURITY_ID, asOf);
		verify(analyticsClient).searchSecurities(
				"AAP", SNAPSHOT_ID, "cursor-2", 25);
	}

	@Test
	void exposesEligibilityRecoveryStatusOnlyAfterClosedTestIdentityResolution()
			throws Exception {
		Instant asOf = Instant.parse("2026-07-29T02:57:08.988871Z");
		var mapper = JsonMapper.builder().findAndAddModules().build();
		EligibilityRecoveryStatusResponse response = mapper.readValue(
				MarketIntelligenceContractTests.eligibilityResponseJson(),
				EligibilityRecoveryStatusResponse.class);
		when(analyticsClient.getLatestEligibilityRecoveryStatus(
				SNAPSHOT_ID,
				"market-intelligence-closed-test-us-v1.0.0",
				asOf))
			.thenReturn(response);

		mockMvc.perform(get(
					"/api/v1/market-intelligence/"
							+ "eligibility-recovery/status/latest")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.queryParam("dataSnapshotId", SNAPSHOT_ID.toString())
				.queryParam(
						"universeVersion",
						"market-intelligence-closed-test-us-v1.0.0")
				.queryParam("asOf", asOf.toString()))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status").value("READY_FOR_CONFIRMATION"))
			.andExpect(jsonPath("$.currentEligibleCount").value(6))
			.andExpect(jsonPath("$.frozenMinimumEligibleCount").value(20))
			.andExpect(jsonPath("$.profileCount").value(66))
			.andExpect(jsonPath("$.resultCount").value(66))
			.andExpect(jsonPath("$.blockerSummary[0].category")
					.value("MISSING_REQUIRED_EVIDENCE"))
			.andExpect(jsonPath("$.freshness[0].datasetCode")
					.value("FUNDAMENTALS"))
			.andExpect(jsonPath("$.objectiveRatingVersion")
					.value("Objective-Rating-v1"))
			.andExpect(jsonPath("$.networkRequestsExecuted").value(false))
			.andExpect(jsonPath("$.scoresOrRanksGenerated").value(false));

		verify(identityResolver).resolve("tester-one");
		verify(analyticsClient).getLatestEligibilityRecoveryStatus(
				SNAPSHOT_ID,
				"market-intelligence-closed-test-us-v1.0.0",
				asOf);
	}

	@Test
	void returnsStableGatewayErrorWithoutInternalProviderDetails() throws Exception {
		when(analyticsClient.getScreeningResults(RUN_ID, null, 20))
			.thenThrow(new MarketIntelligenceGatewayException(
					"ANALYTICS_SERVICE_UNAVAILABLE",
					"The analytics service is temporarily unavailable.",
					502));

		mockMvc.perform(get(
					"/api/v1/market-intelligence/screening-runs/{runId}/results",
					RUN_ID)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isBadGateway())
			.andExpect(jsonPath("$.code").value("ANALYTICS_SERVICE_UNAVAILABLE"))
			.andExpect(jsonPath("$.message")
					.value("The analytics service is temporarily unavailable."))
			.andExpect(jsonPath("$.provider").doesNotExist())
			.andExpect(jsonPath("$.detail").doesNotExist());
	}

	private static ScreeningRunMetadata metadata() {
		return new ScreeningRunMetadata(
				RUN_ID,
				RunState.SEALED,
				SNAPSHOT_ID,
				"market-intelligence-closed-test-us-v1.0.0",
				Instant.parse("2026-07-28T02:00:00Z"),
				RankMetric.BUYING_OPPORTUNITY,
				SortDirection.DESCENDING,
				0,
				66,
				"NO_ELIGIBLE_RESULTS",
				"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
				Instant.parse("2026-07-28T02:00:01Z"));
	}

	private static ProfileResponse profileFixture() throws Exception {
		var mapper = JsonMapper.builder().findAndAddModules().build();
		var path = Path.of(
				"src", "test", "resources",
				"market-intelligence-v1", "profile-response.json");
		return mapper.readValue(Files.readString(path), ProfileResponse.class);
	}
}
