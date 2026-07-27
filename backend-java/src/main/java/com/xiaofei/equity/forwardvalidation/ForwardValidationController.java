package com.xiaofei.equity.forwardvalidation;

import java.util.List;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.EnrollmentAccepted;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.EnrollmentRequest;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardExperimentAccepted;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardExperimentRequest;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardExperimentStatus;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardReport;

@RestController
@RequestMapping("/api/v1/forward-validation")
public class ForwardValidationController {

	private final ForwardValidationAnalyticsClient analyticsClient;

	public ForwardValidationController(ForwardValidationAnalyticsClient analyticsClient) {
		this.analyticsClient = analyticsClient;
	}

	@PostMapping("/experiments")
	public ResponseEntity<ForwardExperimentAccepted> createExperiment(
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@RequestBody ForwardExperimentRequest request) {
		return ResponseEntity.status(HttpStatus.ACCEPTED)
				.body(analyticsClient.createExperiment(request, idempotencyKey));
	}

	@GetMapping("/experiments/{experimentId}")
	public ForwardExperimentStatus getExperiment(@PathVariable String experimentId) {
		return analyticsClient.getExperiment(experimentId);
	}

	@PostMapping("/experiments/{experimentId}/enrollments")
	public ResponseEntity<EnrollmentAccepted> createEnrollment(
			@PathVariable String experimentId,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@RequestBody EnrollmentRequest request) {
		return ResponseEntity.status(HttpStatus.CREATED)
				.body(analyticsClient.createEnrollment(experimentId, request, idempotencyKey));
	}

	@GetMapping("/experiments/{experimentId}/{projection:signals|observations}")
	public List<Map<String, Object>> getRows(
			@PathVariable String experimentId, @PathVariable String projection) {
		return analyticsClient.getRows(experimentId, projection);
	}

	@GetMapping("/experiments/{experimentId}/reports/{reportType}")
	public ForwardReport getReport(
			@PathVariable String experimentId, @PathVariable String reportType) {
		return analyticsClient.getReport(experimentId, reportType);
	}
}
