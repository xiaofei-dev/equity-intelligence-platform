package com.xiaofei.equity.forwardvalidation;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

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

	public enum ProspectiveEnrollmentStatus {
		ENROLLED,
		NO_ELIGIBLE_SIGNALS,
		BLOCKED
	}

	public enum ProspectiveDecisionState {
		ELIGIBLE,
		EXCLUDED
	}

	public enum ProspectiveMaturityStatus {
		NOT_MATURED,
		NOT_APPLICABLE
	}

	public enum ProspectiveHorizon {
		ONE_WEEK,
		ONE_MONTH,
		THREE_MONTHS
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

	public record ProspectiveEnrollmentRequest(
			String decisionSnapshotEventHash,
			List<UUID> marketIntelligenceScreeningRunIds,
			UUID experimentId) {
	}

	public record ProspectiveMaturitySchedule(
			ProspectiveHorizon horizon,
			int tradingDays,
			Instant maturesOn,
			ProspectiveMaturityStatus status) {
	}

	public record ProspectiveSecurityDecision(
			UUID profileId,
			UUID securityId,
			String symbol,
			ProspectiveDecisionState state,
			List<String> exclusionReasons,
			String longHorizonContextHash) {
	}

	public record ProspectiveEnrollmentAccepted(
			UUID attemptId,
			String attemptHash,
			String decisionSnapshotEventHash,
			ProspectiveEnrollmentStatus status,
			UUID dataSnapshotId,
			Instant decisionAsOf,
			int profileCount,
			int eligibleCount,
			int excludedCount,
			int signalCount,
			UUID forwardEnrollmentId,
			List<ProspectiveMaturitySchedule> maturitySchedule,
			List<ProspectiveSecurityDecision> decisions,
			List<String> blockedReasons,
			boolean longHorizonIsContextOnly) {
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
