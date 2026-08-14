package com.xiaofei.equity.portfolio;

import java.util.List;
import java.util.UUID;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import tools.jackson.databind.JsonNode;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

public final class UnifiedPortfolioContracts {

	public static final String INPUT_VERSION = "unified-portfolio-risk-input-v1.0.0";
	public static final String RESULT_VERSION = "unified-portfolio-risk-result-v1.0.0";

	private UnifiedPortfolioContracts() {
	}

	public record CreateContextRequest(
			@NotEmpty List<@NotNull UUID> accountSnapshotIds,
			@NotNull UUID constraintPolicyVersionId,
			@NotNull @Valid RiskInput riskInput) {
	}
	public record CurrentEvidenceReference(@NotNull UUID securityId,
			@NotNull UUID selectionRequestId,@NotNull SleeveType sleeve,UUID modelReferenceId) {}
	@JsonIgnoreProperties(ignoreUnknown=false)
	public record CreateCurrentEvidenceContextRequest(
			@NotEmpty List<@NotNull UUID> accountSnapshotIds,
			@NotNull UUID constraintPolicyVersionId,
			@NotEmpty List<@Valid CurrentEvidenceReference> evidenceReferences) {
		public CreateCurrentEvidenceContextRequest {
			accountSnapshotIds=accountSnapshotIds==null?null:List.copyOf(accountSnapshotIds);
			evidenceReferences=evidenceReferences==null?null:List.copyOf(evidenceReferences);
		}
	}
	public record CurrentEvidenceContextResponse(ContextResponse context,UUID evidenceManifestId,String evidenceManifestHash) {}

	public record RiskInput(
			@NotBlank @Pattern(regexp = "unified-portfolio-risk-input-v1\\.0\\.0") String contractVersion,
			@NotBlank @Pattern(regexp = "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z") String asOfTime,
			@NotBlank @Pattern(regexp = "USD") String baseCurrency,
			@NotBlank @Pattern(regexp = "-?(0|[1-9][0-9]*)(\\.[0-9]+)?") String cashValue,
			@NotBlank @Pattern(regexp = "-?(0|[1-9][0-9]*)(\\.[0-9]+)?") String liabilityValue,
			@NotNull List<@Valid PositionInput> positions,
			@NotEmpty @Size(min = 2, max = 2) List<@Valid SleeveEvidenceInput> sleeveEvidence,
			@NotNull @Valid ConstraintInput constraints) {
	}

	public record PositionInput(
			@NotNull UUID securityId,
			@NotBlank @Size(max = 32) String ticker,
			@NotNull SleeveType sleeve,
			@NotBlank @Size(max = 128) String sectorCode,
			@Pattern(regexp = "-?(0|[1-9][0-9]*)(\\.[0-9]+)?") String marketValue,
			@NotNull DataState dataState) {
	}

	public record SleeveEvidenceInput(
			@NotNull SleeveType sleeve,
			@NotBlank @Size(max = 96) String modelVersion,
			@NotNull ModelEvidenceLabel evidenceLabel,
			@NotNull Boolean researchUseAllowed,
			@NotBlank @Size(max = 255) String referenceId,
			@NotBlank @Pattern(regexp = "sha256:[0-9a-f]{64}") String referenceHash) {
	}

	public record ConstraintInput(
			@NotBlank @Pattern(regexp = "(0|1|0\\.[0-9]+|1\\.0+)") String maximumPositionWeight,
			@NotBlank @Pattern(regexp = "(0|1|0\\.[0-9]+|1\\.0+)") String maximumSectorWeight,
			@NotBlank @Pattern(regexp = "(0|1|0\\.[0-9]+|1\\.0+)") String minimumCashWeight,
			@NotBlank @Pattern(regexp = "(0|[1-9][0-9]*)(\\.[0-9]+)?") String maximumLeverageRatio) {
	}

	public enum SleeveType { LONG_TERM_CORE, QUANT_TRADING, UNASSIGNED }
	public enum DataState { VALID, MISSING, STALE, INVALID }
	public enum ModelEvidenceLabel {
		NOT_VALIDATED, DEVELOPMENT_OBSERVED, BACKTEST_SUPPORTED, PIT_SUPPORTED, FORWARD_SUPPORTED
	}

	public enum ReviewConclusion { ACKNOWLEDGED, REVIEW_REQUIRED, NO_ACTION }

	public record ReviewRequest(
			@NotNull ReviewConclusion conclusion,
			@NotBlank @Size(max = 4000) String rationale) {
	}

	public record ReviewResponse(
			UUID reviewId,
			UUID contextId,
			ReviewConclusion conclusion,
			String rationale,
			String contentHash,
			String reviewedAt,
			String recordedAt) {
	}

	public record ContextResponse(
			UUID contextId,
			UUID portfolioId,
			JsonNode riskContext,
			ReviewSummary review,
			String recordedAt) {
	}

	public record ReviewSummary(
			UUID reviewId,
			ReviewConclusion conclusion,
			String rationale,
			String contentHash,
			String reviewedAt) {
	}
}
