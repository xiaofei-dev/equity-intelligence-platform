package com.xiaofei.equity.marketintelligence;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import tools.jackson.databind.JsonNode;

public final class MarketIntelligenceContract {

	private MarketIntelligenceContract() {
	}

	public enum AiNarrativeStatus {
		NOT_EXECUTED,
		AVAILABLE,
		INSUFFICIENT_EVIDENCE,
		FAILED
	}

	public enum DeterministicViewState {
		ASSESSED,
		INSUFFICIENT_DATA,
		NOT_APPLICABLE
	}

	public enum FactState {
		VALID,
		MISSING,
		INVALID,
		NOT_APPLICABLE
	}

	public enum Horizon {
		ONE_WEEK,
		ONE_MONTH,
		THREE_MONTHS,
		TWELVE_MONTHS_PLUS
	}

	public enum ProfileState {
		COMPLETE,
		PARTIAL,
		INELIGIBLE
	}

	public enum RankingState {
		ELIGIBLE,
		NOT_ELIGIBLE
	}

	public enum RankMetric {
		OBJECTIVE_QUALITY,
		OBJECTIVE_VALUATION,
		TACTICAL_ONE_WEEK,
		TACTICAL_ONE_MONTH,
		TACTICAL_THREE_MONTHS,
		LONG_HORIZON,
		BUYING_OPPORTUNITY
	}

	public enum RunState {
		SEALED,
		FAILED
	}

	public enum EligibilityRecoveryStatus {
		READY_FOR_CONFIRMATION,
		NO_ACTIONABLE_REQUESTS,
		BLOCKED_COHORT_UNREACHABLE,
		BLOCKED_EVIDENCE_SEMANTICS,
		BLOCKED_BUDGET,
		BLOCKED_SNAPSHOT
	}

	public enum EligibilityRecoverySecurityState {
		ALREADY_ELIGIBLE,
		RECOVERABLE,
		BLOCKED,
		NOT_APPLICABLE
	}

	public enum SortDirection {
		ASCENDING,
		DESCENDING
	}

	public record ScreeningFilter(
			List<String> sectors,
			List<String> industries,
			List<String> companyTypes,
			List<String> symbols,
			List<Horizon> horizons,
			Boolean requireRankingEligible) {

		public ScreeningFilter {
			sectors = immutable(sectors);
			industries = immutable(industries);
			companyTypes = immutable(companyTypes);
			symbols = immutable(symbols);
			horizons = immutable(horizons);
			requireRankingEligible = requireRankingEligible == null
					? Boolean.TRUE : requireRankingEligible;
		}
	}

	public record ScreeningRunRequest(
			UUID dataSnapshotId,
			String universeVersion,
			Instant asOf,
			ScreeningFilter filters,
			RankMetric rankBy,
			SortDirection direction,
			Integer limit) {

		public ScreeningRunRequest {
			filters = filters == null
					? new ScreeningFilter(null, null, null, null, null, true)
					: filters;
			direction = direction == null ? SortDirection.DESCENDING : direction;
			limit = limit == null ? 50 : limit;
		}
	}

	public record ScreeningRunMetadata(
			UUID runId,
			RunState state,
			UUID dataSnapshotId,
			String universeVersion,
			Instant asOf,
			RankMetric rankBy,
			SortDirection direction,
			int eligibleCount,
			int excludedCount,
			String gateStatus,
			String profileSetHash,
			String resultHash,
			Instant sealedAt) {
	}

	public record ScreeningResultPage(
			ScreeningRunMetadata run,
			List<ProfileResponse> items,
			String nextCursor) {

		public ScreeningResultPage {
			items = immutable(items);
		}
	}

	public record ProfileResponse(
			UUID profileId,
			UUID securityId,
			SecurityProfile profile,
			CurrentMarketData currentMarketData,
			List<DatasetFreshness> freshness,
			Map<String, String> modelVersions) {

		public ProfileResponse {
			freshness = immutable(freshness);
			modelVersions = modelVersions == null ? Map.of() : Map.copyOf(modelVersions);
		}
	}

