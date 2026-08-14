package com.xiaofei.equity.fundamentalvalue;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import tools.jackson.databind.JsonNode;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

public final class FundamentalValueContract {

	public static final String COMMAND_VERSION = "internal-fundamental-value-command-v1.0.0";
	public static final String RESULT_VERSION = "internal-fundamental-value-result-v1.1.0";

	private FundamentalValueContract() {
	}

	public record OperandRequestId(String operandCode, UUID requestId) {
	}

	public record DecisionIdentity(
			UUID securityId,
			UUID companyId,
			UUID instrumentId,
			UUID shareClassId,
			UUID listingId,
			UUID tickerAssignmentId,
			String ticker,
			String mic,
			String currency,
			LocalDate completedSessionDate) {
	}

	@JsonIgnoreProperties(ignoreUnknown = false)
	public record DecisionRequest(
			String contractVersion,
			UUID routingId,
			UUID classificationRequestId,
			List<OperandRequestId> operandRequestIds,
			int projectionYears) {
	}

	record InternalDecision(
			String contractVersion,
			UUID assemblyId,
			UUID assessmentId,
			DecisionIdentity identity,
			String state,
			String applicability,
			String companyType,
			List<String> reasonCodes,
			boolean coreInvocationAuthorized,
			String manifestContentHash,
			String inputSealContentHash,
			Instant decisionCutoff,
			Instant sealedIngestionCutoff,
			String modelEvidenceLabel,
			String claimCeiling,
			String riskCapCeiling,
			JsonNode deterministicAssessment,
			boolean finalPortfolioWeightAuthorized,
			boolean automaticBrokerageExecutionAuthorized) {
	}

	public record DecisionResponse(
			String contractVersion,
			UUID assemblyId,
			UUID assessmentId,
			DecisionIdentity identity,
			String state,
			String applicability,
			String companyType,
			List<String> reasonCodes,
			boolean coreInvocationAuthorized,
			String manifestContentHash,
			String inputSealContentHash,
			Instant decisionCutoff,
			Instant sealedIngestionCutoff,
			String modelEvidenceLabel,
			String claimCeiling,
			String riskCapCeiling,
			JsonNode deterministicAssessment,
			boolean finalPortfolioWeightAuthorized,
			boolean automaticBrokerageExecutionAuthorized) {
	}
}
