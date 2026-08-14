package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.PortfolioDecisionContracts.*;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.Test;

import com.xiaofei.equity.portfolio.UnifiedPortfolioContracts.SleeveType;

class PortfolioDecisionProjectionTests {
	@Test
	void exactFourOrchestrationForcesHoldNewMoneyToZeroOnly() {
		var candidate=new CandidateInput(UUID.fromString("00000000-0000-4000-8000-000000000001"),
				Permission.BUY_AND_SELL,true,new BigDecimal("12500"));
		var request=new CreateScenarioComparisonRequest(
				UUID.fromString("00000000-0000-4000-8000-000000000002"),
				UUID.fromString("00000000-0000-4000-8000-000000000003"),
				UUID.fromString("00000000-0000-4000-8000-000000000004"),
				new BigDecimal("10000"),List.of(
						new SleeveBudgetInput(SleeveType.LONG_TERM_CORE,new BigDecimal("0.8")),
						new SleeveBudgetInput(SleeveType.QUANT_TRADING,new BigDecimal("0.2"))),List.of(candidate));

		for(ScenarioType type:ScenarioType.values()) {
			CreateScenarioRequest generated=PortfolioDecisionService.comparisonScenarioRequest(request,type);
			assertEquals(type,generated.scenarioType());
			assertEquals(type==ScenarioType.HOLD_CURRENT?BigDecimal.ZERO:new BigDecimal("10000"),
					generated.newMoneyAmount());
			if(type==ScenarioType.HOLD_CURRENT||type==ScenarioType.NEW_MONEY_ONLY)
				assertNull(generated.candidates().getFirst().targetMarketValue());
			else assertEquals(new BigDecimal("12500"),generated.candidates().getFirst().targetMarketValue());
		}
	}

	@Test
	void projectionQueryUsesOnlyPersistedV29ScenarioEconomics() {
		String query=PortfolioDecisionService.SCENARIO_PROJECTION_QUERY;
		assertTrue(query.contains("new_money_amount"));
		assertTrue(query.contains("gross_traded_notional"));
		assertTrue(query.contains("sum(position.current_value)"));
		for(String derivedColumn:List.of("candidate_state","gross_buy_notional","gross_sell_notional",
				"estimated_transaction_and_slippage_cost","impact_state","tax_estimate_amount",
				"applied_tax_amount","one_way_weight_turnover","gross_traded_notional_rate"))
			assertFalse(query.contains(derivedColumn),derivedColumn+" must be derived from sealed V29 rows");
	}

	@Test
	void derivesCompleteEconomicsAndRoundsNonterminatingGrossTradedRate() {
		var position=new DecisionPosition(UUID.fromString("00000000-0000-4000-8000-000000000001"),
				"AAPL","LONG_TERM_CORE","8","9","1","0.9","BUY_ONLY","0.0005","0.25");
		DecisionEconomics economics=PortfolioDecisionService.scenarioProjectionEconomics("VALID",
				BigDecimal.ZERO,BigDecimal.valueOf(2),BigDecimal.valueOf(3),"AVAILABLE_APPLIED",
				BigDecimal.ONE,BigDecimal.ZERO,new BigDecimal("9.9995"),BigDecimal.ONE,
				new BigDecimal("0.0005"),new BigDecimal("0.1"),BigDecimal.valueOf(8),List.of(position));

		assertEquals("1",economics.grossBuyNotional());
		assertEquals("0",economics.grossSellNotional());
		assertEquals("1",economics.grossTradedNotional());
		assertEquals("0.0005",economics.estimatedTransactionAndSlippageCost());
		assertEquals("NOT_ESTIMATED",economics.impactState());
		assertEquals("0.25",economics.taxEstimateAmount());
		assertEquals("0.25",economics.appliedTaxAmount());
		assertEquals("0.1111111111111111111111111111111111",economics.grossTradedNotionalRate());
		assertEquals("9.9995",economics.finalAssetValue());
	}

	@Test
	void derivesCandidateStateAndOmitsEconomicsForInfeasibleScenario() {
		assertEquals("CANDIDATE_FOR_HUMAN_REVIEW",PortfolioDecisionService.candidateState("PARTIAL"));
		assertEquals("NO_FEASIBLE_CANDIDATE",PortfolioDecisionService.candidateState("INFEASIBLE"));
		assertNull(PortfolioDecisionService.scenarioProjectionEconomics("INFEASIBLE",BigDecimal.ZERO,
				BigDecimal.valueOf(2),BigDecimal.valueOf(3),"NOT_ESTIMATED",BigDecimal.ZERO,
				null,null,null,null,null,BigDecimal.ZERO,List.of()));
	}
}
