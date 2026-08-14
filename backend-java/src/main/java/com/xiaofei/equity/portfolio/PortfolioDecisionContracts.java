package com.xiaofei.equity.portfolio;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import tools.jackson.databind.JsonNode;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

public final class PortfolioDecisionContracts {
	private PortfolioDecisionContracts() {
	}

	public enum ScenarioType {
		HOLD_CURRENT, NEW_MONEY_ONLY, CONSTRAINED_REBALANCE, TARGET_PORTFOLIO
	}

	public enum Permission {
		LOCKED, BUY_ONLY, SELL_ONLY, BUY_AND_SELL
	}

	public enum Conclusion {
		ACCEPTED, REJECTED, DEFERRED, NO_ACTION
	}
	public enum ThesisReviewState {
		CONFIRMED, WEAKENED, INVALIDATED, INSUFFICIENT_EVIDENCE
	}

	public record CandidateInput(
			@NotNull UUID securityId,
			@NotNull Permission permission,
			boolean humanApprovedCandidate,
			@DecimalMin("0") BigDecimal targetMarketValue) {
	}
	public record SleeveBudgetInput(
			@NotNull UnifiedPortfolioContracts.SleeveType sleeve,
			@NotNull @DecimalMin("0") BigDecimal maximumWeight) {}

	public record CreateScenarioRequest(
			@NotNull UUID contextId,
			@NotNull UUID evidenceManifestId,
			@NotNull UUID constraintPolicyVersionId,
			@NotNull ScenarioType scenarioType,
			@NotNull @DecimalMin("0") BigDecimal newMoneyAmount,
			@NotEmpty @Size(min = 2, max = 2) List<@Valid SleeveBudgetInput> sleeveBudgets,
			@NotEmpty @Size(max = 500) List<@Valid CandidateInput> candidates) {
		public CreateScenarioRequest {
			sleeveBudgets = sleeveBudgets == null ? null : List.copyOf(sleeveBudgets);
			candidates = candidates == null ? null : List.copyOf(candidates);
		}
	}
	public record CreateScenarioComparisonRequest(
			@NotNull UUID contextId,
			@NotNull UUID evidenceManifestId,
			@NotNull UUID constraintPolicyVersionId,
			@NotNull @DecimalMin("0") BigDecimal newMoneyAmount,
			@NotEmpty @Size(min = 2, max = 2) List<@Valid SleeveBudgetInput> sleeveBudgets,
			@NotEmpty @Size(max = 500) List<@Valid CandidateInput> candidates) {
		public CreateScenarioComparisonRequest {
			sleeveBudgets = sleeveBudgets == null ? null : List.copyOf(sleeveBudgets);
			candidates = candidates == null ? null : List.copyOf(candidates);
		}
	}
	public record SelectScenarioComparisonRequest(@NotNull ScenarioType selectedScenarioType) {}

	public record SealLongitudinalRequest(
			@NotNull Integer horizonSessions,
			@NotNull UUID maturationCommandId) {}
	public record SealLongitudinalByHorizonRequest(@NotNull Integer horizonSessions) {}

	public record CreateThesisReviewRequest(
			@NotNull Integer horizonSessions,
			@NotNull ThesisReviewState state,
			@NotBlank @Size(max = 4000) String rationale,
			UUID supersedesReviewId) {}

	public record ScenarioResponse(
			UUID scenarioId,
			UUID portfolioId,
			UUID contextId,
			ScenarioType scenarioType,
			String scenarioState,
			Instant decisionCutoff,
			String economicPolicyVersion,
			String candidateState,
			List<DecisionEvidence> evidence,
			List<DecisionPosition> positions,
			DecisionEconomics economics,
			List<String> reasonCodes,
			RecommendationSummary recommendation,
			HumanDecisionSummary humanDecision,
			DecisionAuthority authority,
			String contentHash) {
		public ScenarioResponse {
			decisionCutoff = wholeSecond(decisionCutoff);
		}
	}

	public record DecisionEvidence(UUID securityId, String dataState,
			String fundamentalEvidenceLabel, String quantEvidenceLabel) {}
	public record DecisionPosition(UUID securityId, String ticker, String sleeve,
			String currentValue, String targetValue, String valueDelta, String targetWeight,
			String permission, String estimatedCost, String estimatedTax) {}
	public record DecisionEconomics(String newMoneyAmount, String transactionCostBps,
			String slippageBps, String grossBuyNotional, String grossSellNotional,
			String grossTradedNotional, String estimatedTransactionAndSlippageCost,
			String impactState, String taxEstimateState, String taxEstimateAmount,
			String appliedTaxAmount, String oneWayWeightTurnover,
			String grossTradedNotionalRate, String finalCash, String finalAssetValue) {}
	public record RecommendationSummary(UUID recommendationId, String state,
			List<String> reasonCodes, String contentHash) {}
	public record HumanDecisionSummary(UUID decisionId, Conclusion conclusion,
			String rationale, Instant decidedAt, String contentHash) {
		public HumanDecisionSummary { decidedAt = wholeSecond(decidedAt); }
	}
	public record DecisionAuthority(boolean candidateForHumanReviewOnly,
			boolean finalWeightAuthority, boolean orderAuthority,
			boolean automaticBrokerageExecution, boolean llmDecisionAuthority,
			boolean humanDecisionRequired) {}

