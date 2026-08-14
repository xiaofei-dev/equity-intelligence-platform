package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.PortfolioDecisionContracts.*;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;
import com.xiaofei.equity.usercontext.CurrentUser;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest({PortfolioDecisionController.class, UnifiedPortfolioContextExceptionHandler.class})
class PortfolioDecisionControllerTests {
	private static final UUID USER = UUID.fromString("00000000-0000-4000-8000-000000000001");
	private static final UUID IDENTITY = UUID.fromString("00000000-0000-4000-8000-000000000002");
	private static final UUID PORTFOLIO = UUID.fromString("00000000-0000-4000-8000-000000000003");
	private static final UUID SCENARIO = UUID.fromString("00000000-0000-4000-8000-000000000004");
	private static final UUID CONTEXT = UUID.fromString("00000000-0000-4000-8000-000000000005");
	private static final UUID RECOMMENDATION = UUID.fromString("00000000-0000-4000-8000-000000000006");

	@Autowired MockMvc mvc;
	@MockitoBean ClosedTestIdentityResolver identities;
	@MockitoBean PortfolioDecisionService service;

	@Test
	void portfolioDecisionConflictUsesTheStablePortfolioErrorContract() throws Exception {
		CurrentUser user = new CurrentUser(USER, IDENTITY, "tester-one");
		when(identities.resolve("tester-one")).thenReturn(user);
		when(service.latestComparison(user,PORTFOLIO)).thenThrow(new PortfolioContextException(
				"PORTFOLIO_DECISION_CONFLICT","The portfolio decision conflicts with immutable state.",409));

		mvc.perform(get("/api/v1/me/portfolios/{portfolio}/decision-scenarios/comparison/latest",PORTFOLIO)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER,"tester-one"))
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.code").value("PORTFOLIO_DECISION_CONFLICT"))
			.andExpect(jsonPath("$.message").value("The portfolio decision conflicts with immutable state."))
			.andExpect(jsonPath("$.timestamp").exists());
	}

	@Test
	void collectionReturnsTheCompleteLatestScenarioProjection() throws Exception {
		CurrentUser user = new CurrentUser(USER, IDENTITY, "tester-one");
		when(identities.resolve("tester-one")).thenReturn(user);
		when(service.list(user, PORTFOLIO)).thenReturn(List.of(scenario()));
		mvc.perform(get("/api/v1/me/portfolios/{portfolio}/decision-scenarios", PORTFOLIO)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$[0].candidateState").value("CANDIDATE_FOR_HUMAN_REVIEW"))
			.andExpect(jsonPath("$[0].recommendation.recommendationId").value(RECOMMENDATION.toString()))
			.andExpect(jsonPath("$[0].decisionCutoff").value("2026-08-13T00:00:00Z"))
			.andExpect(jsonPath("$[0].authority.finalWeightAuthority").value(false))
			.andExpect(jsonPath("$[0].positions").isArray());
	}

	@Test
	void evaluationProjectionIncludesMaturitiesAndPerformanceSummaries() throws Exception {
		CurrentUser user = new CurrentUser(USER, IDENTITY, "tester-one");
		when(identities.resolve("tester-one")).thenReturn(user);
		UUID evaluation=UUID.fromString("00000000-0000-4000-8000-000000000008");
		UUID decision=UUID.fromString("00000000-0000-4000-8000-000000000007");
		when(service.latestEvaluation(user,PORTFOLIO,SCENARIO)).thenReturn(new EvaluationResponse(
				evaluation,PORTFOLIO,decision,CONTEXT,SCENARIO,SCENARIO,"PARTIALLY_MATURED","SPY",true,
				List.of(new EvaluationMaturity(20,"AVAILABLE",null,Instant.parse("2026-09-01T00:00:00Z"))),
				List.of(new EvaluationPeriodSummary(20,"2026-08-14","2026-09-01",20,19,"0.02","0.01",
						"0.005","0.005","0.008","0.002","-0.03","0.04","12.5","0.95")),
				Instant.parse("2026-08-13T00:00:01Z")));
		mvc.perform(get("/api/v1/me/portfolios/{portfolio}/decision-scenarios/{scenario}/evaluations/latest",
				PORTFOLIO,SCENARIO).header(ClosedTestIdentityResolver.IDENTITY_HEADER,"tester-one"))
			.andExpect(status().isOk()).andExpect(jsonPath("$.benchmarkCode").value("SPY"))
			.andExpect(jsonPath("$.acceptedScenarioId").value(SCENARIO.toString()))
			.andExpect(jsonPath("$.maturities[0].state").value("AVAILABLE"))
			.andExpect(jsonPath("$.summaries[0].netReturn").value("0.01"))
			.andExpect(jsonPath("$.summaries[0].holdCurrentReturn").value("0.008"))
			.andExpect(jsonPath("$.summaries[0].acceptedExcessVsHoldCurrent").value("0.002"))
			.andExpect(jsonPath("$.summaries[0].coverageRate").value("0.95"));
	}

	@Test
	void humanDecisionTimeIsServerOwnedEvenWhenLegacyClientTimeIsPresent() throws Exception {
		CurrentUser user = new CurrentUser(USER, IDENTITY, "tester-one");
		when(identities.resolve("tester-one")).thenReturn(user);
		UUID decision=UUID.fromString("00000000-0000-4000-8000-000000000007");
		Instant serverTime=Instant.parse("2026-08-13T00:00:01.987654Z");
		when(service.decide(org.mockito.ArgumentMatchers.eq(user),org.mockito.ArgumentMatchers.eq(PORTFOLIO),
				org.mockito.ArgumentMatchers.eq(SCENARIO),org.mockito.ArgumentMatchers.eq("decision-1"),
				org.mockito.ArgumentMatchers.any())).thenReturn(new HumanDecisionResponse(decision,SCENARIO,
				RECOMMENDATION,Conclusion.ACCEPTED,"Human review complete.",null,serverTime,serverTime));
		mvc.perform(post("/api/v1/me/portfolios/{portfolio}/decision-scenarios/{scenario}/decisions",
				PORTFOLIO, SCENARIO).header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "decision-1").contentType(MediaType.APPLICATION_JSON)
				.content("""
						{"conclusion":"ACCEPTED","rationale":"Human review complete.",
						 "supersedesDecisionId":null,"decidedAt":"2026-08-13T00:00:00Z"}
						"""))
			.andExpect(status().isCreated())
			.andExpect(jsonPath("$.decidedAt").value("2026-08-13T00:00:01Z"));
	}

	@Test
	void v32ComparisonAndLongitudinalProjectionRemainSpringOwnedAndWholeSecond() throws Exception {
		CurrentUser user = new CurrentUser(USER, IDENTITY, "tester-one");
		when(identities.resolve("tester-one")).thenReturn(user);
		UUID comparison=UUID.fromString("00000000-0000-4000-8000-000000000020");
		when(service.latestComparison(user,PORTFOLIO)).thenReturn(new ScenarioComparisonResponse(
				comparison,PORTFOLIO,CONTEXT,4,List.of(
				item(ScenarioType.CONSTRAINED_REBALANCE,SCENARIO,"1"),
				item(ScenarioType.HOLD_CURRENT,UUID.fromString("00000000-0000-4000-8000-000000000021"),"2"),
				item(ScenarioType.NEW_MONEY_ONLY,UUID.fromString("00000000-0000-4000-8000-000000000022"),"3"),
				item(ScenarioType.TARGET_PORTFOLIO,UUID.fromString("00000000-0000-4000-8000-000000000023"),"4")),
				null,"AWAITING_RECOMMENDATION","sha256:"+"a".repeat(64),
				Instant.parse("2026-08-13T00:00:01.987654Z")));
		mvc.perform(get("/api/v1/me/portfolios/{portfolio}/decision-scenarios/comparison/latest",PORTFOLIO)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER,"tester-one"))
			.andExpect(status().isOk()).andExpect(jsonPath("$.expectedScenarioCount").value(4))
			.andExpect(jsonPath("$.scenarios.length()").value(4))
			.andExpect(jsonPath("$.sealedAt").value("2026-08-13T00:00:01Z"));
	}

	@Test
	void scenarioCreationRequiresBothExplicitHumanSleeveBudgets() throws Exception {
		CurrentUser user = new CurrentUser(USER, IDENTITY, "tester-one");
		when(identities.resolve("tester-one")).thenReturn(user);
		mvc.perform(post("/api/v1/me/portfolios/{portfolio}/decision-scenarios", PORTFOLIO)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "scenario-1").contentType(MediaType.APPLICATION_JSON)
				.content("""
						{"contextId":"00000000-0000-4000-8000-000000000005",
						 "evidenceManifestId":"00000000-0000-4000-8000-000000000009",
						 "constraintPolicyVersionId":"00000000-0000-4000-8000-000000000010",
						 "selectedScenarioType":"TARGET_PORTFOLIO",
						 "scenarioType":"HOLD_CURRENT","newMoneyAmount":0,
						 "candidates":[{"securityId":"00000000-0000-4000-8000-000000000011",
						  "permission":"LOCKED","humanApprovedCandidate":false,"targetMarketValue":null}]}
						"""))
			.andExpect(status().isBadRequest());
	}

	@Test
	void exactFourComparisonCreationUsesOneTransactionalPublicCommand() throws Exception {
		CurrentUser user = new CurrentUser(USER, IDENTITY, "tester-one");
		when(identities.resolve("tester-one")).thenReturn(user);
		UUID comparison=UUID.fromString("00000000-0000-4000-8000-000000000020");
		when(service.createComparison(org.mockito.ArgumentMatchers.eq(user),
				org.mockito.ArgumentMatchers.eq(PORTFOLIO),org.mockito.ArgumentMatchers.eq("comparison-1"),
				org.mockito.ArgumentMatchers.any())).thenReturn(new ScenarioComparisonResponse(
				comparison,PORTFOLIO,CONTEXT,4,List.of(),null,"AWAITING_RECOMMENDATION",
				"sha256:"+"a".repeat(64),Instant.parse("2026-08-13T00:00:01Z")));
		mvc.perform(post("/api/v1/me/portfolios/{portfolio}/decision-scenarios/comparisons",PORTFOLIO)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER,"tester-one")
				.header("Idempotency-Key","comparison-1").contentType(MediaType.APPLICATION_JSON)
				.content("""
						{"contextId":"00000000-0000-4000-8000-000000000005",
						 "evidenceManifestId":"00000000-0000-4000-8000-000000000009",
						 "constraintPolicyVersionId":"00000000-0000-4000-8000-000000000010",
						 "newMoneyAmount":1000,
						 "sleeveBudgets":[{"sleeve":"LONG_TERM_CORE","maximumWeight":1},
						  {"sleeve":"QUANT_TRADING","maximumWeight":0.2}],
						 "candidates":[{"securityId":"00000000-0000-4000-8000-000000000011",
						  "permission":"BUY_AND_SELL","humanApprovedCandidate":true,"targetMarketValue":81000}]}
						"""))
				.andExpect(status().isCreated())
				.andExpect(jsonPath("$.comparisonId").value(comparison.toString()))
				.andExpect(jsonPath("$.expectedScenarioCount").value(4));
	}

	@Test
	void humanSelectsRecommendationOnlyAfterReadingTheExactFourComparison() throws Exception {
		CurrentUser user=new CurrentUser(USER,IDENTITY,"tester-one");when(identities.resolve("tester-one")).thenReturn(user);
		UUID comparison=UUID.fromString("00000000-0000-4000-8000-000000000020");
		when(service.selectComparison(org.mockito.ArgumentMatchers.eq(user),org.mockito.ArgumentMatchers.eq(PORTFOLIO),
				org.mockito.ArgumentMatchers.eq(comparison),org.mockito.ArgumentMatchers.eq("select-1"),
				org.mockito.ArgumentMatchers.any())).thenReturn(new ScenarioComparisonResponse(comparison,PORTFOLIO,CONTEXT,4,
				List.of(),SCENARIO,"RECOMMENDATION_BOUND","sha256:"+"a".repeat(64),Instant.parse("2026-08-13T00:00:01Z")));
		mvc.perform(post("/api/v1/me/portfolios/{portfolio}/decision-scenarios/comparisons/{comparison}/selection",PORTFOLIO,comparison)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER,"tester-one").header("Idempotency-Key","select-1")
				.contentType(MediaType.APPLICATION_JSON).content("{\"selectedScenarioType\":\"TARGET_PORTFOLIO\"}"))
				.andExpect(status().isOk()).andExpect(jsonPath("$.selectedScenarioId").value(SCENARIO.toString()));
	}

	@Test
	void ownerCanSealLongitudinalProjectionAndRecordThesisReview() throws Exception {
		CurrentUser user=new CurrentUser(USER,IDENTITY,"tester-one");
		when(identities.resolve("tester-one")).thenReturn(user);
		UUID evaluation=UUID.fromString("00000000-0000-4000-8000-000000000008");
		when(service.getEvaluation(user,PORTFOLIO,SCENARIO,evaluation)).thenReturn(org.mockito.Mockito.mock(EvaluationResponse.class));
		var projection=new LongitudinalProjectionResponse(evaluation,PORTFOLIO,List.of(),List.of());
		when(service.sealLongitudinalByHorizon(org.mockito.ArgumentMatchers.eq(user),
				org.mockito.ArgumentMatchers.eq(PORTFOLIO),org.mockito.ArgumentMatchers.eq(evaluation),
				org.mockito.ArgumentMatchers.eq("seal-20"),org.mockito.ArgumentMatchers.any())).thenReturn(projection);
		when(service.reviewThesis(org.mockito.ArgumentMatchers.eq(user),org.mockito.ArgumentMatchers.eq(PORTFOLIO),
				org.mockito.ArgumentMatchers.eq(evaluation),org.mockito.ArgumentMatchers.eq("review-20"),
				org.mockito.ArgumentMatchers.any())).thenReturn(projection);
		mvc.perform(post("/api/v1/me/portfolios/{portfolio}/decision-scenarios/{scenario}/evaluations/{evaluation}/longitudinal/seal",
				PORTFOLIO,SCENARIO,evaluation).header(ClosedTestIdentityResolver.IDENTITY_HEADER,"tester-one")
				.header("Idempotency-Key","seal-20").contentType(MediaType.APPLICATION_JSON)
				.content("{\"horizonSessions\":20}"))
				.andExpect(status().isOk()).andExpect(jsonPath("$.evaluationId").value(evaluation.toString()));
		mvc.perform(post("/api/v1/me/portfolios/{portfolio}/decision-scenarios/{scenario}/evaluations/{evaluation}/thesis-reviews",
				PORTFOLIO,SCENARIO,evaluation).header(ClosedTestIdentityResolver.IDENTITY_HEADER,"tester-one")
				.header("Idempotency-Key","review-20").contentType(MediaType.APPLICATION_JSON)
				.content("{\"horizonSessions\":20,\"state\":\"INSUFFICIENT_EVIDENCE\",\"rationale\":\"More evidence is required.\",\"supersedesReviewId\":null}"))
				.andExpect(status().isOk()).andExpect(jsonPath("$.evaluationId").value(evaluation.toString()));
	}

	private static ScenarioResponse scenario() {
		return new ScenarioResponse(SCENARIO, PORTFOLIO, CONTEXT, ScenarioType.HOLD_CURRENT,
				"VALID", Instant.parse("2026-08-13T00:00:00.987654Z"),
				"PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0", "CANDIDATE_FOR_HUMAN_REVIEW",
				List.of(), List.of(), new DecisionEconomics("0", "2", "3", "0", "0", "0", "0",
						"NOT_ESTIMATED", "NOT_ESTIMATED", null, "0", "0", "0", "100000", "100000"),
				List.of(), new RecommendationSummary(RECOMMENDATION, "RECOMMENDATION_AVAILABLE",
						List.of(), "sha256:" + "1".repeat(64)), null,
				new DecisionAuthority(true, false, false, false, false, true), "sha256:" + "2".repeat(64));
	}
	private static ScenarioComparisonItem item(ScenarioType type,UUID id,String digit) {
		String contentHash="sha256:"+digit.repeat(64);
		return new ScenarioComparisonItem(type,id,contentHash,new ScenarioProjection(id,type,"VALID",
				"CANDIDATE_FOR_HUMAN_REVIEW",List.of(),new DecisionEconomics("0","2","3","0","0","0","0",
				"NOT_ESTIMATED","NOT_ESTIMATED",null,"0","0","0","100000","100000"),List.of(),contentHash));
	}
}
