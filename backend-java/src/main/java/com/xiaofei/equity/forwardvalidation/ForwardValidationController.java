package com.xiaofei.equity.forwardvalidation;

import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.UUID;

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
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveEnrollmentAccepted;
import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ProspectiveEnrollmentRequest;
import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;

@RestController
@RequestMapping("/api/v1/forward-validation")
public class ForwardValidationController {

	private final ClosedTestIdentityResolver identityResolver;

	private final ForwardValidationAnalyticsClient analyticsClient;

	public ForwardValidationController(
			ClosedTestIdentityResolver identityResolver,
			ForwardValidationAnalyticsClient analyticsClient) {
		this.identityResolver = identityResolver;
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

	@PostMapping("/prospective-enrollments")
	public ResponseEntity<ProspectiveEnrollmentAccepted> createProspectiveEnrollment(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@RequestBody ProspectiveEnrollmentRequest request) {
		identityResolver.resolve(identity);
		ProspectiveEnrollmentAccepted response =
				analyticsClient.createProspectiveEnrollment(request, idempotencyKey);
		return ResponseEntity.created(
				URI.create("/api/v1/forward-validation/prospective-enrollments/"
						+ response.attemptId()))
			.body(response);
	}

	@GetMapping("/prospective-enrollments/latest")
	public ProspectiveEnrollmentAccepted getLatestProspectiveEnrollment(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity) {
		identityResolver.resolve(identity);
		return analyticsClient.getLatestProspectiveEnrollment();
	}

	@GetMapping("/prospective-enrollments/{attemptId}")
	public ProspectiveEnrollmentAccepted getProspectiveEnrollment(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable UUID attemptId) {
		identityResolver.resolve(identity);
		return analyticsClient.getProspectiveEnrollment(attemptId);
	}
}