	public record EvaluationResponse(
			UUID evaluationId,
			UUID portfolioId,
			UUID humanDecisionId,
			UUID startingContextId,
			UUID acceptedScenarioId,
			UUID holdCurrentScenarioId,
			String state,
			String benchmarkCode,
			boolean simulatedOnly,
			List<EvaluationMaturity> maturities,
			List<EvaluationPeriodSummary> summaries,
			Instant recordedAt) {
	}
	public record EvaluationMaturity(int horizonSessions, String state, String terminalReason,
			Instant observedAt) {}
	public record EvaluationPeriodSummary(int horizonSessions,String periodStart, String periodEnd,
			int expectedObservationCount, int observationCount, String grossReturn,
			String netReturn, String benchmarkReturn, String excessReturn,
			String holdCurrentReturn, String acceptedExcessVsHoldCurrent,
			String maximumDrawdown, String totalTurnover, String totalCost, String coverageRate) {}
	public record ObservationSelectorInput(@NotNull UUID securityId,
			@NotNull UUID selectionRequestId) {}
	@JsonIgnoreProperties(ignoreUnknown = false)
	public record RecordObservationRequest(@NotNull UUID completedSessionId,
			@NotEmpty List<@Valid ObservationSelectorInput> acceptedSelectorRequestIds,
			@NotEmpty List<@Valid ObservationSelectorInput> holdSelectorRequestIds,
			@NotNull UUID benchmarkSelectorRequestId) {
		public RecordObservationRequest {
			acceptedSelectorRequestIds=acceptedSelectorRequestIds==null?null:List.copyOf(acceptedSelectorRequestIds);
			holdSelectorRequestIds=holdSelectorRequestIds==null?null:List.copyOf(holdSelectorRequestIds);
		}
	}
	@JsonIgnoreProperties(ignoreUnknown = false)
	public record RecordExternalCashFlowRequest(@NotNull UUID completedSessionId,
			@NotNull BigDecimal amount,@NotBlank @Size(max=256) String reason) {}
	@JsonIgnoreProperties(ignoreUnknown = false)
	public record ProgressMaturityRequest(@NotNull UUID completedSessionId,
			@NotNull Integer horizonSessions,@Size(max=256) String terminalReason) {}

	@JsonIgnoreProperties(ignoreUnknown = false)
	public record CreateEvaluationRequest(
			@NotNull UUID humanDecisionId,
			@NotNull UUID startingContextId,
			@NotNull UUID holdCurrentScenarioId) {
	}

	@JsonIgnoreProperties(ignoreUnknown = false)
	public record HumanDecisionRequest(
			@NotNull Conclusion conclusion,
			@NotBlank @Size(max = 4000) String rationale,
			UUID supersedesDecisionId) {
	}

	public record HumanDecisionResponse(
			UUID decisionId,
			UUID scenarioId,
			UUID recommendationId,
			Conclusion conclusion,
			String rationale,
			UUID supersedesDecisionId,
			Instant decidedAt,
			Instant recordedAt) {
		public HumanDecisionResponse {
			decidedAt = wholeSecond(decidedAt);
			recordedAt = wholeSecond(recordedAt);
		}
	}

	public record ScenarioComparisonItem(
			ScenarioType scenarioType,
			UUID scenarioId,
			String scenarioContentHash,
			ScenarioProjection scenario) {}
	public record ScenarioProjection(
			UUID scenarioId,
			ScenarioType scenarioType,
			String scenarioState,
			String candidateState,
			List<DecisionPosition> positions,
			DecisionEconomics economics,
			List<String> reasonCodes,
			String contentHash) {
		public ScenarioProjection {
			positions = positions == null ? null : List.copyOf(positions);
			reasonCodes = reasonCodes == null ? null : List.copyOf(reasonCodes);
		}
	}

	public record ScenarioComparisonResponse(
			UUID comparisonId,
			UUID portfolioId,
			UUID contextId,
			int expectedScenarioCount,
			List<ScenarioComparisonItem> scenarios,
			UUID selectedScenarioId,
			String recommendationBindingState,
			String contentHash,
			Instant sealedAt) {
		public ScenarioComparisonResponse {
			scenarios = scenarios == null ? null : List.copyOf(scenarios);
			sealedAt = wholeSecond(sealedAt);
		}
	}

	public record LongitudinalProjectionResponse(
			UUID evaluationId,
			UUID portfolioId,
			List<LongitudinalPeriod> periods,
			List<ThesisReviewSummary> thesisReviews) {
		public LongitudinalProjectionResponse {
			periods = periods == null ? null : List.copyOf(periods);
			thesisReviews = thesisReviews == null ? null : List.copyOf(thesisReviews);
		}
	}
	public record LongitudinalPeriod(
			int horizonSessions,
			String state,
			String periodStart,
			String periodEnd,
			int expectedObservationCount,
			int observationCount,
			String coverageRate,
			String grossReturn,
			String netReturn,
			String holdCurrentReturn,
			String benchmarkReturn,
			String excessVsHoldCurrent,
			String excessVsBenchmark,
			String trueMaximumDrawdown,
			String totalTurnover,
			String totalCost,
			String contentHash) {}
	public record ThesisReviewSummary(
			UUID reviewId,
			int horizonSessions,
			ThesisReviewState state,
			String rationale,
			UUID supersedesReviewId,
			Instant reviewedAt,
			String contentHash) {
		public ThesisReviewSummary { reviewedAt = wholeSecond(reviewedAt); }
	}

	private static Instant wholeSecond(Instant value) {
		return value == null ? null : value.truncatedTo(java.time.temporal.ChronoUnit.SECONDS);
	}
}
