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
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public final class PortfolioContracts {

	private PortfolioContracts() {
	}

	public record CreateAccountRequest(
			@NotBlank @Size(max = 160) String name,
			@NotNull AccountType accountType,
			@NotBlank @Pattern(regexp = "[A-Z]{3}") String baseCurrency) {
	}

	public enum AccountType {
		REAL, SIMULATED, RETIREMENT
	}

	public record AccountResponse(
			UUID id,
			String name,
			AccountType accountType,
			String baseCurrency,
			String status,
			Instant createdAt) {
	}

	public record CreateSnapshotRequest(
			@NotNull Instant asOfTime,
			@NotNull SnapshotSource sourceType,
			@Size(max = 255) String sourceReference,
			@NotNull SnapshotCompleteness completeness,
			@NotNull List<@Valid CashBalanceInput> cashBalances,
			@NotNull List<@Valid PositionInput> positions) {
	}

	public enum SnapshotSource {
		MANUAL, FILE_IMPORT, SYSTEM
	}

	public enum SnapshotCompleteness {
		COMPLETE, PARTIAL
	}

	public record CashBalanceInput(
			@NotBlank @Pattern(regexp = "[A-Z]{3}") String currency,
			@NotNull BigDecimal settledAmount,
			@NotNull BigDecimal unsettledAmount,
			@NotNull @DecimalMin("0") BigDecimal restrictedAmount) {
	}

	public record PositionInput(
			@NotNull UUID securityPublicId,
			@NotNull BigDecimal quantity,
			@NotNull @DecimalMin("0") BigDecimal averageCost,
			@NotBlank @Pattern(regexp = "[A-Z]{3}") String costCurrency) {
	}

	public record SnapshotAccepted(
			UUID snapshotId,
			UUID accountId,
			Instant asOfTime,
			SnapshotCompleteness completeness,
			String contentHash,
			Instant recordedAt) {
	}

	public record CreatePortfolioRequest(
			@NotBlank @Size(max = 160) String name,
			@NotBlank @Pattern(regexp = "USD") String baseCurrency) {
	}

	public record PortfolioResponse(
			UUID id,
			String name,
			String baseCurrency,
			String status,
			List<UUID> accountIds,
			Instant createdAt) {
	}

	public record ReplacePortfolioAccountsRequest(
			@NotEmpty List<@NotNull UUID> accountIds) {
	}

	public record ReplacePortfolioLiabilitiesRequest(
			@NotNull List<@NotNull UUID> liabilityIds) {
	}

	public record PortfolioLiabilityMembershipResponse(
			UUID portfolioId,
			List<UUID> liabilityIds) {
	}

	public record CreateScenarioRequest(
			@NotNull ScenarioType scenarioType,
			@NotNull @DecimalMin("0") BigDecimal newMoneyAmount) {
	}

	public enum ScenarioType {
		NEW_MONEY, CONSTRAINED_REBALANCING, TARGET_PORTFOLIO
	}

	public record ScenarioAccepted(
			UUID scenarioId,
			UUID portfolioId,
			ScenarioType scenarioType,
			String status,
			BigDecimal newMoneyAmount,
			int frozenAccountSnapshotCount,
			Instant createdAt) {
	}
}
