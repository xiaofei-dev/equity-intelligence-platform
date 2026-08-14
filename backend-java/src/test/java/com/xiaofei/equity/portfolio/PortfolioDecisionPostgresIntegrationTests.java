package com.xiaofei.equity.portfolio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import com.xiaofei.equity.usercontext.CurrentUser;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import static com.xiaofei.equity.portfolio.PortfolioDecisionContracts.*;

/** Readback smoke test; V31 command arithmetic and adversarial cases live in PostgreSQL acceptance. */
@EnabledIfEnvironmentVariable(named="TEST_DATABASE_URL", matches="jdbc:postgresql:.*")
class PortfolioDecisionPostgresIntegrationTests {
	@Test
	void readsAllFourSealedComparisonProjectionsFromV29Rows() {
		var dataSource=new DriverManagerDataSource(System.getenv("TEST_DATABASE_URL"),"postgres","postgres");
		var service=new PortfolioDecisionService(JdbcClient.create(dataSource),mock(PortfolioDecisionAnalyticsClient.class));
		var user=new CurrentUser(UUID.fromString("28000000-0000-4000-8000-000000000001"),
				UUID.fromString("28000000-0000-4000-8000-000000000002"),"pg-task5");
		var response=service.latestComparison(user,UUID.fromString("28000000-0000-4000-8000-000000000003"));

		assertEquals(4,response.scenarios().size());
		assertEquals(Set.of(ScenarioType.HOLD_CURRENT,ScenarioType.NEW_MONEY_ONLY,
				ScenarioType.CONSTRAINED_REBALANCE,ScenarioType.TARGET_PORTFOLIO),
				response.scenarios().stream().map(ScenarioComparisonItem::scenarioType).collect(java.util.stream.Collectors.toSet()));
		response.scenarios().forEach(item->assertNotNull(item.scenario().economics()));
		var newMoney=response.scenarios().stream().filter(item->item.scenarioType()==ScenarioType.NEW_MONEY_ONLY)
				.findFirst().orElseThrow().scenario().economics();
		assertEquals("10000",newMoney.newMoneyAmount());
		assertEquals("110000",newMoney.finalAssetValue());
		assertEquals("0",newMoney.grossTradedNotionalRate());
	}

	@Test
	void readsTheSealedAcceptedAndHoldEvaluationProjection() {
		var dataSource=new DriverManagerDataSource(System.getenv("TEST_DATABASE_URL"),"postgres","postgres");
		var service=new PortfolioDecisionService(JdbcClient.create(dataSource),mock(PortfolioDecisionAnalyticsClient.class));
		var user=new CurrentUser(UUID.fromString("28000000-0000-4000-8000-000000000001"),
				UUID.fromString("28000000-0000-4000-8000-000000000002"),"pg-task5");
		var response=service.getEvaluation(user,UUID.fromString("28000000-0000-4000-8000-000000000003"),
				UUID.fromString("29000000-0000-4000-8000-000000000012"),
				UUID.fromString("30000000-0000-4000-8000-000000000001"));
		assertEquals("SPY",response.benchmarkCode());
		assertEquals(5,response.maturities().size());
	}