	public record SecurityProfile(
			String contractVersion,
			SecurityMaster security,
			Classification classification,
			List<ComparableCohort> comparableCohorts,
			List<ProfileFact> facts,
			BigDecimal objectiveQualityScore,
			BigDecimal objectiveValuationScore,
			String objectiveRatingStatus,
			String objectiveRatingVersion,
			List<HorizonView> horizons,
			ValuationEvidence valuation,
			ProfileState profileState,
			RankingState rankingState,
			List<String> rankingExclusions,
			List<String> explainability,
			AiNarrative aiNarrative) {

		public SecurityProfile {
			comparableCohorts = immutable(comparableCohorts);
			facts = immutable(facts);
			horizons = immutable(horizons);
			rankingExclusions = immutable(rankingExclusions);
			explainability = immutable(explainability);
		}
	}

	public record SecurityMaster(
			UUID securityId,
			String symbol,
			String issuerName,
			String exchangeMic,
			String currency,
			String instrumentType,
			String cik,
			String durableProviderId) {
	}

	public record Classification(
			String taxonomyCode,
			String taxonomyVersion,
			String sectorCode,
			String sectorName,
			String industryCode,
			String industryName,
			String companyType,
			Instant effectiveAt,
			List<EvidenceLineage> lineage) {

		public Classification {
			lineage = immutable(lineage);
		}
	}

	public record ComparableCohort(
			String cohortId,
			String taxonomyVersion,
			String sectorCode,
			String industryCode,
			String companyType,
			String sizeBand,
			int eligibleMemberCount,
			int minimumMemberCount) {
	}

	public record ProfileFact(
			String name,
			String metricVersion,
			FactState state,
			JsonNode value,
			String reason,
			List<EvidenceLineage> lineage) {

		public ProfileFact {
			lineage = immutable(lineage);
		}
	}

	public record EvidenceLineage(
			String providerCode,
			String providerSchemaVersion,
			String parserVersion,
			String sourceReference,
			String contentHash,
			Instant availableAt,
			Instant retrievedAt,
			Instant effectiveAt) {
	}

	public record HorizonView(
			Horizon horizon,
			DeterministicView deterministicView) {
	}

	public record DeterministicView(
			String modelId,
			String modelVersion,
			DeterministicViewState state,
			Instant asOf,
			Instant effectiveAt,
			Instant expiresAt,
			BigDecimal score,
			String label,
			String inputHash,
			String evidenceHash,
			List<String> missingInputs,
			List<String> explanation) {

		public DeterministicView {
			missingInputs = immutable(missingInputs);
			explanation = immutable(explanation);
		}
	}

	public record ValuationEvidence(
			FactState state,
			Instant asOf,
			BigDecimal objectiveValuationScore,
			BigDecimal longHorizonValuationScore,
			BigDecimal ownHistoryPercentile,
			List<ProfileFact> evidence,
			List<String> limitations) {

		public ValuationEvidence {
			evidence = immutable(evidence);
			limitations = immutable(limitations);
		}
	}

	public record CurrentMarketData(
			FactState state,
			BigDecimal price,
			String currency,
			LocalDate tradingDate,
			String providerCode,
			Instant availableAt,
			Instant ingestedAt,
			String adjustmentMode,
			String reason) {
	}

	public record DatasetFreshness(
			String datasetCode,
			String state,
			String providerCode,
			Instant effectiveAt,
			Instant availableAt,
			Instant ingestedAt,
			Instant evaluatedAt,
			Instant staleAfter,
			String reasonCode) {
	}

	public record AiNarrative(
			AiNarrativeStatus status,
			String narrative,
			List<String> sourceReferences,
			Instant generatedAt,
			String promptVersion,
			String modelVersion,
			String confidence,
			boolean mayAffectDeterministicFields) {

		public AiNarrative {
			sourceReferences = immutable(sourceReferences);
		}
	}

