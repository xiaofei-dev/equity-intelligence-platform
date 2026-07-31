package com.xiaofei.equity.forwardvalidation;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.Test;

import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardReport;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveEnrollmentAccepted;

import tools.jackson.databind.json.JsonMapper;

class ForwardValidationContractTests {

	@Test
	void sharedFixturePreservesPrecisionAndStatisticalBoundary() throws Exception {
		var mapper = JsonMapper.builder().findAndAddModules().build();
		var path = Path.of("..", "contracts", "forward-validation-v1.example.json");
		var report = mapper.readValue(Files.readString(path), ForwardReport.class);

		assertThat(report.operationalCompleteness())
				.isEqualByComparingTo(new BigDecimal("0.97500000"));
		assertThat(report.statisticalEdgeProven()).isEqualTo("NOT_ESTABLISHED");
		assertThat(report.preliminaryConclusion().name()).isEqualTo("INSUFFICIENT_SAMPLE");
	}

	@Test
	void prospectiveContractPreservesFrozenSchedulesAndExplicitBlockedState()
			throws Exception {
		var mapper = JsonMapper.builder().findAndAddModules().build();
		var response = mapper.readValue("""
				{
				  "attemptId":"00000000-0000-0000-0000-000000000031",
				  "attemptHash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
				  "decisionSnapshotEventHash":
				    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				  "status":"BLOCKED",
				  "dataSnapshotId":"00000000-0000-0000-0000-000000000032",
				  "decisionAsOf":"2026-07-29T02:00:00Z",
				  "profileCount":1,
				  "eligibleCount":1,
				  "excludedCount":0,
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
				    "state":"ELIGIBLE",
				    "exclusionReasons":[],
				    "longHorizonContextHash":
				      "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
				  }],
				  "blockedReasons":["COMPATIBLE_OBJECTIVE_SCREENING_RUN_REQUIRED"],
				  "longHorizonIsContextOnly":true
				}
				""", ProspectiveEnrollmentAccepted.class);

		assertThat(response.attemptId()).isEqualTo(UUID.fromString(
				"00000000-0000-0000-0000-000000000031"));
		assertThat(response.decisionAsOf()).isEqualTo(
				Instant.parse("2026-07-29T02:00:00Z"));
		assertThat(response.status().name()).isEqualTo("BLOCKED");
		assertThat(response.maturitySchedule())
			.extracting(schedule -> schedule.tradingDays())
			.isEqualTo(List.of(5, 20, 60));
		assertThat(response.decisions().getFirst().exclusionReasons()).isEmpty();
		assertThat(response.longHorizonIsContextOnly()).isTrue();
	}
}
