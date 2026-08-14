package com.xiaofei.equity.fundamentalvalue;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

import tools.jackson.databind.JsonNode;

public final class CurrentFundamentalValueContract {

	public static final String RESULT_VERSION =
			"internal-current-fundamental-value-result-v1.0.0";

	private CurrentFundamentalValueContract() {
	}

	public record Identity(
			UUID securityId, UUID companyId, UUID instrumentId, UUID shareClassId,
			UUID listingId, UUID tickerAssignmentId, String ticker, String mic,
			String currency) {
	}

	record InternalAssessment(
			String contractVersion, UUID assessmentId, String assessmentContentHash,
			Identity identity, Instant decisionCutoff, LocalDate priceSessionDate,
			LocalDate latestFundamentalPeriodEnd, String evidenceTrack,
			String claimCeiling, String modelEvidenceLabel, JsonNode versions,
			JsonNode referencePrice, JsonNode companyQuality,
			JsonNode financialResilience, JsonNode earningsAndCashFlowQuality,
			JsonNode capitalAllocationQuality, JsonNode downsideRisk,
			JsonNode valuations, JsonNode fairValue, JsonNode marginOfSafety,
			JsonNode expectedReturn, JsonNode riskCap, JsonNode investmentView,
			boolean deterministicActionAuthorized,
			boolean deterministicRankingAuthorized,
			boolean finalPortfolioWeightAuthorized,
			boolean automaticBrokerageExecutionAuthorized) {
	}

	public record AssessmentResponse(
			String contractVersion, UUID assessmentId, String assessmentContentHash,
			Identity identity, Instant decisionCutoff, LocalDate priceSessionDate,
			LocalDate latestFundamentalPeriodEnd, String evidenceTrack,
			String claimCeiling, String modelEvidenceLabel, JsonNode versions,
			JsonNode referencePrice, JsonNode companyQuality,
			JsonNode financialResilience, JsonNode earningsAndCashFlowQuality,
			JsonNode capitalAllocationQuality, JsonNode downsideRisk,
			JsonNode valuations, JsonNode fairValue, JsonNode marginOfSafety,
			JsonNode expectedReturn, JsonNode riskCap, JsonNode investmentView,
			boolean deterministicActionAuthorized,
			boolean deterministicRankingAuthorized,
			boolean finalPortfolioWeightAuthorized,
			boolean automaticBrokerageExecutionAuthorized) {
	}
}
