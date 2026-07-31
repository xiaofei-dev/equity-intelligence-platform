package com.xiaofei.equity.marketintelligence;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withResourceNotFound;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import java.time.Instant;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.UUID;

import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.RankMetric;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ScreeningFilter;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ScreeningRunRequest;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.SortDirection;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class MarketIntelligenceAnalyticsClientTests {

	private static final UUID SNAPSHOT_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000010");

	private static final UUID RUN_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000020");

	@Test
	void usesCanonicalMetadataResourcePath() throws Exception {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		MarketIntelligenceAnalyticsClient client =
				new MarketIntelligenceAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/market-intelligence/"
							+ "screening-runs/" + RUN_ID + "/metadata"))
			.andExpect(method(HttpMethod.GET))
			.andRespond(withSuccess(
					Files.readString(Path.of(
							"..", "contracts", "market-intelligence-v1",
							"screening-run-metadata.example.json")),
					MediaType.APPLICATION_JSON));

		assertThat(client.getScreeningRun(RUN_ID).gateStatus())
			.isEqualTo("NO_ELIGIBLE_RESULTS");
		server.verify();
	}

	@Test
	void translatesPublicCamelCaseToPythonSnakeCaseQueryParameters() {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		MarketIntelligenceAnalyticsClient client =
				new MarketIntelligenceAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/market-intelligence/facets"
							+ "?data_snapshot_id=" + SNAPSHOT_ID))
			.andExpect(method(HttpMethod.GET))
			.andRespond(withSuccess("""
					{
					  "dataSnapshotId":"00000000-0000-0000-0000-000000000010",
					  "universeVersion":"market-intelligence-closed-test-us-v1.0.0",
					  "sectors":["45"],
					  "industries":["4510"],
					  "companyTypes":["MATURE_OPERATING_COMPANY"],
					  "membershipStatuses":["INCLUDED"]
					}
					""", MediaType.APPLICATION_JSON));

		assertThat(client.getFacets(SNAPSHOT_ID).sectors()).containsExactly("45");
		server.verify();
	}

	@Test
	void forwardsIdempotencyButNeverAcceptsOrForwardsUserIdentity() {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		MarketIntelligenceAnalyticsClient client =
				new MarketIntelligenceAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/market-intelligence/screening-runs"))
			.andExpect(method(HttpMethod.POST))
			.andExpect(header("Idempotency-Key", "run-key-1"))
			.andExpect(request -> assertThat(
					request.getHeaders().get("X-Test-Identity")).isNull())
			.andRespond(withSuccess("""
					{
					  "runId":"00000000-0000-0000-0000-000000000020",
					  "state":"SEALED",
					  "dataSnapshotId":"00000000-0000-0000-0000-000000000010",
					  "universeVersion":"market-intelligence-closed-test-us-v1.0.0",
					  "asOf":"2026-07-28T02:00:00Z",
					  "rankBy":"BUYING_OPPORTUNITY",
					  "direction":"DESCENDING",
					  "eligibleCount":0,
					  "excludedCount":66,
					  "gateStatus":"NO_ELIGIBLE_RESULTS",
					  "profileSetHash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
					  "resultHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
					  "sealedAt":"2026-07-28T02:00:01Z"
					}
					""", MediaType.APPLICATION_JSON));

		var response = client.createScreeningRun(
				new ScreeningRunRequest(
						SNAPSHOT_ID,
						"market-intelligence-closed-test-us-v1.0.0",
						Instant.parse("2026-07-28T02:00:00Z"),
						new ScreeningFilter(
								List.of(), List.of(), List.of(), List.of(), List.of(), true),
						RankMetric.BUYING_OPPORTUNITY,
						SortDirection.DESCENDING,
						50),
				"run-key-1");

		assertThat(response.runId()).isEqualTo(RUN_ID);
		server.verify();
	}

	@Test
	void mapsAnalyticsNotFoundWithoutExposingResponseBody() {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		MarketIntelligenceAnalyticsClient client =
				new MarketIntelligenceAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/market-intelligence/profiles/"
							+ RUN_ID))
			.andExpect(method(HttpMethod.GET))
			.andRespond(withResourceNotFound().body(
					"{\"detail\":\"provider payload path C:/secret/raw.json\"}"));

		assertThatThrownBy(() -> client.getProfile(RUN_ID))
			.isInstanceOfSatisfying(
					MarketIntelligenceGatewayException.class,
					exception -> {
						assertThat(exception.code())
							.isEqualTo("MARKET_INTELLIGENCE_PROFILE_NOT_FOUND");
						assertThat(exception.getMessage())
							.doesNotContain("provider", "secret", "raw.json");
						assertThat(exception.status()).isEqualTo(404);
					});
		server.verify();
	}

	@Test
	void mapsIdempotencyConflictWithoutExposingResponseBody() {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		MarketIntelligenceAnalyticsClient client =
				new MarketIntelligenceAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/market-intelligence/screening-runs"))
			.andExpect(method(HttpMethod.POST))
			.andRespond(withStatus(HttpStatus.CONFLICT).body(
					"{\"detail\":\"provider payload path C:/secret/raw.json\"}"));

		assertThatThrownBy(() -> client.createScreeningRun(
				new ScreeningRunRequest(
						SNAPSHOT_ID,
						"market-intelligence-closed-test-us-v1.0.0",
						Instant.parse("2026-07-28T02:00:00Z"),
						new ScreeningFilter(
								List.of(), List.of(), List.of(), List.of(), List.of(), true),
						RankMetric.BUYING_OPPORTUNITY,
						SortDirection.DESCENDING,
						50),
				"run-key-1"))
			.isInstanceOfSatisfying(
					MarketIntelligenceGatewayException.class,
					exception -> {
						assertThat(exception.code())
							.isEqualTo("IDEMPOTENCY_KEY_CONFLICT");
						assertThat(exception.getMessage())
							.doesNotContain("provider", "secret", "raw.json");
						assertThat(exception.status()).isEqualTo(409);
					});
		server.verify();
	}

	@Test
	void readsDbBackedEligibilityRecoveryStatusWithCanonicalParameters() {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		MarketIntelligenceAnalyticsClient client =
				new MarketIntelligenceAnalyticsClient(builder.build());
		Instant asOf = Instant.parse("2026-07-29T02:57:08.988871Z");
		server.expect(once(), request -> {
			assertThat(request.getMethod()).isEqualTo(HttpMethod.GET);
			assertThat(request.getURI().getPath()).isEqualTo(
					"/internal/v1/market-intelligence/"
							+ "eligibility-recovery/status/latest");
			assertThat(request.getURI().getQuery())
				.contains(
						"data_snapshot_id=" + SNAPSHOT_ID,
						"universe_version=market-intelligence-closed-test-us-v1.0.0",
						"as_of=2026-07-29T02:57:08.988871Z");
			assertThat(request.getHeaders().get("X-Test-Identity")).isNull();
		}).andRespond(withSuccess(
				MarketIntelligenceContractTests.eligibilityResponseJson(),
				MediaType.APPLICATION_JSON));

		var response = client.getLatestEligibilityRecoveryStatus(
				SNAPSHOT_ID,
				"market-intelligence-closed-test-us-v1.0.0",
				asOf);

		assertThat(response.status().name()).isEqualTo("READY_FOR_CONFIRMATION");
		assertThat(response.currentEligibleCount()).isEqualTo(6);
		assertThat(response.blockerSummary()).hasSize(1);
		server.verify();
	}

	@Test
	void preservesAllowListedEligibilityConflictWithoutExposingDetails() {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		MarketIntelligenceAnalyticsClient client =
				new MarketIntelligenceAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/market-intelligence/"
							+ "eligibility-recovery/status/latest"
							+ "?data_snapshot_id=" + SNAPSHOT_ID
							+ "&universe_version=wrong"
							+ "&as_of=2026-07-29T02:57:08Z"))
			.andRespond(withStatus(HttpStatus.CONFLICT).body("""
					{"detail":{
					  "code":"ELIGIBILITY_RECOVERY_UNIVERSE_MISMATCH",
					  "message":"provider payload C:/secret/raw.json"
					}}
					"""));

		assertThatThrownBy(() -> client.getLatestEligibilityRecoveryStatus(
				SNAPSHOT_ID,
				"wrong",
				Instant.parse("2026-07-29T02:57:08Z")))
			.isInstanceOfSatisfying(
					MarketIntelligenceGatewayException.class,
					exception -> {
						assertThat(exception.code())
							.isEqualTo("ELIGIBILITY_RECOVERY_UNIVERSE_MISMATCH");
						assertThat(exception.status()).isEqualTo(409);
						assertThat(exception.getMessage())
							.doesNotContain("provider", "secret", "raw.json");
					});
		server.verify();
	}
}
