package com.xiaofei.equity.quanttrading;

import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

public final class QuantResearchContract {

	public static final String CONTRACT_VERSION = "quant-trading-research-decision-v1.1.0";
	public static final String PROJECTION_VERSION = "quant-trading-public-projection-v1.1.0";
	public static final String ASSEMBLY_VERSION = "quant-trading-v22-assembly-v1.1.0";
	public static final String MODEL_VERSION = "QUANT-TRADING-v1.1.0";
	public static final String STRATEGY_VERSION = "DUAL-MOMENTUM-TREND-v1.1.0";
	public static final String FORMULA_VERSION = "DUAL-MOMENTUM-TREND-FORMULAS-v1.1.0";
	public static final String ENTRY_EXIT_POLICY_VERSION =
			"DUAL-MOMENTUM-TREND-ENTRY-EXIT-v1.1.0";

	private QuantResearchContract() {
	}

	public record Features(
			String atr14,
			String sma100,
			String sma200,
			String marketSma200,
			String momentum252Skip20,
			String momentum126Skip20,
			String marketMomentum252Skip20,
			String marketMomentum126Skip20,
			String relative252Skip20,
			String relative126Skip20,
			String medianAdtv20,
			String atrPercent) {
	}

	public record RawSignal(
			String state,
			List<String> reasonCodes,
			String inputHash,
			String contentHash,
			String signalClose,
			Features features) {
	}

	public record Ranking(
			String state,
			Integer rank,
			int crossSectionCount,
			String momentum252Percentile,
			String momentum126Percentile,
			String compositeScore,
			String crossSectionHash,
			String contentHash) {
	}

	public record EntryPlan(
			String signalClose,
			String initialStop,
			String maximumEntryPrice,
			String atr14,
			int maximumHoldingSessions) {
	}

	public record ResearchSignal(
			UUID securityId,
			String assemblyState,
			String applicability,
			List<String> assemblyReasonCodes,
			RawSignal rawSignal,
			Ranking ranking,
			EntryPlan entryPlan,
			String researchClassification) {
	}

	public record Authority(
			boolean deterministicResearchSignal,
			boolean deterministicFinalPortfolioWeight,
			boolean automaticBrokerageExecution,
			boolean llmSignalOrWeightAuthority,
			boolean futureReturnGuaranteed) {
	}

	public record ResearchDecisionResponse(
			UUID decisionId,
			String contractVersion,
			String projectionVersion,
			String assemblyVersion,
			String modelVersion,
			String strategyVersion,
			String formulaVersion,
			String entryExitPolicyVersion,
			String modelEvidenceLabel,
			LocalDate decisionDate,
			int rebalanceOrdinal,
			int expectedSecurityCount,
			String assemblyManifestHash,
			List<ResearchSignal> signals,
			Authority authority,
			String contentHash) {
	}
}
