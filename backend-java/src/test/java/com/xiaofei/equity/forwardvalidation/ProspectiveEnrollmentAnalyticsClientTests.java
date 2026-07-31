package com.xiaofei.equity.forwardvalidation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import java.util.List;
import java.util.UUID;

import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveEnrollmentRequest;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class ProspectiveEnrollmentAnalyticsClientTests {

	private static final UUID ATTEMPT_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000031");

	private static final UUID RUN_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000033");

	private static final String DECISION_HASH =
			"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

	@Test
	void forwardsIdempotencyWithoutForwardingClosedTestIdentity() {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new ForwardValidationAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/forward-validation/"
							+ "prospective-enrollments"))
			.andExpect(method(HttpMethod.POST))
			.andExpect(header("Idempotency-Key", "prospective-1"))
			.andExpect(request -> assertThat(
					request.getHeaders().get("X-Test-Identity")).isNull())
			.andRespond(withSuccess(responseJson("BLOCKED"), MediaType.APPLICATION_JSON));

		var response = client.createProspectiveEnrollment(
				new ProspectiveEnrollmentRequest(DECISION_HASH, List.of(RUN_ID), null),
				"prospective-1");

		assertThat(response.attemptId()).isEqualTo(ATTEMPT_ID);
		assertThat(response.status().name()).isEqualTo("BLOCKED");
		assertThat(response.decisionAsOf().toString()).isEqualTo("2026-07-29T02:00:00Z");
		assertThat(response.maturitySchedule())
			.extracting(item -> item.tradingDays())
			.containsExactly(5, 20, 60);
		assertThat(response.longHorizonIsContextOnly()).isTrue();
		server.verify();
	}

	@Test
	void readsAnImmutableAttemptThroughTheCanonicalPath() {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new ForwardValidationAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/forward-validation/"
							+ "prospective-enrollments/" + ATTEMPT_ID))
			.andExpect(method(HttpMethod.GET))
			.andRespond(withSuccess(
					responseJson("NO_ELIGIBLE_SIGNALS"),
					MediaType.APPLICATION_JSON));

		var response = client.getProspectiveEnrollment(ATTEMPT_ID);

		assertThat(response.status().name()).isEqualTo("NO_ELIGIBLE_SIGNALS");
		assertThat(response.decisions()).hasSize(1);
		assertThat(response.decisions().getFirst().exclusionReasons())
			.containsExactly("OBJECTIVE_RATING_NOT_SCORE_ELIGIBLE");
		server.verify();
	}

	@Test
	void readsTheLatestAttemptThroughTheTypedReadOnlyPath() {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new ForwardValidationAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/forward-validation/"
							+ "prospective-enrollments/latest"))
			.andExpect(method(HttpMethod.GET))
			.andExpect(request -> assertThat(
					request.getHeaders().get("X-Test-Identity")).isNull())
			.andRespond(withSuccess(responseJson("BLOCKED"), MediaType.APPLICATION_JSON));

		var response = client.getLatestProspectiveEnrollment();

		assertThat(response.attemptId()).isEqualTo(ATTEMPT_ID);
		assertThat(response.status().name()).isEqualTo("BLOCKED");
		server.verify();
	}

	@Test
	void mapsStableErrorsWithoutExposingAnalyticsResponseBodies() {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new ForwardValidationAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/forward-validation/"
							+ "prospective-enrollments"))
			.andRespond(withStatus(HttpStatus.UNPROCESSABLE_ENTITY)
				.body("""
						{"detail":{
						  "code":"INVALID_MARKET_INTELLIGENCE_DECISION_SNAPSHOT",
						  "message":"provider payload C:/secret/raw.json"
						}}
						"""));

		assertThatThrownBy(() -> client.createProspectiveEnrollment(
				new ProspectiveEnrollmentRequest(DECISION_HASH, List.of(RUN_ID), null),
				"prospective-1"))
			.isInstanceOfSatisfying(
					ForwardValidationGatewayException.class,
					exception -> {
						assertThat(exception.code())
							.isEqualTo("INVALID_MARKET_INTELLIGENCE_DECISION_SNAPSHOT");
						assertThat(exception.status()).isEqualTo(400);
						assertThat(exception.getMessage())
							.doesNotContain("provider", "secret", "raw.json");
					});
		server.verify();
	}

	@Test
	void distinguishesInvalidRequestWithoutLeakingUnknownAnalyticsDetails() {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new ForwardValidationAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/forward-validation/"
							+ "prospective-enrollments"))
			.andRespond(withStatus(HttpStatus.UNPROCESSABLE_ENTITY)
				.body("{\"detail\":\"provider payload C:/secret/raw.json\"}"));

		assertThatThrownBy(() -> client.createProspectiveEnrollment(
				new ProspectiveEnrollmentRequest(DECISION_HASH, List.of(RUN_ID), null),
				"prospective-1"))
			.isInstanceOfSatisfying(
					ForwardValidationGatewayException.class,
					exception -> {
						assertThat(exception.code())
							.isEqualTo("INVALID_PROSPECTIVE_ENROLLMENT");
						assertThat(exception.status()).isEqualTo(400);
						assertThat(exception.getMessage())
							.doesNotContain("provider", "secret", "raw.json");
					});
		server.verify();
	}

	@Test
	void mapsNotFoundAndIdempotencyConflictToStableCodes() {
		RestClient.Builder builder = RestClient.builder()
			.baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new ForwardValidationAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/forward-validation/"
							+ "prospective-enrollments/latest"))
			.andRespond(withStatus(HttpStatus.NOT_FOUND));
		server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/forward-validation/"
							+ "prospective-enrollments"))
			.andRespond(withStatus(HttpStatus.CONFLICT));

		assertThatThrownBy(client::getLatestProspectiveEnrollment)
			.isInstanceOfSatisfying(
					ForwardValidationGatewayException.class,
					exception -> {
						assertThat(exception.code())
							.isEqualTo("PROSPECTIVE_ENROLLMENT_NOT_FOUND");
						assertThat(exception.status()).isEqualTo(404);
					});
		assertThatThrownBy(() -> client.createProspectiveEnrollment(
				new ProspectiveEnrollmentRequest(DECISION_HASH, List.of(RUN_ID), null),
				"prospective-1"))
			.isInstanceOfSatisfying(
					ForwardValidationGatewayException.class,
					exception -> {
						assertThat(exception.code()).isEqualTo("IDEMPOTENCY_KEY_CONFLICT");
						assertThat(exception.status()).isEqualTo(409);
					});
		server.verify();
	}

	private static String responseJson(String status) {
		boolean blocked = "BLOCKED".equals(status);
		return """
				{
				  "attemptId":"00000000-0000-0000-0000-000000000031",
				  "attemptHash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
				  "decisionSnapshotEventHash":"%s",
				  "status":"%s",
				  "dataSnapshotId":"00000000-0000-0000-0000-000000000032",
				  "decisionAsOf":"2026-07-29T02:00:00Z",
				  "profileCount":1,
				  "eligibleCount":%d,
				  "excludedCount":%d,
				  "signalCount":0,
				  "forwardEnrollmentId":null,
				  "maturitySchedule":[
				    {"horizon":"ONE_WEEK","tradingDays":5,
				     "maturesOn":"2026-08-05T20:00:00Z","status":"NOT_APPLICABLE"},
				    {"horizon":"ONE_MONTH","tradingDays":20,
				     "maturesOn":"2026-08-26T20:00:00Z","status":"NOT_APPLICABLE"},
				    {"horizon":"THREE_MONTHS","tradingDays":60,
				     "maturesOn":"2026-10-22T20:00:00Z","status":"NOT_APPLICABLE"}
				  ],
				  "decisions":[{
				    "profileId":"00000000-0000-0000-0000-000000000034",
				    "securityId":"00000000-0000-0000-0000-000000000035",
				    "symbol":"AAPL",
				    "state":"%s",
				    "exclusionReasons":%s,
				    "longHorizonContextHash":
				      "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
				  }],
				  "blockedReasons":%s,
				  "longHorizonIsContextOnly":true
				}
				""".formatted(
				DECISION_HASH,
				status,
				blocked ? 1 : 0,
				blocked ? 0 : 1,
				blocked ? "ELIGIBLE" : "EXCLUDED",
				blocked ? "[]" : "[\"OBJECTIVE_RATING_NOT_SCORE_ELIGIBLE\"]",
				blocked
						? "[\"COMPATIBLE_OBJECTIVE_SCREENING_RUN_REQUIRED\"]"
						: "[]");
	}
}