	public record SecuritySearchPage(
			UUID dataSnapshotId,
			String universeVersion,
			List<SecuritySearchItem> items,
			String nextCursor) {

		public SecuritySearchPage {
			items = immutable(items);
		}
	}

	public record SecuritySearchItem(
			UUID securityId,
			String symbol,
			String issuerName,
			String exchangeMic,
			String membershipStatus,
			String companyType,
			String sector,
			String industry,
			UUID latestProfileId,
			CurrentMarketData currentMarketData,
			List<DatasetFreshness> freshness,
			Map<String, String> modelVersions) {

		public SecuritySearchItem {
			freshness = immutable(freshness);
			modelVersions = modelVersions == null ? Map.of() : Map.copyOf(modelVersions);
		}
	}

	public record MarketIntelligenceFacets(
			UUID dataSnapshotId,
			String universeVersion,
			List<String> sectors,
			List<String> industries,
			List<String> companyTypes,
			List<String> membershipStatuses) {

		public MarketIntelligenceFacets {
			sectors = immutable(sectors);
			industries = immutable(industries);
			companyTypes = immutable(companyTypes);
			membershipStatuses = immutable(membershipStatuses);
		}
	}

	public record EligibilityRecoveryStatusResponse(
			String schemaVersion,
			String preflightId,
			Instant generatedAt,
			UUID dataSnapshotId,
			String universeVersion,
			Instant snapshotAsOf,
			String objectiveRatingVersion,
			String recoveryPolicyVersion,
			EligibilityRecoveryStatus status,
			int currentEligibleCount,
			int frozenMinimumEligibleCount,
			int maximumEligibleAfterPlan,
			int dueSecurityCount,
			List<String> dueSymbols,
			int persistedEvidenceReuseCount,
			int profileCount,
			int resultCount,
			List<EligibilityRecoveryRequestPlan> requestPlan,
			List<EligibilityBlockerSummary> blockerSummary,
			List<EligibilityFreshnessSummary> freshness,
			List<EligibilitySecurityDiagnostic> securityDiagnostics,
			boolean confirmationRequired,
			boolean networkRequestsExecuted,
			boolean scoresOrRanksGenerated,
			String artifactContentHash) {

		public EligibilityRecoveryStatusResponse {
			dueSymbols = immutable(dueSymbols);
			requestPlan = immutable(requestPlan);
			blockerSummary = immutable(blockerSummary);
			freshness = immutable(freshness);
			securityDiagnostics = immutable(securityDiagnostics);
		}
	}

	public record EligibilityRecoveryRequestPlan(
			String provider,
			String endpointCode,
			String dataset,
			List<String> symbols,
			int physicalRequestHardCeiling,
			int weightedCallHardCeiling,
			int runnerMaximumAttempts) {

		public EligibilityRecoveryRequestPlan {
			symbols = immutable(symbols);
		}
	}

	public record EligibilityBlockerSummary(
			String category,
			String reasonCode,
			String actionability,
			int affectedSecurityCount) {
	}

	public record EligibilityFreshnessSummary(
			String datasetCode,
			String state,
			Instant evaluatedAt,
			Instant staleAfter,
			String reasonCode,
			int affectedSecurityCount) {
	}

	public record EligibilitySecurityDiagnostic(
			UUID securityId,
			String symbol,
			EligibilityRecoverySecurityState state,
			List<EligibilityMissingOperand> missingOperands,
			List<EligibilitySecurityFreshness> freshness) {

		public EligibilitySecurityDiagnostic {
			missingOperands = immutable(missingOperands);
			freshness = immutable(freshness);
		}
	}

	public record EligibilityMissingOperand(
			String factorCode,
			String operandCode,
			String reasonCode,
			String providerRoute,
			String actionability) {
	}

	public record EligibilitySecurityFreshness(
			String datasetCode,
			String state,
			Instant evaluatedAt,
			Instant staleAfter,
			String reasonCode) {
	}

	private static <T> List<T> immutable(List<T> values) {
		return values == null ? List.of() : List.copyOf(values);
	}
}
