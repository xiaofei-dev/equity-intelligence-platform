package com.xiaofei.equity.forwardvalidation;

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
import java.util.List;
import java.util.UUID;

import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveDecisionState;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveEnrollmentAccepted;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveEnrollmentStatus;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveHorizon;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveMaturitySchedule;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveMaturityStatus;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveSecurityDecision;
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

@WebMvcTest({
	ForwardValidationController.class,
	ForwardValidationExceptionHandler.class,
	UserContextExceptionHandler.class
})
class ProspectiveEnrollmentControllerTests {

	private static final UUID ATTEMPT_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000031");

	private static final UUID RUN_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000033");

	private static final String DECISION_HASH =
			"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

	@Autowired
	private MockMvc mockMvc;

	@MockitoBean
	private ClosedTestIdentityResolver identityResolver;

	@MockitoBean
	private ForwardValidationAnalyticsClient analyticsClient;

	@BeforeEach
	void resolveIdentity() {
		when(identityResolver.resolve("tester-one")).thenReturn(new CurrentUser(
				UUID.fromString("00000000-0000-0000-0000-000000000001"),
				UUID.fromString("00000000-0000-0000-0000-000000000002"),
				"tester-one"));
	}

	@Test
	void createsBlockedAttemptAsSuccessfulTypedResponse() throws Exception {
		when(analyticsClient.createProspectiveEnrollment(any(), eq("prospective-1")))
			.thenReturn(accepted());

		mockMvc.perform(post("/api/v1/forward-validation/prospective-enrollments")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "prospective-1")
				.contentType(MediaType.APPLICATION_JSON)
				.content("""
						{
						  "decisionSnapshotEventHash":"%s",
						  "marketIntelligenceScreeningRunIds":["%s"],
						  "experimentId":null
						}
						""".formatted(DECISION_HASH, RUN_ID)))
			.andExpect(status().isCreated())
			.andExpect(header().string(
					"Location",
					"/api/v1/forward-validation/prospective-enrollments/"
							+ ATTEMPT_ID))
			.andExpect(jsonPath("$.status").value("BLOCKED"))
			.andExpect(jsonPath("$.decisionAsOf").value("2026-07-29T02:00:00Z"))
			.andExpect(jsonPath("$.eligibleCount").value(1))
			.andExpect(jsonPath("$.blockedReasons[0]").value(
					"COMPATIBLE_OBJECTIVE_SCREENING_RUN_REQUIRED"))
			.andExpect(jsonPath("$.maturitySchedule[0].tradingDays").value(5))
			.andExpect(jsonPath("$.maturitySchedule[1].tradingDays").value(20))
			.andExpect(jsonPath("$.maturitySchedule[2].tradingDays").value(60))
			.andExpect(jsonPath("$.longHorizonIsContextOnly").value(true));

		verify(identityResolver).resolve("tester-one");
		verify(analyticsClient).createProspectiveEnrollment(any(), eq("prospective-1"));
	}

	@Test
	void readsAttemptOnlyAfterResolvingClosedTestIdentity() throws Exception {
		when(analyticsClient.getProspectiveEnrollment(ATTEMPT_ID))
			.thenReturn(accepted());

		mockMvc.perform(get(
					"/api/v1/forward-validation/prospective-enrollments/{attemptId}",
					ATTEMPT_ID)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.attemptId").value(ATTEMPT_ID.toString()))
			.andExpect(jsonPath("$.decisions[0].symbol").value("AAPL"));

		verify(identityResolver).resolve("tester-one");
		verify(analyticsClient).getProspectiveEnrollment(ATTEMPT_ID);
	}

	@Test
	void readsLatestAttemptWithoutParsingLatestAsUuid() throws Exception {
		when(analyticsClient.getLatestProspectiveEnrollment()).thenReturn(accepted());

		mockMvc.perform(get(
					"/api/v1/forward-validation/prospective-enrollments/latest")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.attemptId").value(ATTEMPT_ID.toString()))
			.andExpect(jsonPath("$.status").value("BLOCKED"));

		verify(identityResolver).resolve("tester-one");
		verify(analyticsClient).getLatestProspectiveEnrollment();
	}

	@Test
	void exposesStableGatewayErrorWithoutInternalDetail() throws Exception {
		when(analyticsClient.getProspectiveEnrollment(ATTEMPT_ID))
			.thenThrow(new ForwardValidationGatewayException(
					"PROSPECTIVE_ENROLLMENT_NOT_FOUND",
					"The prospective-enrollment attempt was not found.",
					404));

		mockMvc.perform(get(
					"/api/v1/forward-validation/prospective-enrollments/{attemptId}",
					ATTEMPT_ID)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isNotFound())
			.andExpect(jsonPath("$.code").value(
					"PROSPECTIVE_ENROLLMENT_NOT_FOUND"))
			.andExpect(jsonPath("$.message").value(
					"The prospective-enrollment attempt was not found."));
	}

	private static ProspectiveEnrollmentAccepted accepted() {
		return new ProspectiveEnrollmentAccepted(
				ATTEMPT_ID,
				"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
				DECISION_HASH,
				ProspectiveEnrollmentStatus.BLOCKED,
				UUID.fromString("00000000-0000-0000-0000-000000000032"),
				Instant.parse("2026-07-29T02:00:00Z"),
				1,
				1,
				0,
				0,
				null,
				List.of(
						new ProspectiveMaturitySchedule(
								ProspectiveHorizon.ONE_WEEK,
								5,
								Instant.parse("2026-08-05T20:00:00Z"),
								ProspectiveMaturityStatus.NOT_APPLICABLE),
						new ProspectiveMaturitySchedule(
								ProspectiveHorizon.ONE_MONTH,
								20,
								Instant.parse("2026-08-26T20:00:00Z"),
								ProspectiveMaturityStatus.NOT_APPLICABLE),
						new ProspectiveMaturitySchedule(
								ProspectiveHorizon.THREE_MONTHS,
								60,
								Instant.parse("2026-10-22T20:00:00Z"),
								ProspectiveMaturityStatus.NOT_APPLICABLE)),
				List.of(new ProspectiveSecurityDecision(
						UUID.fromString("00000000-0000-0000-0000-000000000034"),
						UUID.fromString("00000000-0000-0000-0000-000000000035"),
						"AAPL",
						ProspectiveDecisionState.ELIGIBLE,
						List.of(),
						"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc")),
				List.of("COMPATIBLE_OBJECTIVE_SCREENING_RUN_REQUIRED"),
				true);
	}
}
