package com.xiaofei.equity.screening;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.xiaofei.equity.screening.ScreeningRatingContract.RatingPage;
import com.xiaofei.equity.screening.ScreeningRatingContract.ScreeningRunAccepted;
import com.xiaofei.equity.screening.ScreeningRatingContract.ScreeningRunRequest;
import com.xiaofei.equity.screening.ScreeningRatingContract.ScreeningRunStatus;

@RestController
@RequestMapping("/api/v1/screening")
public class ScreeningController {

	private final ScreeningAnalyticsClient analyticsClient;

	public ScreeningController(ScreeningAnalyticsClient analyticsClient) {
		this.analyticsClient = analyticsClient;
	}

	@PostMapping("/runs")
	public ResponseEntity<ScreeningRunAccepted> createRun(
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@RequestBody ScreeningRunRequest request) {
		return ResponseEntity.status(HttpStatus.ACCEPTED)
				.body(analyticsClient.createRun(request, idempotencyKey));
	}

	@GetMapping("/runs/{runId}")
	public ResponseEntity<ScreeningRunStatus> getRun(@PathVariable String runId) {
		return ResponseEntity.ok(analyticsClient.getRun(runId));
	}

	@GetMapping("/runs/{runId}/ratings")
	public ResponseEntity<RatingPage> getRatings(
			@PathVariable String runId,
			@RequestParam(required = false) String cursor) {
		return ResponseEntity.ok(analyticsClient.getRatings(runId, cursor));
	}
}