	@Test
	void readsTheNaturalMaturityHistoricalV31Projection() {
		var dataSource=new DriverManagerDataSource(System.getenv("TEST_DATABASE_URL"),"postgres","postgres");
		var jdbc=JdbcClient.create(dataSource);
		var service=new PortfolioDecisionService(jdbc,mock(PortfolioDecisionAnalyticsClient.class));
		var user=new CurrentUser(UUID.fromString("28000000-0000-4000-8000-000000000001"),
				UUID.fromString("28000000-0000-4000-8000-000000000002"),"pg-task5");
		var portfolioId=UUID.fromString("28000000-0000-4000-8000-000000000003");
		var scenarioId=UUID.fromString("32000000-0000-4000-8000-000000000032");
		var evaluationId=UUID.fromString("32000000-0000-4000-8000-000000000035");
		var completed=service.getEvaluation(user,portfolioId,scenarioId,evaluationId);
		assertEquals(0,completed.summaries().size());
		assertEquals(5,completed.maturities().size());
		assertEquals(21,jdbc.sql("SELECT count(*) FROM app.simulated_portfolio_observation_command_v1 WHERE evaluation_id=:id")
				.param("id",evaluationId).query(Integer.class).single());
		assertEquals(42,jdbc.sql("""
				SELECT count(*) FROM app.simulated_portfolio_observation_selector_v1 selector
				JOIN app.simulated_portfolio_observation_command_v1 command ON command.id=selector.command_id
				WHERE command.evaluation_id=:id
				""")
				.param("id",evaluationId).query(Integer.class).single());
		assertEquals(2,jdbc.sql("SELECT count(*) FROM app.simulated_portfolio_opening_cash_v1 WHERE evaluation_id=:id")
				.param("id",evaluationId).query(Integer.class).single());
	}

