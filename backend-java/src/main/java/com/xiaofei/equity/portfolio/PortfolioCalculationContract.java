package com.xiaofei.equity.portfolio;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

public final class PortfolioCalculationContract {

	public static final String VERSION = "portfolio-calculation-v1";

	private PortfolioCalculationContract() {
	}

	public record CalculationRequest(
			String contractVersion,
			UUID scenarioId,
			Instant asOfTime,
			PortfolioContracts.ScenarioType scenarioType,
			String baseCurrency,
			BigDecimal newMoneyAmount,
			UUID investmentProfileVersionId,
			List<AccountInput> accounts,
			List<LiabilityInput> userLiabilities,
			ConstraintInput constraints,
			List<RebalancingPermissionInput> rebalancingPermissions,
			UUID screeningRunId,
			String marketDataSnapshotId) {
	}

	public record AccountInput(
			UUID accountId,
			PortfolioContracts.AccountType accountType,
			List<CashInput> cashBalances,
			List<PositionInput> positions,
			List<LiabilityInput> liabilities) {
	}

	public record CashInput(
			String currency,
			BigDecimal settledAmount,
			BigDecimal unsettledAmount,
			BigDecimal restrictedAmount) {
	}

	public record PositionInput(
			UUID securityId,
			BigDecimal quantity,
			BigDecimal averageCost,
			String costCurrency) {
	}

	public record LiabilityInput(
			UUID liabilityId,
			String currency,
			BigDecimal balance,
			BigDecimal annualInterestRate) {
	}

	public record ConstraintInput(
			Integer maximumPositionCount,
			BigDecimal maximumPositionWeight,
			BigDecimal maximumSectorWeight,
			BigDecimal minimumCashWeight,
			BigDecimal maximumLeverageRatio,
			BigDecimal maximumSpeculativeWeight,
			List<SectorConstraintInput> sectorConstraints) {
	}

	public record SectorConstraintInput(
			String taxonomyCode,
			String taxonomyVersion,
			String sectorCode,
			BigDecimal maximumWeight,
			boolean excluded) {
	}

	public record RebalancingPermissionInput(
			UUID securityId,
			RebalancingPermission permission,
			BigDecimal maximumQuantityChange,
			BigDecimal maximumWeightChange) {
	}

	public enum RebalancingPermission {
		LOCKED, BUY_ONLY, SELL_ONLY, BUY_AND_SELL
	}

	public record CalculationAccepted(
			UUID calculationId,
			UUID scenarioId,
			String status,
			Instant submittedAt) {
	}

	public record CalculationResult(
			UUID calculationId,
			UUID scenarioId,
			String contractVersion,
			String status,
			String valuationStatus,
			String constraintStatus,
			List<TargetPosition> targetPositions,
			List<SimulatedTransaction> simulatedTransactions,
			List<ConstraintViolation> violations,
			String resultHash,
			Instant completedAt) {
	}

	public record TargetPosition(
			UUID accountId,
			UUID securityId,
			BigDecimal targetQuantity,
			BigDecimal targetWeight) {
	}

	public record SimulatedTransaction(
			UUID accountId,
			UUID securityId,
			String action,
			BigDecimal quantity,
			BigDecimal estimatedPrice,
			BigDecimal estimatedCost,
			String currency) {
	}

	public record ConstraintViolation(
			String code,
			String scope,
			UUID resourceId,
			String message) {
	}
}
