package com.xiaofei.equity.forwardvalidation;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Map;

public final class ForwardValidationContract {

	private ForwardValidationContract() {
	}

	public enum ExperimentMode {
		DRY_RUN,
		FORMAL
	}

	public enum ExperimentStatus {
		PENDING,
		ACTIVE,
		PAUSED,
		COMPLETED,
		FAILED
	}

	public enum PreliminaryConclusion {
		PROMISING,
		MIXED,
		UNFAVORABLE,
		INSUFFICIENT_SAMPLE
	}

	public record ForwardExperimentRequest(
			String screeningRunId,
			ExperimentMode mode,
			String experimentVersion,
			String entryPolicyVersion,
			String costModelVersion,
			String cashReturnVersion,
			String sectorBenchmarkMapVersion,
			BigDecimal notionalUsd,
			String providerAcceptanceId) {
	}

	public record ForwardExperimentAccepted(
			String experimentId,
			ExperimentStatus status,
			ExperimentMode mode,
			Instant submittedAt) {
	}

	public record ForwardExperimentStatus(
			String experimentId,
			ExperimentStatus status,
			ExperimentMode mode,
			Instant submittedAt,
			String screeningRunId,
			String experimentVersion,
			String entryPolicyVersion,
			String providerAcceptanceId,
			BigDecimal notionalUsd) {
	}

	public record EnrollmentRequest(
			String screeningRunId,
			Instant enrollmentTime) {
	}

	public record EnrollmentAccepted(
			String enrollmentId,
			int signalCount,
			Instant sealedAt,
			String inputHash) {
	}

	public record ResultRows(
			Map<String, Object>[] items) {
	}

	public record ForwardReport(
			String experimentId,
			String reportType,
			Instant asOfTime,
			PreliminaryConclusion preliminaryConclusion,
			String statisticalEdgeProven,
			int completedEpisodeCount,
			BigDecimal operationalCompleteness,
			String resultHash) {
	}
}