	@Test
	void writesAndMaturesTheFrozenHistoricalGraphThroughSpring() {
		var dataSource=new DriverManagerDataSource(System.getenv("TEST_DATABASE_URL"),"postgres","postgres");
		var jdbc=JdbcClient.create(dataSource);
		var service=new PortfolioDecisionService(jdbc,mock(PortfolioDecisionAnalyticsClient.class));
		var competingService=new PortfolioDecisionService(JdbcClient.create(dataSource),
				mock(PortfolioDecisionAnalyticsClient.class));
		var tx=new TransactionTemplate(new DataSourceTransactionManager(dataSource));
		var competingTx=new TransactionTemplate(new DataSourceTransactionManager(dataSource));
		var user=new CurrentUser(UUID.fromString("28000000-0000-4000-8000-000000000001"),
				UUID.fromString("28000000-0000-4000-8000-000000000002"),"pg-task5");
		var portfolioId=UUID.fromString("28000000-0000-4000-8000-000000000003");
		var scenarioId=UUID.fromString("32000000-0000-4000-8000-000000000032");
		var contextId=UUID.fromString("32000000-0000-4000-8000-000000000013");
		var holdId=UUID.fromString("32000000-0000-4000-8000-000000000031");
		var historicalDecision=UUID.randomUUID();
		jdbc.sql("""
				INSERT INTO app.portfolio_human_decision_v1
				(id,user_id,portfolio_id,recommendation_id,created_by_identity_id,conclusion,rationale,
				 idempotency_key,request_hash,content_hash,decided_at,recorded_at,supersedes_decision_id)
				VALUES (:id,:user,:portfolio,'32000000-0000-4000-8000-000000000033',
				 '28000000-0000-4000-8000-000000000002','ACCEPTED','Spring historical writer acceptance.',
				 :key,'sha256:'||repeat('d',64),'sha256:'||repeat('e',64),
				 '2025-01-02T22:00:06Z','2025-01-02T22:00:06Z','32000000-0000-4000-8000-000000000034')
				""").params(Map.of("id",historicalDecision,"user",user.userId(),"portfolio",portfolioId,
				"key","spring-v31-history-decision-"+historicalDecision)).update();
		var request=new CreateEvaluationRequest(historicalDecision,contextId,holdId);
		var evaluation=tx.execute(status -> service.createEvaluation(user,portfolioId,scenarioId,
				"spring-v31-history-evaluation",request));
		assertNotNull(evaluation);
		assertEquals(evaluation.evaluationId(),tx.execute(status -> service.createEvaluation(user,
				portfolioId,scenarioId,"spring-v31-history-evaluation",request)).evaluationId());
		var sessions=jdbc.sql("""
				SELECT id FROM analytics.evidence_completed_session_v1
				WHERE calendar_id='XNAS' AND calendar_version='XNAS-HISTORICAL-2025-v1'
				AND session_date BETWEEN DATE '2025-01-03' AND DATE '2025-01-31'
				ORDER BY session_date,id
				""").query(UUID.class).list();
		assertEquals(21,sessions.size());
		UUID aapl=security(jdbc,"AAPL");
		UUID spy=security(jdbc,"SPY");
		UUID firstSession=sessions.getFirst();
		UUID firstAaplRequest=selector(jdbc,aapl,firstSession);
		UUID firstSpyRequest=selector(jdbc,spy,firstSession);
		var firstObservation=new RecordObservationRequest(firstSession,
				List.of(new ObservationSelectorInput(aapl,firstAaplRequest)),
				List.of(new ObservationSelectorInput(aapl,firstAaplRequest)),firstSpyRequest);
		concurrently(
				()->tx.execute(status->service.recordObservation(user,portfolioId,evaluation.evaluationId(),
						"spring-v31-history-observation-0",firstObservation)),
				()->competingTx.execute(status->competingService.recordObservation(user,portfolioId,evaluation.evaluationId(),
						"spring-v31-history-observation-0",firstObservation)));
		assertThrows(PortfolioContextException.class,()->tx.execute(status->service.recordObservation(user,portfolioId,
				evaluation.evaluationId(),"spring-v31-history-observation-0",
				new RecordObservationRequest(sessions.get(1),firstObservation.acceptedSelectorRequestIds(),
						firstObservation.holdSelectorRequestIds(),firstObservation.benchmarkSelectorRequestId()))));
		var zeroFlow=new RecordExternalCashFlowRequest(firstSession,java.math.BigDecimal.ZERO,"NO_EXTERNAL_FLOW");
		concurrently(
				()->tx.execute(status->service.recordCashFlow(user,portfolioId,evaluation.evaluationId(),
						"spring-v31-history-cash",zeroFlow)),
				()->competingTx.execute(status->competingService.recordCashFlow(user,portfolioId,evaluation.evaluationId(),
						"spring-v31-history-cash",zeroFlow)));
		assertThrows(PortfolioContextException.class,()->tx.execute(status->service.recordCashFlow(user,portfolioId,
				evaluation.evaluationId(),"spring-v31-history-cash",
				new RecordExternalCashFlowRequest(firstSession,java.math.BigDecimal.ZERO,"CHANGED_REASON"))));
		for(int index=1;index<sessions.size();index++) {
			UUID session=sessions.get(index);
			UUID aaplRequest=selector(jdbc,aapl,session);
			UUID spyRequest=selector(jdbc,spy,session);
			var observation=new RecordObservationRequest(session,
					List.of(new ObservationSelectorInput(aapl,aaplRequest)),
					List.of(new ObservationSelectorInput(aapl,aaplRequest)),spyRequest);
			int ordinal=index;
			tx.executeWithoutResult(status -> service.recordObservation(user,portfolioId,evaluation.evaluationId(),
					"spring-v31-history-observation-"+ordinal,observation));
		}
		var maturity=new ProgressMaturityRequest(sessions.getLast(),20,null);
		var matured=concurrently(
				()->tx.execute(status->service.progressMaturity(user,portfolioId,evaluation.evaluationId(),
						"spring-v31-history-maturity-20",maturity)),
				()->competingTx.execute(status->competingService.progressMaturity(user,portfolioId,evaluation.evaluationId(),
						"spring-v31-history-maturity-20",maturity)));
		var completed=matured.getFirst();
		assertEquals(completed,matured.getLast());
		assertThrows(PortfolioContextException.class,()->tx.execute(status->service.progressMaturity(user,portfolioId,
				evaluation.evaluationId(),"spring-v31-history-maturity-20",
				new ProgressMaturityRequest(sessions.getLast(),20,"CHANGED_TERMINAL_REASON"))));
		var summary=completed.summaries().getFirst();
		assertEquals(20,summary.horizonSessions());
		assertEquals(21,summary.observationCount());
		assertNotNull(summary.holdCurrentReturn());
		assertNotNull(summary.acceptedExcessVsHoldCurrent());
		assertEquals("0.5",summary.totalCost());
		UUID maturationCommandId=jdbc.sql("SELECT id FROM app.simulated_portfolio_maturation_command_v1 WHERE evaluation_id=:evaluation AND horizon_sessions=20")
				.param("evaluation",evaluation.evaluationId()).query(UUID.class).single();
		var longitudinal=tx.execute(status->service.sealLongitudinal(user,portfolioId,evaluation.evaluationId(),
				"spring-v32-longitudinal-20",new SealLongitudinalRequest(20,maturationCommandId)));
		assertEquals(1,longitudinal.periods().stream().filter(period->period.horizonSessions()==20
				&&"AVAILABLE".equals(period.state())).count());
		assertEquals(longitudinal,tx.execute(status->service.sealLongitudinal(user,portfolioId,
				evaluation.evaluationId(),"spring-v32-longitudinal-20",
				new SealLongitudinalRequest(20,maturationCommandId))));
		var reviewRequest=new CreateThesisReviewRequest(20,ThesisReviewState.INSUFFICIENT_EVIDENCE,
				"More naturally matured observations are required.",null);
		var reviewed=tx.execute(status->service.reviewThesis(user,portfolioId,evaluation.evaluationId(),
				"spring-v32-thesis-20",reviewRequest));
		assertEquals(ThesisReviewState.INSUFFICIENT_EVIDENCE,reviewed.thesisReviews().getFirst().state());
		assertEquals(reviewed,tx.execute(status->service.reviewThesis(user,portfolioId,evaluation.evaluationId(),
				"spring-v32-thesis-20",reviewRequest)));
		assertThrows(PortfolioContextException.class,()->tx.execute(status->service.reviewThesis(user,
				portfolioId,evaluation.evaluationId(),"spring-v32-thesis-20",
				new CreateThesisReviewRequest(20,ThesisReviewState.CONFIRMED,"Changed content.",null))));
		assertThrows(PortfolioContextException.class,() -> tx.execute(status -> service.createEvaluation(user,
				portfolioId,scenarioId,"spring-v31-history-evaluation",
				new CreateEvaluationRequest(request.humanDecisionId(),contextId,scenarioId))));
		assertThrows(PortfolioContextException.class,() -> tx.execute(status -> service.createEvaluation(user,
				portfolioId,holdId,"spring-v31-history-evaluation",request)));
	}

