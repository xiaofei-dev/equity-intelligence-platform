package com.xiaofei.equity.screening;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

public final class ScreeningRatingContract {

	private ScreeningRatingContract() {
	}

	public enum AssessmentStatus {
		SCORED,
		INSUFFICIENT_DATA,
		NOT_DEFINED,
		NOT_APPLICABLE
	}

	public enum CohortLevel {
		SECTOR_SIZE_COMPANY_TYPE,
		SECTOR_COMPANY_TYPE,
		GENERAL_COMPANY
	}

	public enum CompanyType {
		MATURE_OPERATING_COMPANY,
		FINANCIAL,
		REIT,
		RESOURCE,
		BIOTECHNOLOGY,
		EMERGING_GROWTH,
		SPECIAL_SITUATION,
		BENCHMARK
	}

	public enum CoverageState {
		QUANT_ELIGIBLE,
		QUANT_INELIGIBLE,
		INSUFFICIENT_DATA,
		STALE,
		ANALYSIS_FAILED,
		SPECIALIZED_MODEL_REQUIRED
	}

	public enum ErrorCode {
		UNSUPPORTED_COMPANY_TYPE,
		INSUFFICIENT_DATA,
		STALE_DATA,
		PIT_LINEAGE_FAILED,
		INVALID_UNITS,
		COHORT_TOO_SMALL,
		STRATEGY_VERSION_UNSUPPORTED,
		ANALYSIS_FAILED
	}

	public enum FactorStatus {
		VALID,
		MISSING,
		INVALID,
		NOT_APPLICABLE
	}

	public enum Horizon {
		NEAR_TERM,
		MEDIUM_TERM,
		LONG_TERM
	}

	public enum RiskFlag {
		REVENUE_DECLINE,
		MARGIN_DETERIORATION,
		HIGH_LEVERAGE,
		LOW_INTEREST_COVERAGE,
		MATERIAL_DILUTION,
		GOING_CONCERN,
		PROVIDER_MISMATCH
	}

	public enum RunStatus {
		PENDING,
		RUNNING,
		SUCCEEDED,
		FAILED
	}

	public enum SizeCohort {
		SMALL,
		MID,
		LARGE,
		MEGA
	}

	public record RatingPage(
			String runId,
			List<SecurityRating> items,
			String nextCursor) {
	}

	public record ScreeningRunRequest(
			Instant asOfTime,
			String dataSnapshotId,
			String universeVersion,
			List<String> strategyVersions,
			boolean includeNearTermMarketCondition) {
	}

	public record ScreeningRunAccepted(
			String runId,
			RunStatus status,
			Instant submittedAt) {
	}

	public record CoverageSummary(
			int universeCount,
			int scoredCount,
			int ineligibleCount,
			int insufficientDataCount,
			int specializedModelCount) {
	}

	public record ScreeningRunStatus(
			String runId,
			RunStatus status,
			Instant asOfTime,
			String dataSnapshotId,
			String universeVersion,
			List<String> strategyVersions,
			Instant submittedAt,
			Instant startedAt,
			Instant completedAt,
			CoverageSummary coverage,
			ErrorCode errorCode,
			String errorMessage) {
	}

	public record SecurityRating(
			String securityId,
			String symbol,
			Instant asOfTime,
			CoverageState coverageState,
			CompanyType companyType,
			SizeCohort sizeCohort,
			BigDecimal qualityScore,
			BigDecimal valuationScore,
			List<FactorResult> factorResults,
			List<HorizonAssessment> horizonAssessments,
			List<RiskFlag> riskFlags,
			List<String> missingReasons,
			List<DataLineage> lineage) {
	}

	public record FactorResult(
			String name,
			FactorStatus status,
			BigDecimal rawValue,
			BigDecimal winsorizedValue,
			BigDecimal normalizedScore,
			CohortLevel cohortLevel,
			Integer cohortSize,
			String reason) {
	}

	public record HorizonAssessment(
			Horizon horizon,
			AssessmentStatus status,
			BigDecimal score,
			String label,
			List<StrategyRating> strategyRatings) {
	}

	public record StrategyRating(
			String strategyVersion,
			AssessmentStatus status,
			BigDecimal score,
			Integer rank,
			List<FactorContribution> contributions,
			List<String> missingFactors,
			ErrorCode errorCode) {
	}

	public record FactorContribution(
			String factorName,
			BigDecimal normalizedScore,
			BigDecimal weight,
			BigDecimal contribution) {
	}

	public record DataLineage(
			String provider,
			String sourceReference,
			LocalDate periodEnd,
			Instant filedAt,
			Instant availableAt,
			Instant ingestedAt,
			String currency,
			String unit,
			String revisionStatus,
			String qualityStatus,
			String contentHash) {
	}
}
