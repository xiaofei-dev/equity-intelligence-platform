package com.xiaofei.equity.screening;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import com.xiaofei.equity.screening.ScreeningRatingContract.RatingPage;
import com.xiaofei.equity.screening.ScreeningRatingContract.RunStatus;
import com.xiaofei.equity.screening.ScreeningRatingContract.ScreeningRunAccepted;

@WebMvcTest(ScreeningController.class)
class ScreeningControllerTests {

	@Autowired
	private MockMvc mockMvc;

	@MockitoBean
	private ScreeningAnalyticsClient analyticsClient;

	@Test
	void proxiesCreateRunWithCallerIdempotencyKey() throws Exception {
		when(analyticsClient.createRun(any(), any())).thenReturn(
				new ScreeningRunAccepted(
						"00000000-0000-0000-0000-000000000001",
						RunStatus.PENDING,
						Instant.parse("2026-07-26T20:00:00Z")));

		mockMvc.perform(post("/api/v1/screening/runs")
				.header("Idempotency-Key", "screening-test-1")
				.contentType(MediaType.APPLICATION_JSON)
				.content("""
						{
						  "asOfTime":"2026-07-25T20:00:00Z",
						  "dataSnapshotId":"snapshot-2026-07-25",
						  "universeVersion":"universe-us-general-company-v1.0.0",
						  "strategyVersions":["QC-v1.0.0","UQ-v1.0.0"],
						  "includeNearTermMarketCondition":true
						}
						"""))
				.andExpect(status().isAccepted())
				.andExpect(jsonPath("$.status").value("PENDING"));
	}

	@Test
	void requiresIdempotencyHeader() throws Exception {
		mockMvc.perform(post("/api/v1/screening/runs")
				.contentType(MediaType.APPLICATION_JSON)
				.content("{}"))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.code").value("IDEMPOTENCY_KEY_REQUIRED"));
	}

	@Test
	void proxiesRatingPages() throws Exception {
		when(analyticsClient.getRatings("run-1", "next")).thenReturn(
				new RatingPage("run-1", List.of(), null));

		mockMvc.perform(get("/api/v1/screening/runs/run-1/ratings")
				.queryParam("cursor", "next"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.runId").value("run-1"));
	}
}