	private static UUID selector(JdbcClient jdbc,UUID securityId,UUID sessionId) {
		return jdbc.sql("""
				SELECT request.request_id FROM analytics.evidence_selection_request_v1 request
				JOIN analytics.evidence_selection_result_v1 result ON result.request_id=request.request_id
				JOIN analytics.evidence_selection_seal_v1 seal ON seal.request_id=request.request_id
				WHERE request.security_id=:security AND request.completed_session_id=:session AND result.state='VALID'
				""").params(Map.of("security",securityId,"session",sessionId)).query(UUID.class).single();
	}

	private static UUID security(JdbcClient jdbc,String ticker) {
		return jdbc.sql("""
				SELECT DISTINCT request.security_id FROM analytics.evidence_selection_request_v1 request
				JOIN analytics.evidence_selection_result_v1 result ON result.request_id=request.request_id
				JOIN analytics.canonical_evidence_v1 evidence ON evidence.evidence_id=result.selected_evidence_id
				WHERE evidence.ticker=:ticker AND result.state='VALID'
				""").param("ticker",ticker).query(UUID.class).single();
	}

	private static <T> List<T> concurrently(Callable<T> first,Callable<T> second) {
		try(var executor=Executors.newFixedThreadPool(2)) {
			var ready=new CountDownLatch(2);var start=new CountDownLatch(1);
			Callable<T> synchronizedFirst=()->{ready.countDown();start.await();return first.call();};
			Callable<T> synchronizedSecond=()->{ready.countDown();start.await();return second.call();};
			Future<T> one=executor.submit(synchronizedFirst);Future<T> two=executor.submit(synchronizedSecond);
			ready.await();start.countDown();
			return List.of(one.get(),two.get());
		}catch(Exception exception){throw new AssertionError("Concurrent service operation failed",exception);}
	}
}
