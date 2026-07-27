package com.xiaofei.equity.portfolio;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public final class InvestmentContextContracts {

	private InvestmentContextContracts() {
	}

	public enum InvestmentApproach {
		DEFENSIVE, ENTERPRISING, SPECULATIVE_LIMITED
	}

	public enum InvestmentHorizon {
		SHORT_TERM, MEDIUM_TERM, LONG_TERM
	}

	public enum RiskTolerance {
		CONSERVATIVE, MODERATE, AGGRESSIVE
	}

	public enum SectorPreferenceValue {
		PREFER, NEUTRAL, AVOID, EXCLUDE
	}

	public record CreateInvestmentProfileRequest(
			@NotNull InvestmentApproach investmentApproach,
			@NotNull InvestmentHorizon primaryHorizon,
			@NotNull RiskTolerance riskTolerance,
			String liquidityNeeds,
			String notes,
			@NotNull Instant effectiveAt,
			@NotNull List<@Valid GoalInput> goals,
			@NotNull List<@Valid SectorPreferenceInput> sectorPreferences) {
	}

	public record GoalInput(
			@NotBlank @Size(max = 64) String goalType,
			@Min(1) int priority,
			LocalDate targetDate,
			@DecimalMin("0") BigDecimal targetAmount,
			@Pattern(regexp = "[A-Z]{3}") String currency,
			String description) {
	}

	public record SectorPreferenceInput(
			@NotBlank @Size(max = 64) String taxonomyCode,
			@NotBlank @Size(max = 64) String taxonomyVersion,
			@NotBlank @Size(max = 128) String sectorCode,
			@NotNull SectorPreferenceValue preference) {
	}

	public record InvestmentProfileResponse(
			UUID id,
			int versionNumber,
			InvestmentApproach investmentApproach,
			InvestmentHorizon primaryHorizon,
			RiskTolerance riskTolerance,
			String liquidityNeeds,
			String notes,
			Instant effectiveAt,
			Instant recordedAt,
			List<GoalInput> goals,
			List<SectorPreferenceInput> sectorPreferences) {
	}

	public enum LiabilityType {
		MARGIN, LOAN, OTHER
	}

	public record CreateLiabilityRequest(
			UUID accountId,
			@NotBlank @Size(max = 160) String name,
			@NotNull LiabilityType liabilityType,
			@NotBlank @Pattern(regexp = "[A-Z]{3}") String currency) {
	}

	public record LiabilityResponse(
			UUID id,
			UUID accountId,
			String name,
			LiabilityType liabilityType,
			String currency,
			String status,
			Instant createdAt) {
	}

	public record CreateLiabilityBalanceRequest(
			@NotNull Instant asOfTime,
			@NotNull @DecimalMin("0") BigDecimal balance,
			@DecimalMin("0") BigDecimal annualInterestRate,
			@NotNull PortfolioContracts.SnapshotSource sourceType) {
	}

	public record LiabilityBalanceAccepted(
			UUID id,
			UUID liabilityId,
			Instant asOfTime,
			BigDecimal balance,
			BigDecimal annualInterestRate,
			Instant recordedAt) {
	}

	public enum ConstraintScope {
		USER, PORTFOLIO, ACCOUNT
	}

	public record CreateConstraintPolicyRequest(
			@NotNull ConstraintScope scopeType,
			UUID portfolioId,
			UUID accountId,
			@Min(1) Integer maximumPositionCount,
			@DecimalMin("0") @DecimalMax("1") BigDecimal maximumPositionWeight,
			@DecimalMin("0") @DecimalMax("1") BigDecimal maximumSectorWeight,
			@DecimalMin("0") @DecimalMax("1") BigDecimal minimumCashWeight,
			@DecimalMin("0") BigDecimal maximumLeverageRatio,
			@DecimalMin("0") @DecimalMax("1") BigDecimal maximumSpeculativeWeight,
			@NotNull Instant effectiveAt,
			@NotNull List<@Valid SectorConstraintInput> sectorConstraints) {
	}

	public record SectorConstraintInput(
			@NotBlank @Size(max = 64) String taxonomyCode,
			@NotBlank @Size(max = 64) String taxonomyVersion,
			@NotBlank @Size(max = 128) String sectorCode,
			@DecimalMin("0") @DecimalMax("1") BigDecimal maximumWeight,
			boolean excluded) {
	}

	public record ConstraintPolicyResponse(
			UUID id,
			ConstraintScope scopeType,
			UUID portfolioId,
			UUID accountId,
			int versionNumber,
			ConstraintValues values,
			Instant effectiveAt,
			Instant recordedAt,
			List<SectorConstraintInput> sectorConstraints) {
	}

	public record ConstraintValues(
			Integer maximumPositionCount,
			BigDecimal maximumPositionWeight,
			BigDecimal maximumSectorWeight,
			BigDecimal minimumCashWeight,
			BigDecimal maximumLeverageRatio,
			BigDecimal maximumSpeculativeWeight) {
	}

	public record ResolvedPortfolioConstraints(
			UUID portfolioId,
			ConstraintValues portfolioValues,
			List<ResolvedAccountConstraints> accounts) {
	}

	public record ResolvedAccountConstraints(
			UUID accountId,
			ConstraintValues values) {
	}
}
