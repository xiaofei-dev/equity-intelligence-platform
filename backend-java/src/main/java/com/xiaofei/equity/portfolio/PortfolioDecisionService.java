package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.PortfolioDecisionContracts.*;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.UUID;

import com.xiaofei.equity.usercontext.CurrentUser;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

@Service
public class PortfolioDecisionService {
	private static final JsonMapper MAPPER = JsonMapper.builder().build();
	private static final String CONTRACT = "portfolio-decision-scenario-v1.0.0";
	private static final String RESULT = "portfolio-decision-scenario-result-v1.0.0";
	private static final String ENGINE = "PORTFOLIO-DECISION-SCENARIO-ENGINE-v1.0.0";
	private static final String ECONOMICS = "PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0";
	private static final String RECOMMENDATION = "PORTFOLIO-RECOMMENDATION-v1.0.0";
	static final String SCENARIO_PROJECTION_QUERY = """
			SELECT scenario_type,scenario_state,content_hash,new_money_amount,
			 transaction_cost_bps,slippage_bps,tax_estimate_state,current_cash,final_cash,
			 final_asset_value,gross_traded_notional,estimated_total_cost,one_way_turnover,
			 COALESCE((SELECT sum(position.current_value)
			   FROM app.portfolio_scenario_position_v1 position
			   WHERE position.scenario_id=scenario.id AND position.user_id=scenario.user_id),0)
			FROM app.portfolio_decision_scenario_v1 scenario
			WHERE id=:scenario AND user_id=:user AND portfolio_id=:portfolio AND sealed_at IS NOT NULL
			""";
	private static final Set<String> ROOT_FIELDS = Set.of("resultVersion", "engineVersion",
			"contractVersion", "scenarioType", "inputContentHash", "status", "reasonCodes",
			"positions", "economics", "constraintStatus", "authority", "contentHash");
	private final JdbcClient jdbc;
	private final PortfolioDecisionAnalyticsClient analytics;
	private final PortfolioDecisionClock clock;

	public PortfolioDecisionService(JdbcClient jdbc, PortfolioDecisionAnalyticsClient analytics) {
		this(jdbc, analytics, new PortfolioDecisionClock());
	}

	@Autowired
	PortfolioDecisionService(JdbcClient jdbc, PortfolioDecisionAnalyticsClient analytics,
			PortfolioDecisionClock clock) {
		this.jdbc = jdbc;
		this.analytics = analytics;
		this.clock = clock;
	}

	@Transactional
	public ScenarioResponse create(CurrentUser user, UUID portfolioId, String key,
			CreateScenarioRequest request) {
		throw invalid("EXACT_FOUR_SCENARIO_COMPARISON_REQUIRED");
	}

	@Transactional
	public ScenarioComparisonResponse createComparison(CurrentUser user, UUID portfolioId, String key,
			CreateScenarioComparisonRequest request) {
		requireKey(key);
		lockIdempotency(user.userId(), "comparison", key);
		Instant frozenCutoff=clock.now();
		UUID deterministicComparisonId = UUID.nameUUIDFromBytes((user.userId()+"|"+portfolioId+"|"+key+"|"+
				comparisonPayloadHash(request)).getBytes(StandardCharsets.UTF_8));
		String replayId = jdbc.sql("SELECT id::text FROM app.portfolio_scenario_comparison_v1 WHERE user_id=:user AND idempotency_key=:key")
				.params(Map.of("user", user.userId(), "key", key)).query(String.class).optional().orElse(null);
		if (replayId != null) {
			if (!UUID.fromString(replayId).equals(deterministicComparisonId)) throw conflict();
			return comparison(user, portfolioId, deterministicComparisonId);
		}
		ContextRow context = loadContext(user.userId(), portfolioId, request.contextId());
		loadPolicy(user.userId(), portfolioId, request.constraintPolicyVersionId());
		requireManifest(user.userId(), portfolioId, request.contextId(), request.evidenceManifestId());
		List<UUID> scenarioIds = new ArrayList<>();
		for (ScenarioType type : ScenarioType.values()) {
			CreateScenarioRequest scenarioRequest = comparisonScenarioRequest(request,type);
			List<CandidateInput> candidates = scenarioRequest.candidates();
			List<PositionRow> positions = loadPositions(user.userId(), request.contextId(),
					request.evidenceManifestId());
			Map<UUID, CandidateInput> candidateMap = candidates(scenarioRequest, positions);
			JsonNode command = command(context, loadPolicy(user.userId(), portfolioId,
					request.constraintPolicyVersionId()), scenarioRequest, positions, candidateMap);
			JsonNode result = validateResult(analytics.evaluate(command), type, command);
			String scenarioKey = key + ":" + type.name();
			persist(user, portfolioId, scenarioKey, scenarioRequest, context, result, candidateMap, false,
					frozenCutoff);
			scenarioIds.add(jdbc.sql("SELECT id FROM app.portfolio_decision_scenario_v1 WHERE user_id=:user AND idempotency_key=:key")
					.params(Map.of("user", user.userId(), "key", scenarioKey)).query(UUID.class).single());
		}
		UUID comparisonId = deterministicComparisonId;
		String contentHash=jdbc.sql("""
				SELECT 'sha256:'||encode(sha256(convert_to(:portfolio::text||'|'||:context::text||'|'||
				 string_agg(scenario_type||':'||id::text||':'||content_hash,'|' ORDER BY scenario_type),'UTF8')),'hex')
				FROM app.portfolio_decision_scenario_v1 WHERE id=ANY(:scenarios::uuid[])
				""").params(Map.of("portfolio",portfolioId,"context",request.contextId(),
				"scenarios",scenarioIds.toArray(UUID[]::new))).query(String.class).single();
		jdbc.sql("""
				INSERT INTO app.portfolio_scenario_comparison_v1
				(id,user_id,portfolio_id,context_id,expected_scenario_count,idempotency_key,request_hash,content_hash)
				VALUES (:id,:user,:portfolio,:context,4,:key,:requestHash,:contentHash)
				""").params(Map.of("id", comparisonId, "user", user.userId(), "portfolio", portfolioId,
				"context", request.contextId(), "key", key, "requestHash", comparisonRequestHash(
						comparisonId, user.userId(), portfolioId, request.contextId()),
				"contentHash", contentHash)).update();
		for (UUID scenarioId : scenarioIds) jdbc.sql("""
				INSERT INTO app.portfolio_scenario_comparison_item_v1
				(comparison_id,user_id,scenario_type,scenario_id,scenario_content_hash)
				SELECT :comparison,:user,scenario_type,id,content_hash
				FROM app.portfolio_decision_scenario_v1 WHERE id=:scenario
				""").params(Map.of("comparison", comparisonId, "user", user.userId(), "scenario", scenarioId)).update();
		jdbc.sql("UPDATE app.portfolio_scenario_comparison_v1 SET sealed_at=CURRENT_TIMESTAMP WHERE id=:id")
				.param("id", comparisonId).update();
		return comparison(user, portfolioId, comparisonId);
	}

	static CreateScenarioRequest comparisonScenarioRequest(CreateScenarioComparisonRequest request,
			ScenarioType type) {
		List<CandidateInput> candidates = request.candidates().stream()
				.map(candidate -> new CandidateInput(candidate.securityId(), candidate.permission(),
						candidate.humanApprovedCandidate(),
						(type == ScenarioType.HOLD_CURRENT || type == ScenarioType.NEW_MONEY_ONLY)
								? null : candidate.targetMarketValue())).toList();
		BigDecimal newMoney = type == ScenarioType.HOLD_CURRENT ? BigDecimal.ZERO : request.newMoneyAmount();
		return new CreateScenarioRequest(request.contextId(),request.evidenceManifestId(),
				request.constraintPolicyVersionId(),type,newMoney,request.sleeveBudgets(),candidates);
	}

	@Transactional
	public ScenarioComparisonResponse selectComparison(CurrentUser user, UUID portfolioId,
			UUID comparisonId, String key, SelectScenarioComparisonRequest request) {
		requireKey(key);
		lockIdempotency(user.userId(), "comparison-selection", comparisonId + "|" + key);
		ScenarioComparisonResponse current = comparison(user, portfolioId, comparisonId);
		UUID selectedScenarioId = current.scenarios().stream()
				.filter(item -> item.scenarioType() == request.selectedScenarioType())
				.map(ScenarioComparisonItem::scenarioId).findFirst().orElseThrow(PortfolioDecisionService::conflict);
		if (current.selectedScenarioId() != null) {
			if (!current.selectedScenarioId().equals(selectedScenarioId)) throw conflict();
			return current;
		}
		createRecommendationAndBinding(user, portfolioId, comparisonId, selectedScenarioId, key);
		return comparison(user, portfolioId, comparisonId);
	}

	public ScenarioResponse get(CurrentUser user, UUID portfolioId, UUID scenarioId) {
		return read(user.userId(), portfolioId, scenarioId);
	}

	public List<ScenarioResponse> list(CurrentUser user, UUID portfolioId) {
		return jdbc.sql("""
				SELECT DISTINCT ON (scenario.scenario_type) scenario.id
				FROM app.portfolio_decision_scenario_v1 scenario
				JOIN app.portfolio_recommendation_v1 recommendation
				 ON recommendation.scenario_id=scenario.id AND recommendation.user_id=scenario.user_id
				WHERE scenario.user_id=:user AND scenario.portfolio_id=:portfolio
				AND scenario.sealed_at IS NOT NULL AND recommendation.sealed_at IS NOT NULL
				ORDER BY scenario.scenario_type, scenario.recorded_at DESC, scenario.id
				""").params(Map.of("user", user.userId(), "portfolio", portfolioId))
				.query(UUID.class).list().stream().map(id -> read(user.userId(), portfolioId, id))
				.sorted(Comparator.comparing(value -> value.scenarioType().name())).toList();
	}

	public ScenarioComparisonResponse latestComparison(CurrentUser user, UUID portfolioId) {
		UUID comparisonId=jdbc.sql("""
				SELECT id FROM app.portfolio_scenario_comparison_v1
				WHERE user_id=:user AND portfolio_id=:portfolio AND sealed_at IS NOT NULL
				ORDER BY recorded_at DESC,id LIMIT 1
				""").params(Map.of("user",user.userId(),"portfolio",portfolioId))
				.query(UUID.class).optional().orElseThrow(PortfolioDecisionService::notFound);
		return comparison(user,portfolioId,comparisonId);
	}

	private ScenarioComparisonResponse comparison(CurrentUser user,UUID portfolioId,UUID comparisonId) {
		ComparisonRoot root = jdbc.sql("""
				SELECT id,context_id,expected_scenario_count,content_hash,sealed_at
				FROM app.portfolio_scenario_comparison_v1
				WHERE id=:comparison AND user_id=:user AND portfolio_id=:portfolio AND sealed_at IS NOT NULL
				""").params(Map.of("comparison",comparisonId,"user",user.userId(),"portfolio",portfolioId))
				.query((rs,n)->new ComparisonRoot(rs.getObject(1,UUID.class),rs.getObject(2,UUID.class),
					rs.getInt(3),rs.getString(4),wholeSecond(rs.getTimestamp(5).toInstant())))
				.optional().orElseThrow(PortfolioDecisionService::notFound);
		List<ScenarioComparisonItem> items=jdbc.sql("""
				SELECT scenario_type,scenario_id,scenario_content_hash
				FROM app.portfolio_scenario_comparison_item_v1
				WHERE comparison_id=:comparison AND user_id=:user ORDER BY scenario_type
				""").params(Map.of("comparison",root.id(),"user",user.userId()))
				.query((rs,n)->{
					UUID scenarioId=rs.getObject(2,UUID.class);
					return new ScenarioComparisonItem(ScenarioType.valueOf(rs.getString(1)),
						scenarioId,rs.getString(3),scenarioProjection(user.userId(),portfolioId,scenarioId));
				}).list();
		if(items.size()!=4 || items.stream().map(ScenarioComparisonItem::scenarioType).distinct().count()!=4)
			throw conflict();
		UUID selected=jdbc.sql("""
				SELECT selected_scenario_id FROM app.portfolio_recommendation_comparison_binding_v1
				WHERE comparison_id=:comparison AND user_id=:user ORDER BY recorded_at DESC LIMIT 1
				""").params(Map.of("comparison",root.id(),"user",user.userId()))
				.query(UUID.class).optional().orElse(null);
		return new ScenarioComparisonResponse(root.id(),portfolioId,root.contextId(),root.expectedCount(),
				items,selected,selected==null?"AWAITING_RECOMMENDATION":"RECOMMENDATION_BOUND",
				root.contentHash(),root.sealedAt());
	}

	private ScenarioProjection scenarioProjection(UUID userId, UUID portfolioId, UUID scenarioId) {
		ScenarioProjectionRoot root=jdbc.sql(SCENARIO_PROJECTION_QUERY)
				.params(Map.of("scenario",scenarioId,"user",userId,"portfolio",portfolioId))
				.query((rs,n)->new ScenarioProjectionRoot(ScenarioType.valueOf(rs.getString(1)),rs.getString(2),
					rs.getString(3),rs.getBigDecimal(4),rs.getBigDecimal(5),rs.getBigDecimal(6),rs.getString(7),
					rs.getBigDecimal(8),rs.getBigDecimal(9),rs.getBigDecimal(10),rs.getBigDecimal(11),
					rs.getBigDecimal(12),rs.getBigDecimal(13),rs.getBigDecimal(14))).single();
		List<DecisionPosition> positions=jdbc.sql("""
				SELECT context.ticker,position.sleeve_type,position.current_value,position.target_value,
				 position.value_delta,position.target_weight,position.permission,position.estimated_cost,
				 position.estimated_tax,position.security_public_id
				FROM app.portfolio_scenario_position_v1 position
				JOIN app.portfolio_decision_scenario_v1 scenario ON scenario.id=position.scenario_id
				JOIN app.unified_portfolio_position_v1 context ON context.context_id=scenario.context_id
				 AND context.security_public_id=position.security_public_id
				WHERE position.scenario_id=:scenario AND position.user_id=:user ORDER BY position.ordinal
				""").params(Map.of("scenario",scenarioId,"user",userId)).query((rs,n)->new DecisionPosition(
				rs.getObject(10,UUID.class),rs.getString(1),rs.getString(2),rs.getString(3),rs.getString(4),
				rs.getString(5),rs.getString(6),rs.getString(7),rs.getString(8),rs.getString(9))).list();
		List<String> reasons=jdbc.sql("SELECT reason_code FROM app.portfolio_scenario_reason_v1 WHERE scenario_id=:scenario AND user_id=:user ORDER BY ordinal")
				.params(Map.of("scenario",scenarioId,"user",userId)).query(String.class).list();
		DecisionEconomics economics=scenarioProjectionEconomics(root.state(),root.newMoney(),
				root.transactionCostBps(),root.slippageBps(),root.taxState(),root.currentCash(),
				root.finalCash(),root.finalAssetValue(),root.grossTraded(),root.totalCost(),root.turnover(),
				root.currentInvested(),positions);
		return new ScenarioProjection(scenarioId,root.type(),root.state(),candidateState(root.state()),positions,
				economics,reasons,root.contentHash());
	}

	static String candidateState(String scenarioState) {
		return "INFEASIBLE".equals(scenarioState)?"NO_FEASIBLE_CANDIDATE":"CANDIDATE_FOR_HUMAN_REVIEW";
	}

	static DecisionEconomics scenarioProjectionEconomics(String scenarioState,BigDecimal newMoney,
			BigDecimal transactionCostBps,BigDecimal slippageBps,String taxState,BigDecimal currentCash,
			BigDecimal finalCash,BigDecimal finalAssetValue,BigDecimal grossTraded,BigDecimal totalCost,
			BigDecimal turnover,BigDecimal currentInvested,List<DecisionPosition> positions) {
		if("INFEASIBLE".equals(scenarioState))return null;
		if(finalCash==null||finalAssetValue==null||grossTraded==null||totalCost==null||turnover==null)
			throw conflict();
		BigDecimal buys=positions.stream().map(DecisionPosition::valueDelta).map(BigDecimal::new)
				.filter(value->value.signum()>0).reduce(BigDecimal.ZERO,BigDecimal::add);
		BigDecimal sells=positions.stream().map(DecisionPosition::valueDelta).map(BigDecimal::new)
				.filter(value->value.signum()<0).map(BigDecimal::negate).reduce(BigDecimal.ZERO,BigDecimal::add);
		BigDecimal taxes=positions.stream().map(DecisionPosition::estimatedTax).filter(java.util.Objects::nonNull)
				.map(BigDecimal::new).reduce(BigDecimal.ZERO,BigDecimal::add);
		BigDecimal preCostAssets=currentCash.add(newMoney).add(currentInvested);
		if(preCostAssets.signum()<=0)throw conflict();
		return new DecisionEconomics(decimal(newMoney),decimal(transactionCostBps),decimal(slippageBps),
				decimal(buys),decimal(sells),decimal(grossTraded),decimal(totalCost),"NOT_ESTIMATED",taxState,
				"AVAILABLE_APPLIED".equals(taxState)?decimal(taxes):null,decimal(taxes),decimal(turnover),
				decimal(grossTraded.divide(preCostAssets,java.math.MathContext.DECIMAL128)),
				decimal(finalCash),decimal(finalAssetValue));
	}

	public LongitudinalProjectionResponse longitudinalProjection(CurrentUser user,UUID portfolioId,
			UUID evaluationId) {
		loadEvaluationHeader(user.userId(),portfolioId,evaluationId);
		List<LongitudinalPeriod> periods=jdbc.sql("""
				SELECT maturity.horizon_sessions,
				 CASE WHEN summary.id IS NOT NULL THEN 'AVAILABLE' ELSE maturity.maturity_state END,
				 summary.period_start,summary.period_end,summary.expected_observation_count,
				 COALESCE(summary.observation_count,0),summary.coverage_rate,summary.gross_return,
				 summary.net_return,summary.hold_current_return,summary.benchmark_return,
				 summary.accepted_excess_vs_hold,summary.accepted_excess_vs_benchmark,
				 summary.true_maximum_drawdown,summary.total_turnover,summary.total_cost,summary.content_hash
				FROM app.simulated_portfolio_maturity_v1 maturity
				LEFT JOIN app.simulated_portfolio_longitudinal_summary_v1 summary
				 ON summary.evaluation_id=maturity.evaluation_id AND summary.user_id=maturity.user_id
				 AND summary.horizon_sessions=maturity.horizon_sessions
				WHERE maturity.evaluation_id=:evaluation AND maturity.user_id=:user
				ORDER BY maturity.horizon_sessions
				""").params(Map.of("evaluation",evaluationId,"user",user.userId())).query((rs,n)->
				new LongitudinalPeriod(rs.getInt(1),rs.getString(2),
					rs.getObject(3)==null?null:rs.getObject(3,java.time.LocalDate.class).toString(),
					rs.getObject(4)==null?null:rs.getObject(4,java.time.LocalDate.class).toString(),
					rs.getObject(5)==null?0:rs.getInt(5),rs.getInt(6),decimalOrNull(rs.getBigDecimal(7)),
					decimalOrNull(rs.getBigDecimal(8)),decimalOrNull(rs.getBigDecimal(9)),
					decimalOrNull(rs.getBigDecimal(10)),decimalOrNull(rs.getBigDecimal(11)),
					decimalOrNull(rs.getBigDecimal(12)),decimalOrNull(rs.getBigDecimal(13)),
					decimalOrNull(rs.getBigDecimal(14)),decimalOrNull(rs.getBigDecimal(15)),
					decimalOrNull(rs.getBigDecimal(16)),rs.getString(17))).list();
		List<ThesisReviewSummary> reviews=jdbc.sql("""
				SELECT DISTINCT ON (horizon_sessions) id,horizon_sessions,review_state,rationale,
				 supersedes_review_id,reviewed_at,content_hash
				FROM app.portfolio_thesis_review_v1 WHERE evaluation_id=:evaluation AND user_id=:user
				ORDER BY horizon_sessions,reviewed_at DESC,id DESC
				""").params(Map.of("evaluation",evaluationId,"user",user.userId())).query((rs,n)->
				new ThesisReviewSummary(rs.getObject(1,UUID.class),rs.getInt(2),
					ThesisReviewState.valueOf(rs.getString(3)),rs.getString(4),rs.getObject(5,UUID.class),
					wholeSecond(rs.getTimestamp(6).toInstant()),rs.getString(7))).list();
		return new LongitudinalProjectionResponse(evaluationId,portfolioId,periods,reviews);
	}

	@Transactional
	LongitudinalProjectionResponse sealLongitudinal(CurrentUser user, UUID portfolioId,
			UUID evaluationId, String key, SealLongitudinalRequest request) {
		requireKey(key);
		lockIdempotency(user.userId(), "longitudinal", key);
		loadEvaluationHeader(user.userId(), portfolioId, evaluationId);
		UUID existing = jdbc.sql("SELECT id FROM app.simulated_portfolio_longitudinal_command_v1 WHERE user_id=:user AND idempotency_key=:key")
				.params(Map.of("user",user.userId(),"key",key)).query(UUID.class).optional().orElse(null);
		if (existing != null) {
			int exact = jdbc.sql("SELECT count(*) FROM app.simulated_portfolio_longitudinal_command_v1 WHERE id=:id AND evaluation_id=:evaluation AND horizon_sessions=:horizon AND maturation_command_id=:maturity AND sealed_at IS NOT NULL")
					.params(Map.of("id",existing,"evaluation",evaluationId,"horizon",request.horizonSessions(),
							"maturity",request.maturationCommandId())).query(Integer.class).single();
			if (exact != 1) throw conflict();
			return longitudinalProjection(user,portfolioId,evaluationId);
		}
		UUID id=UUID.randomUUID();
		String requestHash=hash(id+"|"+evaluationId+"|"+request.horizonSessions()+"|"+request.maturationCommandId());
		jdbc.sql("""
				INSERT INTO app.simulated_portfolio_longitudinal_command_v1
				(id,evaluation_id,user_id,horizon_sessions,maturation_command_id,idempotency_key,request_hash)
				VALUES (:id,:evaluation,:user,:horizon,:maturity,:key,:hash)
				""").params(Map.of("id",id,"evaluation",evaluationId,"user",user.userId(),
				"horizon",request.horizonSessions(),"maturity",request.maturationCommandId(),
				"key",key,"hash",requestHash)).update();
		jdbc.sql("UPDATE app.simulated_portfolio_longitudinal_command_v1 SET sealed_at=CURRENT_TIMESTAMP WHERE id=:id")
				.param("id",id).update();
		return longitudinalProjection(user,portfolioId,evaluationId);
	}

	LongitudinalProjectionResponse sealLongitudinalByHorizon(CurrentUser user,UUID portfolioId,
			UUID evaluationId,String key,SealLongitudinalByHorizonRequest request) {
		UUID maturation=jdbc.sql("""
				SELECT id FROM app.simulated_portfolio_maturation_command_v1
				WHERE evaluation_id=:evaluation AND user_id=:user AND horizon_sessions=:horizon
				 AND terminal_reason IS NULL
				""").params(Map.of("evaluation",evaluationId,"user",user.userId(),
				"horizon",request.horizonSessions())).query(UUID.class).optional()
				.orElseThrow(PortfolioDecisionService::notFound);
		return sealLongitudinal(user,portfolioId,evaluationId,key,
				new SealLongitudinalRequest(request.horizonSessions(),maturation));
	}

	@Transactional
	LongitudinalProjectionResponse reviewThesis(CurrentUser user, UUID portfolioId,
			UUID evaluationId, String key, CreateThesisReviewRequest request) {
		requireKey(key);
		lockIdempotency(user.userId(), "thesis", key);
		loadEvaluationHeader(user.userId(),portfolioId,evaluationId);
		UUID existing=jdbc.sql("SELECT id FROM app.portfolio_thesis_review_v1 WHERE user_id=:user AND idempotency_key=:key")
				.params(Map.of("user",user.userId(),"key",key)).query(UUID.class).optional().orElse(null);
		UUID summary=jdbc.sql("SELECT id FROM app.simulated_portfolio_longitudinal_summary_v1 WHERE evaluation_id=:evaluation AND user_id=:user AND horizon_sessions=:horizon")
				.params(Map.of("evaluation",evaluationId,"user",user.userId(),"horizon",request.horizonSessions()))
				.query(UUID.class).optional().orElseThrow(PortfolioDecisionService::notFound);
		String requestHash=hash(evaluationId+"|"+request.horizonSessions()+"|"+summary+"|"+
				request.state()+"|"+request.rationale());
		if(existing!=null) {
			String stored=jdbc.sql("SELECT request_hash FROM app.portfolio_thesis_review_v1 WHERE id=:id")
					.param("id",existing).query(String.class).single();
			if(!stored.equals(requestHash))throw conflict();
			return longitudinalProjection(user,portfolioId,evaluationId);
		}
		UUID id=UUID.randomUUID(); Instant reviewed=clock.now();
		String summaryHash=jdbc.sql("SELECT content_hash FROM app.simulated_portfolio_longitudinal_summary_v1 WHERE id=:id")
				.param("id",summary).query(String.class).single();
		String contentHash=jdbc.sql("SELECT 'sha256:'||encode(sha256(convert_to(:requestHash||'|'||:summaryHash||'|'||:reviewed::timestamptz::text||'|'||:supersedes,'UTF8')),'hex')")
				.params(Map.of("requestHash",requestHash,"summaryHash",summaryHash,
						"reviewed",Timestamp.from(reviewed),"supersedes",request.supersedesReviewId()==null?"":request.supersedesReviewId().toString()))
				.query(String.class).single();
		jdbc.sql("""
				INSERT INTO app.portfolio_thesis_review_v1
				(id,evaluation_id,user_id,horizon_sessions,longitudinal_summary_id,review_state,rationale,
				 supersedes_review_id,idempotency_key,request_hash,content_hash,reviewed_at)
				VALUES (:id,:evaluation,:user,:horizon,:summary,:state,:rationale,:supersedes,:key,:requestHash,:contentHash,:reviewed)
				""").params(Map.ofEntries(Map.entry("id",id),Map.entry("evaluation",evaluationId),Map.entry("user",user.userId()),
				Map.entry("horizon",request.horizonSessions()),Map.entry("summary",summary),Map.entry("state",request.state().name()),
				Map.entry("rationale",request.rationale()),Map.entry("supersedes",nullable(request.supersedesReviewId())),
				Map.entry("key",key),Map.entry("requestHash",requestHash),Map.entry("contentHash",contentHash),
				Map.entry("reviewed",Timestamp.from(reviewed)))).update();
		return longitudinalProjection(user,portfolioId,evaluationId);
	}

	@Transactional
	public EvaluationResponse createEvaluation(CurrentUser user, UUID portfolioId, UUID scenarioId,
			String key, CreateEvaluationRequest request) {
		requireKey(key);
		EvaluationResponse replay = findEvaluationByKey(user.userId(), portfolioId, key);
		if (replay != null) {
			String stored=jdbc.sql("SELECT request_hash FROM app.simulated_portfolio_evaluation_v1 WHERE id=:id")
					.param("id",replay.evaluationId()).query(String.class).single();
			if(!stored.equals(hash(portfolioId+"|"+scenarioId+"|"+request)))throw conflict();
			return replay;
		}
		int binding = jdbc.sql("""
				SELECT count(*) FROM app.portfolio_human_decision_v1 d
				JOIN app.portfolio_recommendation_v1 r ON r.id=d.recommendation_id AND r.user_id=d.user_id
				WHERE d.id=:decision AND d.user_id=:user AND d.portfolio_id=:portfolio
				AND r.scenario_id=:scenario AND d.conclusion='ACCEPTED'
				""").params(Map.of("decision", request.humanDecisionId(), "user", user.userId(),
				"portfolio", portfolioId, "scenario", scenarioId)).query(Integer.class).single();
		if (binding != 1) throw notFound();
		SessionRow session = jdbc.sql("""
				WITH anchor_calendar AS (
				 SELECT min(anchor.calendar_id) calendar_id,min(anchor.calendar_version) calendar_version,
				        greatest(scenario.decision_cutoff,hold.decision_cutoff,manifest.decision_cutoff,
				          context.as_of_time,decision.decided_at) decision_cutoff
				FROM app.portfolio_decision_scenario_v1 scenario
				JOIN app.unified_portfolio_context_v1 context
				  ON context.id=:context AND context.user_id=scenario.user_id AND context.portfolio_id=scenario.portfolio_id
				JOIN app.portfolio_human_decision_v1 decision
				  ON decision.id=:decision AND decision.user_id=scenario.user_id
				JOIN app.portfolio_decision_scenario_v1 hold
				  ON hold.id=:hold AND hold.user_id=scenario.user_id AND hold.portfolio_id=scenario.portfolio_id
				JOIN app.portfolio_context_evidence_manifest_v1 manifest
				  ON manifest.id=scenario.evidence_manifest_id AND manifest.user_id=scenario.user_id
				JOIN app.portfolio_context_position_evidence_v1 position_evidence
				  ON position_evidence.manifest_id=manifest.id AND position_evidence.price_selection_request_id IS NOT NULL
				JOIN analytics.evidence_selection_request_v1 selection_request
				  ON selection_request.request_id=position_evidence.price_selection_request_id
				JOIN analytics.evidence_completed_session_v1 anchor
				  ON anchor.id=selection_request.completed_session_id
				WHERE scenario.id=:scenario AND scenario.user_id=:user AND scenario.portfolio_id=:portfolio
				GROUP BY scenario.decision_cutoff,hold.decision_cutoff,manifest.decision_cutoff,
				 context.as_of_time,decision.decided_at
				HAVING count(DISTINCT (anchor.calendar_id,anchor.calendar_version))=1)
				SELECT next.id,next.session_date,next.calendar_id,next.calendar_version,next.session_content_hash
				FROM anchor_calendar anchor JOIN analytics.evidence_completed_session_v1 next
				 ON next.calendar_id=anchor.calendar_id AND next.calendar_version=anchor.calendar_version
				 AND next.status='COMPLETED' AND next.session_date>(anchor.decision_cutoff AT TIME ZONE 'UTC')::date
				 AND next.completed_at>anchor.decision_cutoff
				ORDER BY next.session_date,next.id LIMIT 1
				""").params(Map.of("scenario",scenarioId,"user",user.userId(),"portfolio",portfolioId,
						"context",request.startingContextId(),"decision",request.humanDecisionId(),
						"hold",request.holdCurrentScenarioId()))
				.query((rs, n) -> new SessionRow(rs.getObject(1,UUID.class),
				rs.getObject(2, java.time.LocalDate.class), rs.getString(3), rs.getString(4), rs.getString(5)))
				.optional().orElseThrow(PortfolioDecisionService::notFound);
		UUID id = UUID.randomUUID(); Instant now = clock.now();
		String requestHash = hash(portfolioId+"|"+scenarioId+"|"+request);
		String contentHash = hash(id + "|" + requestHash + "|SPY");
		jdbc.sql("""
				INSERT INTO app.simulated_portfolio_evaluation_v1
				(id,user_id,portfolio_id,human_decision_id,starting_context_id,accepted_scenario_id,
				 hold_current_scenario_id,
				 contract_version,benchmark_code,benchmark_policy_version,cost_policy_version,
				 entry_completed_session_id,entry_calendar_id,entry_calendar_version,entry_session_content_hash,
				 start_session_date,expected_maturity_count,idempotency_key,request_hash,content_hash,recorded_at)
				VALUES (:id,:user,:portfolio,:decision,:context,:accepted,:hold,
				 'simulated-portfolio-evaluation-v1.0.0',
				 'SPY','SPY-BUY-HOLD-v1.0.0','PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0',:session,:calendar,
				 :calendarVersion,:sessionHash,:start,5,:key,:requestHash,:contentHash,:recorded)
				""").params(Map.ofEntries(Map.entry("id", id), Map.entry("user", user.userId()),
				Map.entry("portfolio", portfolioId), Map.entry("decision", request.humanDecisionId()),
				Map.entry("context", request.startingContextId()), Map.entry("accepted", scenarioId),
				Map.entry("hold", request.holdCurrentScenarioId()),
				Map.entry("session", session.id()), Map.entry("calendar", session.calendarId()),
				Map.entry("calendarVersion", session.calendarVersion()), Map.entry("sessionHash", session.contentHash()),
				Map.entry("start", session.sessionDate()), Map.entry("key", key),
				Map.entry("requestHash", requestHash), Map.entry("contentHash", contentHash),
				Map.entry("recorded", Timestamp.from(now)))).update();
		for (int horizon : List.of(20, 60, 252, 504, 756)) jdbc.sql("""
				INSERT INTO app.simulated_portfolio_maturity_v1
				(evaluation_id,user_id,horizon_sessions,maturity_state)
				VALUES (:id,:user,:horizon,'AWAITING_NATURAL_MATURITY')
				""").params(Map.of("id", id, "user", user.userId(), "horizon", horizon)).update();
		createOpeningLedger(id,user.userId(),request.startingContextId(),scenarioId,
				request.holdCurrentScenarioId(),session.id());
		jdbc.sql("UPDATE app.simulated_portfolio_evaluation_v1 SET sealed_at=:sealed WHERE id=:id")
				.params(Map.of("sealed", Timestamp.from(now), "id", id)).update();
		return readEvaluation(user.userId(), portfolioId, id);
	}

	public EvaluationResponse getEvaluation(CurrentUser user, UUID portfolioId, UUID scenarioId,
			UUID evaluationId) {
		EvaluationResponse result = readEvaluation(user.userId(), portfolioId, evaluationId);
		requireEvaluationScenario(user.userId(), scenarioId, result.humanDecisionId());
		return result;
	}

	public EvaluationResponse latestEvaluation(CurrentUser user, UUID portfolioId, UUID scenarioId) {
		UUID id = jdbc.sql("""
				SELECT e.id FROM app.simulated_portfolio_evaluation_v1 e
				JOIN app.portfolio_human_decision_v1 d ON d.id=e.human_decision_id AND d.user_id=e.user_id
				JOIN app.portfolio_recommendation_v1 r ON r.id=d.recommendation_id AND r.user_id=d.user_id
				WHERE e.user_id=:user AND e.portfolio_id=:portfolio AND r.scenario_id=:scenario
				AND e.sealed_at IS NOT NULL ORDER BY e.recorded_at DESC,e.id LIMIT 1
				""").params(Map.of("user", user.userId(), "portfolio", portfolioId, "scenario", scenarioId))
				.query(UUID.class).optional().orElseThrow(PortfolioDecisionService::notFound);
		return readEvaluation(user.userId(), portfolioId, id);
	}

	@Transactional
	EvaluationResponse recordObservation(CurrentUser user,UUID portfolioId,UUID evaluationId,
			String key,RecordObservationRequest request) {
		requireKey(key);lockIdempotency(user.userId(),"observation",key);
		loadEvaluationHeader(user.userId(),portfolioId,evaluationId);
		UUID commandId=UUID.randomUUID();String requestHash=hash(evaluationId+"|"+request);
		String replayHash=jdbc.sql("SELECT request_hash FROM app.simulated_portfolio_observation_command_v1 WHERE user_id=:user AND idempotency_key=:key AND sealed_at IS NOT NULL")
				.params(Map.of("user",user.userId(),"key",key)).query(String.class).optional().orElse(null);
		if(replayHash!=null){if(!replayHash.equals(requestHash))throw conflict();return readEvaluation(user.userId(),portfolioId,evaluationId);}
		int inserted=jdbc.sql("""
				INSERT INTO app.simulated_portfolio_observation_command_v1
				(id,evaluation_id,user_id,completed_session_id,benchmark_selection_request_id,idempotency_key,request_hash)
				VALUES (:id,:evaluation,:user,:session,:benchmark,:key,:hash)
				ON CONFLICT DO NOTHING""")
				.params(Map.of("id",commandId,"evaluation",evaluationId,"user",user.userId(),
						"session",request.completedSessionId(),"benchmark",request.benchmarkSelectorRequestId(),
						"key",key,"hash",requestHash)).update();
		if(inserted==0){return replayObservation(user,portfolioId,evaluationId,key,requestHash);}
		insertObservationSelectors(commandId,user.userId(),"ACCEPTED",request.acceptedSelectorRequestIds());
		insertObservationSelectors(commandId,user.userId(),"HOLD_CURRENT",request.holdSelectorRequestIds());
		jdbc.sql("UPDATE app.simulated_portfolio_observation_command_v1 SET sealed_at=CURRENT_TIMESTAMP WHERE id=:id")
				.param("id",commandId).update();
		return readEvaluation(user.userId(),portfolioId,evaluationId);
	}

	@Transactional
	EvaluationResponse recordCashFlow(CurrentUser user,UUID portfolioId,UUID evaluationId,String key,
			RecordExternalCashFlowRequest request) {
		requireKey(key);lockIdempotency(user.userId(),"cash-flow",key);
		loadEvaluationHeader(user.userId(),portfolioId,evaluationId);
		if(request.amount().signum()!=0)throw invalid("EXTERNAL_CASH_FLOW_NOT_SUPPORTED_IN_MVP");
		String contentHash=hash(evaluationId+"|"+request.completedSessionId()+"|"+
				decimal(request.amount())+"|"+request.reason());
		String replay=jdbc.sql("SELECT content_hash FROM app.simulated_portfolio_external_cash_flow_v1 WHERE user_id=:user AND idempotency_key=:key")
				.params(Map.of("user",user.userId(),"key",key)).query(String.class).optional().orElse(null);
		if(replay!=null){if(!replay.equals(contentHash))throw conflict();return readEvaluation(user.userId(),portfolioId,evaluationId);}
		int inserted=jdbc.sql("""
				INSERT INTO app.simulated_portfolio_external_cash_flow_v1
				(id,evaluation_id,user_id,completed_session_id,amount,reason,idempotency_key,content_hash)
				VALUES (:id,:evaluation,:user,:session,:amount,:reason,:key,:hash)
				ON CONFLICT DO NOTHING""").params(Map.of("id",UUID.randomUUID(),
				"evaluation",evaluationId,"user",user.userId(),"session",request.completedSessionId(),
				"amount",request.amount(),"reason",request.reason(),"key",key,"hash",contentHash)).update();
		if(inserted==0)return replayCommand(user,portfolioId,evaluationId,key,contentHash,
				"app.simulated_portfolio_external_cash_flow_v1");
		return readEvaluation(user.userId(),portfolioId,evaluationId);
	}

	@Transactional
	EvaluationResponse progressMaturity(CurrentUser user,UUID portfolioId,UUID evaluationId,String key,
			ProgressMaturityRequest request) {
		requireKey(key);lockIdempotency(user.userId(),"maturity",key);
		loadEvaluationHeader(user.userId(),portfolioId,evaluationId);
		String contentHash=hash(evaluationId+"|"+request.horizonSessions()+"|"+
				request.completedSessionId()+"|"+(request.terminalReason()==null?"":request.terminalReason()));
		String replay=jdbc.sql("SELECT content_hash FROM app.simulated_portfolio_maturation_command_v1 WHERE user_id=:user AND idempotency_key=:key")
				.params(Map.of("user",user.userId(),"key",key)).query(String.class).optional().orElse(null);
		if(replay!=null){if(!replay.equals(contentHash))throw conflict();return readEvaluation(user.userId(),portfolioId,evaluationId);}
		int inserted=jdbc.sql("""
				INSERT INTO app.simulated_portfolio_maturation_command_v1
				(id,evaluation_id,user_id,horizon_sessions,completed_session_id,terminal_reason,idempotency_key,content_hash)
				VALUES (:id,:evaluation,:user,:horizon,:session,:reason,:key,:hash)
				ON CONFLICT DO NOTHING""").params(Map.ofEntries(
				Map.entry("id",UUID.randomUUID()),Map.entry("evaluation",evaluationId),Map.entry("user",user.userId()),
				Map.entry("horizon",request.horizonSessions()),Map.entry("session",request.completedSessionId()),
				Map.entry("reason",nullable(request.terminalReason())),Map.entry("key",key),Map.entry("hash",contentHash))).update();
		if(inserted==0)return replayCommand(user,portfolioId,evaluationId,key,contentHash,
				"app.simulated_portfolio_maturation_command_v1");
		return readEvaluation(user.userId(),portfolioId,evaluationId);
	}

	@Transactional
	public HumanDecisionResponse decide(CurrentUser user, UUID portfolioId, UUID scenarioId,
			String key, HumanDecisionRequest request) {
		requireKey(key);
		ScenarioResponse scenario = read(user.userId(), portfolioId, scenarioId);
		HumanDecisionResponse replay = findDecisionByKey(user.userId(), key);
		if (replay != null) {
			String expected=hash(request.conclusion()+"|"+request.rationale()+"|"+request.supersedesDecisionId());
			String stored=jdbc.sql("SELECT request_hash FROM app.portfolio_human_decision_v1 WHERE id=:id")
					.param("id",replay.decisionId()).query(String.class).single();
			if (!replay.scenarioId().equals(scenarioId)||!stored.equals(expected)) throw conflict();
			return replay;
		}
		if (scenario.recommendation() == null) throw conflict();
		Instant now = clock.now();
		UUID id = UUID.randomUUID();
		String requestHash = hash(request.conclusion() + "|" + request.rationale() + "|"
				+ request.supersedesDecisionId());
		String contentHash = hash(id + "|" + scenario.recommendation().recommendationId() + "|" + requestHash);
		try {
			jdbc.sql("""
					INSERT INTO app.portfolio_human_decision_v1
					(id,user_id,portfolio_id,recommendation_id,created_by_identity_id,supersedes_decision_id,
					 conclusion,rationale,idempotency_key,request_hash,content_hash,decided_at,recorded_at)
					VALUES (:id,:user,:portfolio,:recommendation,:identity,:supersedes,:conclusion,:rationale,
					 :key,:requestHash,:contentHash,:decidedAt,:recordedAt)
					""").params(Map.ofEntries(Map.entry("id", id), Map.entry("user", user.userId()),
					Map.entry("portfolio", portfolioId), Map.entry("recommendation", scenario.recommendation().recommendationId()),
					Map.entry("identity", user.identityId()), Map.entry("supersedes", nullable(request.supersedesDecisionId())),
					Map.entry("conclusion", request.conclusion().name()), Map.entry("rationale", request.rationale()),
					Map.entry("key", key), Map.entry("requestHash", requestHash), Map.entry("contentHash", contentHash),
					Map.entry("decidedAt", Timestamp.from(now)), Map.entry("recordedAt", Timestamp.from(now))))
					.update();
		}
		catch (RuntimeException exception) {
			throw conflict();
		}
		return new HumanDecisionResponse(id, scenarioId, scenario.recommendation().recommendationId(),
				request.conclusion(), request.rationale(), request.supersedesDecisionId(), now, now);
	}

	private JsonNode command(ContextRow context, PolicyRow policy, CreateScenarioRequest request,
			List<PositionRow> positions, Map<UUID, CandidateInput> candidates) {
		Map<UnifiedPortfolioContracts.SleeveType,BigDecimal> budgetBySleeve=new java.util.EnumMap<>(
				UnifiedPortfolioContracts.SleeveType.class);
		for(SleeveBudgetInput budget:request.sleeveBudgets()) {
			if(budget.sleeve()==UnifiedPortfolioContracts.SleeveType.UNASSIGNED
					|| budget.maximumWeight().compareTo(BigDecimal.ONE)>0
					|| budgetBySleeve.put(budget.sleeve(),budget.maximumWeight())!=null)
				throw invalid("SCENARIO_SLEEVE_BUDGETS_INVALID");
		}
		if(!budgetBySleeve.keySet().equals(Set.of(UnifiedPortfolioContracts.SleeveType.LONG_TERM_CORE,
				UnifiedPortfolioContracts.SleeveType.QUANT_TRADING)))
			throw invalid("SCENARIO_SLEEVE_BUDGETS_INVALID");
		if(budgetBySleeve.get(UnifiedPortfolioContracts.SleeveType.QUANT_TRADING)
				.compareTo(policy.maxSpeculative())>0)throw invalid("SCENARIO_SLEEVE_BUDGET_EXCEEDS_POLICY");
		ObjectNode root = MAPPER.createObjectNode();
		root.put("projectionVersion","portfolio-decision-spring-projection-v1.0.0");
		root.put("contextId",request.contextId().toString());
		root.put("evidenceManifestId",request.evidenceManifestId().toString());
		root.put("constraintPolicyVersionId",request.constraintPolicyVersionId().toString());
		root.put("contractVersion", CONTRACT); root.put("scenarioType", request.scenarioType().name());
		root.put("portfolioContextHash", context.contentHash());
		root.put("constraintPolicyHash", normalizedHash(policy.requestHash())); root.put("currentCash", decimal(context.cash()));
		root.put("liabilityValue", decimal(context.liability())); root.put("newMoneyAmount", decimal(request.newMoneyAmount()));
		ArrayNode positionArray = root.putArray("positions");
		for (PositionRow position : positions) {
			CandidateInput candidate = candidates.get(position.securityId());
			ObjectNode item = positionArray.addObject(); item.put("securityId", position.securityId().toString());
			item.put("ticker", position.ticker()); item.put("sleeve", position.sleeve());
			item.put("sectorCode", position.sector());
			if (position.marketValue() == null) item.putNull("currentMarketValue");
			else item.put("currentMarketValue", decimal(position.marketValue()));
			item.put("priceState", position.state()); item.put("permission", candidate.permission().name());
			item.put("humanApprovedCandidate", candidate.humanApprovedCandidate());
			if (position.modelReferenceId() == null) item.putNull("modelReferenceId");
			else item.put("modelReferenceId", position.modelReferenceId().toString());
			if (candidate.targetMarketValue() == null) item.putNull("targetMarketValue");
			else item.put("targetMarketValue", decimal(candidate.targetMarketValue()));
		}
		ArrayNode budgets = root.putArray("sleeveBudgets");
		budgets.addObject().put("sleeve", "LONG_TERM_CORE").put("maximumWeight",
				decimal(budgetBySleeve.get(UnifiedPortfolioContracts.SleeveType.LONG_TERM_CORE)));
		budgets.addObject().put("sleeve", "QUANT_TRADING").put("maximumWeight",
				decimal(budgetBySleeve.get(UnifiedPortfolioContracts.SleeveType.QUANT_TRADING)));
		ObjectNode constraints = root.putObject("constraints");
		constraints.put("maximumPositionCount", policy.maxCount());
		constraints.put("maximumPositionWeight", decimal(policy.maxPosition()));
		constraints.put("maximumSectorWeight", decimal(policy.maxSector()));
		constraints.put("minimumCashWeight", decimal(policy.minCash()));
		constraints.put("maximumLeverageRatio", decimal(policy.maxLeverage()));
		constraints.put("maximumSpeculativeWeight", decimal(policy.maxSpeculative()));
		root.putObject("costPolicy").put("transactionCostBps", "2").put("slippageBps", "3")
				.put("impactState", "NOT_ESTIMATED").put("taxEstimateState", "NOT_ESTIMATED");
		root.put("taxEstimateState", "NOT_ESTIMATED"); root.putNull("taxEstimateAmount");
		root.putNull("taxLotEvidenceHash");
		sealProjection(root);
		return root;
	}
	static void sealProjection(ObjectNode root){root.remove("projectionHash");root.put("projectionHash","sha256:"+sha256(canonical(root)));}

	private JsonNode validateResult(JsonNode result, ScenarioType type, JsonNode command) {
		if (result == null || !result.isObject() || !fields(result).equals(ROOT_FIELDS)
				|| !RESULT.equals(text(result, "resultVersion")) || !ENGINE.equals(text(result, "engineVersion"))
				|| !CONTRACT.equals(text(result, "contractVersion")) || !type.name().equals(text(result, "scenarioType"))
				|| !text(command, "projectionHash").equals(text(result, "inputContentHash"))
				|| !hashValue(text(result, "contentHash"))
				|| !Set.of("CANDIDATE_FOR_HUMAN_REVIEW", "NO_FEASIBLE_CANDIDATE").contains(text(result, "status"))
				|| !result.path("reasonCodes").isArray() || !result.path("positions").isArray()) throw upstream();
		JsonNode authority = result.path("authority");
		if (!authority.isObject() || !authority.path("candidateForHumanReviewOnly").booleanValue()
				|| authority.path("finalWeightAuthority").booleanValue() || authority.path("orderAuthority").booleanValue()
				|| authority.path("automaticBrokerageExecution").booleanValue()
				|| authority.path("llmDecisionAuthority").booleanValue()
				|| !authority.path("humanDecisionRequired").booleanValue()) throw upstream();
		ObjectNode body = (ObjectNode) result.deepCopy(); body.remove("contentHash");
		if (!text(result, "contentHash").equals("sha256:" + sha256(canonical(body)))) throw upstream();
		Map<String,JsonNode> requested=new HashMap<>();
		for(JsonNode item:command.path("positions"))requested.put(item.path("securityId").asText(),item);
		Set<String> returned=new HashSet<>();
		for(JsonNode item:result.path("positions")) {
			String security=item.path("securityId").asText();JsonNode source=requested.get(security);
			if(source==null||!returned.add(security)
					||!source.path("ticker").asText().equals(item.path("ticker").asText())
					||!source.path("sleeve").asText().equals(item.path("sleeve").asText())
					||!source.path("sectorCode").asText().equals(item.path("sectorCode").asText())
					||!java.util.Objects.equals(source.path("currentMarketValue").textValue(),
							item.path("currentMarketValue").textValue()))throw upstream();
		}
			if("CANDIDATE_FOR_HUMAN_REVIEW".equals(text(result,"status"))) {
				if(!returned.equals(requested.keySet()))throw upstream();
			} else if(!returned.isEmpty())throw upstream();
		return result.deepCopy();
	}

	@Transactional
	private ScenarioResponse persist(CurrentUser user, UUID portfolioId, String key,
			CreateScenarioRequest request, ContextRow context, JsonNode result,
			Map<UUID, CandidateInput> candidates, boolean createRecommendation, Instant frozenCutoff) {
		UUID scenarioId = UUID.randomUUID();
		Instant now = frozenCutoff;
		List<JsonNode> numericPositions = new ArrayList<>();
		for (JsonNode item : result.path("positions")) if (item.path("currentMarketValue").isTextual()
				&& item.path("targetMarketValue").isTextual() && item.path("deltaNotional").isTextual()
				&& item.path("finalAssetWeight").isTextual()) numericPositions.add(item);
		List<String> reasons = new ArrayList<>(); for (JsonNode reason : result.path("reasonCodes")) reasons.add(reason.textValue());
		String state = "NO_FEASIBLE_CANDIDATE".equals(text(result, "status")) ? "INFEASIBLE"
				: result.path("constraintStatus").asText().startsWith("PARTIAL") ? "PARTIAL" : "VALID";
		JsonNode economics=result.path("economics");
		BigDecimal finalCash=economics.isNull()?null:nullableDecimal(economics,"finalCash");
		BigDecimal finalAssets=economics.isNull()?null:nullableDecimal(economics,"finalAssetValue");
		BigDecimal grossTraded=economics.isNull()?null:decimalValue(economics,"grossTradedNotional");
		BigDecimal totalCost=economics.isNull()?null:decimalValue(economics,"estimatedTransactionAndSlippageCost");
		BigDecimal turnover=economics.isNull()?null:decimalValue(economics,"oneWayWeightTurnover");
		String taxState=economics.isNull()?"NOT_ESTIMATED":text(economics,"taxEstimateState");
		jdbc.sql("""
				INSERT INTO app.portfolio_decision_scenario_v1
				(id,user_id,portfolio_id,context_id,evidence_manifest_id,constraint_policy_version_id,created_by_identity_id,
				 scenario_type,scenario_state,economic_policy_version,decision_cutoff,new_money_amount,transaction_cost_bps,
				 slippage_bps,tax_estimate_state,current_cash,liability_value,final_cash,final_asset_value,gross_traded_notional,
				 estimated_total_cost,one_way_turnover,expected_position_count,expected_reason_count,idempotency_key,request_hash,
				 content_hash,recorded_at)
				VALUES (:id,:user,:portfolio,:context,:manifest,:policy,:identity,:type,:state,:economics,:cutoff,:money,
				 2,3,:taxState,:currentCash,:liability,:finalCash,:finalAssets,:grossTraded,:totalCost,:turnover,
				 :positions,:reasons,:key,:requestHash,:contentHash,:recordedAt)
				""").params(Map.ofEntries(Map.entry("id", scenarioId), Map.entry("user", user.userId()),
				Map.entry("portfolio", portfolioId), Map.entry("context", request.contextId()),
				Map.entry("manifest", request.evidenceManifestId()), Map.entry("policy", request.constraintPolicyVersionId()),
				Map.entry("identity", user.identityId()), Map.entry("type", request.scenarioType().name()),
				Map.entry("state", state), Map.entry("economics", ECONOMICS), Map.entry("cutoff", Timestamp.from(now)),
				Map.entry("money", request.newMoneyAmount()), Map.entry("positions", numericPositions.size()),
				Map.entry("taxState",taxState),Map.entry("currentCash",context.cash()),Map.entry("liability",context.liability()),
				Map.entry("finalCash",nullable(finalCash)),Map.entry("finalAssets",nullable(finalAssets)),
				Map.entry("grossTraded",nullable(grossTraded)),Map.entry("totalCost",nullable(totalCost)),
				Map.entry("turnover",nullable(turnover)),
				Map.entry("reasons", reasons.size()), Map.entry("key", key),
				Map.entry("requestHash", text(result, "inputContentHash")), Map.entry("contentHash", text(result, "contentHash")),
				Map.entry("recordedAt", Timestamp.from(now)))).update();
		int ordinal = 0; for (JsonNode item : numericPositions) {
			UUID security = UUID.fromString(text(item, "securityId")); CandidateInput candidate = candidates.get(security);
			BigDecimal delta = decimalValue(item, "deltaNotional");
			BigDecimal rowCost = delta.abs().multiply(BigDecimal.valueOf(5)).divide(BigDecimal.valueOf(10000));
			jdbc.sql("""
					INSERT INTO app.portfolio_scenario_position_v1
					(scenario_id,user_id,ordinal,security_public_id,sleeve_type,current_value,target_value,value_delta,
					 target_weight,permission,estimated_cost,estimated_tax)
					VALUES (:scenario,:user,:ordinal,:security,:sleeve,:current,:target,:delta,:weight,:permission,:cost,NULL)
					""").params(Map.ofEntries(
					Map.entry("scenario", scenarioId), Map.entry("user", user.userId()),
					Map.entry("ordinal", ++ordinal), Map.entry("security", security),
					Map.entry("sleeve", text(item, "sleeve")),
					Map.entry("current", decimalValue(item, "currentMarketValue")),
					Map.entry("target", decimalValue(item, "targetMarketValue")), Map.entry("delta", delta),
					Map.entry("weight", decimalValue(item, "finalAssetWeight")),
					Map.entry("permission", candidate.permission().name()),
					Map.entry("cost", rowCost))).update();
		}
		ordinal=0; for (String reason : reasons) jdbc.sql("INSERT INTO app.portfolio_scenario_reason_v1 VALUES (:s,:u,:o,:r)")
				.params(Map.of("s",scenarioId,"u",user.userId(),"o",++ordinal,"r",reason)).update();
		jdbc.sql("UPDATE app.portfolio_decision_scenario_v1 SET sealed_at=:sealed WHERE id=:id")
				.params(Map.of("sealed",Timestamp.from(now),"id",scenarioId)).update();
		if (!createRecommendation) return null;
		UUID recommendationId=UUID.randomUUID(); String recommendationState = "INFEASIBLE".equals(state)
				? "NO_FEASIBLE_ACTION" : reasons.isEmpty() ? "RECOMMENDATION_AVAILABLE" : "REVIEW_REQUIRED";
		jdbc.sql("""
				INSERT INTO app.portfolio_recommendation_v1
				(id,user_id,portfolio_id,scenario_id,created_by_identity_id,recommendation_version,recommendation_state,
				 idempotency_key,expected_position_count,expected_reason_count,request_hash,content_hash,recorded_at)
				VALUES (:id,:user,:portfolio,:scenario,:identity,:version,:state,:key,:positions,:count,:requestHash,:contentHash,:recordedAt)
				""").params(Map.ofEntries(
				Map.entry("id", recommendationId), Map.entry("user", user.userId()),
				Map.entry("portfolio", portfolioId), Map.entry("scenario", scenarioId),
				Map.entry("identity", user.identityId()), Map.entry("version", RECOMMENDATION),
				Map.entry("state", recommendationState), Map.entry("key", key + ":recommendation"),
				Map.entry("positions", numericPositions.size()),
				Map.entry("count", reasons.size()),
				Map.entry("requestHash", text(result, "inputContentHash")),
				Map.entry("contentHash", hash(recommendationId + "|" + text(result, "contentHash"))),
				Map.entry("recordedAt", Timestamp.from(now)))).update();
		ordinal=0; for(JsonNode item:numericPositions) {
			BigDecimal delta=decimalValue(item,"deltaNotional"); String action=delta.signum()==0?"HOLD":delta.signum()>0?"BUY":"SELL";
			jdbc.sql("""
				INSERT INTO app.portfolio_recommendation_position_v1
				(recommendation_id,user_id,ordinal,scenario_position_ordinal,security_public_id,action,value_delta,
				 target_value,target_weight,estimated_cost,estimated_tax)
				SELECT :r,:u,:o,:o,security_public_id,:action,value_delta,target_value,target_weight,estimated_cost,estimated_tax
				FROM app.portfolio_scenario_position_v1 WHERE scenario_id=:s AND ordinal=:o
				""").params(Map.of("r",recommendationId,"u",user.userId(),"o",++ordinal,"action",action,"s",scenarioId)).update();
		}
		ordinal=0; for(String reason:reasons) jdbc.sql("INSERT INTO app.portfolio_recommendation_reason_v1 VALUES (:r,:u,:o,:c)")
				.params(Map.of("r",recommendationId,"u",user.userId(),"o",++ordinal,"c",reason)).update();
		jdbc.sql("UPDATE app.portfolio_recommendation_v1 SET sealed_at=:sealed WHERE id=:id")
				.params(Map.of("sealed",Timestamp.from(now),"id",recommendationId)).update();
		return read(user.userId(), portfolioId, scenarioId);
	}

	private void createRecommendationAndBinding(CurrentUser user, UUID portfolioId,
			UUID comparisonId, UUID scenarioId, String key) {
		UUID recommendationId=UUID.randomUUID(); Instant now=clock.now();
		String scenarioHash=jdbc.sql("SELECT content_hash FROM app.portfolio_decision_scenario_v1 WHERE id=:id AND user_id=:user")
				.params(Map.of("id",scenarioId,"user",user.userId())).query(String.class).single();
		String state=jdbc.sql("SELECT CASE WHEN scenario_state='INFEASIBLE' THEN 'NO_FEASIBLE_ACTION' ELSE 'RECOMMENDATION_AVAILABLE' END FROM app.portfolio_decision_scenario_v1 WHERE id=:id")
				.param("id",scenarioId).query(String.class).single();
		int positions=jdbc.sql("SELECT count(*) FROM app.portfolio_scenario_position_v1 WHERE scenario_id=:id")
				.param("id",scenarioId).query(Integer.class).single();
		int reasons=jdbc.sql("SELECT count(*) FROM app.portfolio_scenario_reason_v1 WHERE scenario_id=:id")
				.param("id",scenarioId).query(Integer.class).single();
		String recommendationHash=hash(recommendationId+"|"+scenarioHash);
		jdbc.sql("""
				INSERT INTO app.portfolio_recommendation_v1
				(id,user_id,portfolio_id,scenario_id,created_by_identity_id,recommendation_version,recommendation_state,
				 idempotency_key,expected_position_count,expected_reason_count,request_hash,content_hash,recorded_at)
				SELECT :id,:user,:portfolio,id,:identity,:version,:state,:key,:positions,:reasons,request_hash,:hash,:recorded
				FROM app.portfolio_decision_scenario_v1 WHERE id=:scenario
				""").params(Map.ofEntries(Map.entry("id",recommendationId),Map.entry("user",user.userId()),
				Map.entry("portfolio",portfolioId),Map.entry("identity",user.identityId()),Map.entry("version",RECOMMENDATION),
				Map.entry("state",state),Map.entry("key",key),Map.entry("positions",positions),Map.entry("reasons",reasons),
				Map.entry("hash",recommendationHash),Map.entry("recorded",Timestamp.from(now)),Map.entry("scenario",scenarioId))).update();
		jdbc.sql("""
				INSERT INTO app.portfolio_recommendation_position_v1
				(recommendation_id,user_id,ordinal,scenario_position_ordinal,security_public_id,action,value_delta,
				 target_value,target_weight,estimated_cost,estimated_tax)
				SELECT :recommendation,user_id,ordinal,ordinal,security_public_id,
				 CASE WHEN value_delta=0 THEN 'HOLD' WHEN value_delta>0 THEN 'BUY' ELSE 'SELL' END,
				 value_delta,target_value,target_weight,estimated_cost,estimated_tax
				FROM app.portfolio_scenario_position_v1 WHERE scenario_id=:scenario
				""").params(Map.of("recommendation",recommendationId,"scenario",scenarioId)).update();
		jdbc.sql("""
				INSERT INTO app.portfolio_recommendation_reason_v1(recommendation_id,user_id,ordinal,reason_code)
				SELECT :recommendation,user_id,ordinal,reason_code FROM app.portfolio_scenario_reason_v1 WHERE scenario_id=:scenario
				""").params(Map.of("recommendation",recommendationId,"scenario",scenarioId)).update();
		jdbc.sql("UPDATE app.portfolio_recommendation_v1 SET sealed_at=:sealed WHERE id=:id")
				.params(Map.of("sealed",Timestamp.from(now),"id",recommendationId)).update();
		String comparisonHash=jdbc.sql("SELECT content_hash FROM app.portfolio_scenario_comparison_v1 WHERE id=:id")
				.param("id",comparisonId).query(String.class).single();
		String bindingHash=hash(recommendationId+"|"+comparisonId+"|"+scenarioId+"|"+comparisonHash);
		jdbc.sql("""
				INSERT INTO app.portfolio_recommendation_comparison_binding_v1
				(recommendation_id,user_id,comparison_id,selected_scenario_id,binding_hash)
				VALUES (:recommendation,:user,:comparison,:scenario,:hash)
				""").params(Map.of("recommendation",recommendationId,"user",user.userId(),
				"comparison",comparisonId,"scenario",scenarioId,"hash",bindingHash)).update();
	}

	private static String comparisonPayloadHash(CreateScenarioComparisonRequest request) {
		return hash(request.contextId()+"|"+request.evidenceManifestId()+"|"+
				request.constraintPolicyVersionId()+"|"+request.newMoneyAmount()+"|"+
				request.sleeveBudgets()+"|"+request.candidates());
	}

	private static String comparisonRequestHash(UUID id,UUID user,UUID portfolio,UUID context) {
		return hash(id+"|"+user+"|"+portfolio+"|"+context+"|4");
	}

	private ScenarioResponse read(UUID user, UUID portfolio, UUID scenario) {
		ScenarioRoot root = jdbc.sql("""
				SELECT s.context_id,s.evidence_manifest_id,s.scenario_type,s.scenario_state,s.economic_policy_version,
				 s.decision_cutoff,s.new_money_amount,s.transaction_cost_bps,s.slippage_bps,s.tax_estimate_state,
				 s.final_cash,s.final_asset_value,s.gross_traded_notional,s.estimated_total_cost,s.one_way_turnover,
				 s.content_hash,r.id recommendation_id,r.recommendation_state,r.content_hash recommendation_hash
				FROM app.portfolio_decision_scenario_v1 s JOIN app.portfolio_recommendation_v1 r ON r.scenario_id=s.id
				WHERE s.id=:id AND s.user_id=:user AND s.portfolio_id=:portfolio
				AND s.sealed_at IS NOT NULL AND r.sealed_at IS NOT NULL
				""").params(Map.of("id",scenario,"user",user,"portfolio",portfolio)).query((rs,n)->new ScenarioRoot(
				rs.getObject(1,UUID.class),rs.getObject(2,UUID.class),ScenarioType.valueOf(rs.getString(3)),
				rs.getString(4),rs.getString(5),wholeSecond(rs.getTimestamp(6).toInstant()),rs.getBigDecimal(7),
				rs.getBigDecimal(8),rs.getBigDecimal(9),rs.getString(10),rs.getBigDecimal(11),rs.getBigDecimal(12),
				rs.getBigDecimal(13),rs.getBigDecimal(14),rs.getBigDecimal(15),rs.getString(16),
				rs.getObject(17,UUID.class),rs.getString(18),rs.getString(19)))
				.optional().orElseThrow(PortfolioDecisionService::notFound);
		List<DecisionPosition> positions = jdbc.sql("""
				SELECT p.security_public_id,u.ticker,p.sleeve_type,p.current_value,p.target_value,p.value_delta,
				 p.target_weight,p.permission,p.estimated_cost,p.estimated_tax
				FROM app.portfolio_scenario_position_v1 p JOIN app.unified_portfolio_position_v1 u
				 ON u.context_id=:context AND u.user_id=p.user_id AND u.security_public_id=p.security_public_id
				WHERE p.scenario_id=:scenario AND p.user_id=:user ORDER BY p.security_public_id
				""").params(Map.of("context",root.contextId(),"scenario",scenario,"user",user)).query((rs,n)->new DecisionPosition(
				rs.getObject(1,UUID.class),rs.getString(2),rs.getString(3),decimal(rs.getBigDecimal(4)),
				decimal(rs.getBigDecimal(5)),decimal(rs.getBigDecimal(6)),decimal(rs.getBigDecimal(7)),rs.getString(8),
				decimal(rs.getBigDecimal(9)),rs.getBigDecimal(10)==null?null:decimal(rs.getBigDecimal(10)))).list();
		List<DecisionEvidence> evidence = jdbc.sql("""
				SELECT security_public_id,data_state,fundamental_evidence_label,quant_evidence_label
				FROM app.portfolio_context_position_evidence_v1
				WHERE manifest_id=:manifest AND user_id=:user ORDER BY security_public_id
				""").params(Map.of("manifest",root.manifestId(),"user",user)).query((rs,n)->new DecisionEvidence(
				rs.getObject(1,UUID.class),rs.getString(2),rs.getString(3),rs.getString(4))).list();
		List<String> reasons=jdbc.sql("SELECT reason_code FROM app.portfolio_scenario_reason_v1 WHERE scenario_id=:s AND user_id=:u ORDER BY reason_code")
				.params(Map.of("s",scenario,"u",user)).query(String.class).list();
		List<String> recommendationReasons=jdbc.sql("SELECT reason_code FROM app.portfolio_recommendation_reason_v1 WHERE recommendation_id=:r AND user_id=:u ORDER BY reason_code")
				.params(Map.of("r",root.recommendationId(),"u",user)).query(String.class).list();
		HumanDecisionSummary decision=jdbc.sql("""
				SELECT id,conclusion,rationale,decided_at,content_hash FROM app.portfolio_human_decision_v1
				WHERE recommendation_id=:r AND user_id=:u
				 AND NOT EXISTS (SELECT 1 FROM app.portfolio_human_decision_v1 successor
				   WHERE successor.supersedes_decision_id=app.portfolio_human_decision_v1.id)
				ORDER BY decided_at DESC,id LIMIT 1
				""").params(Map.of("r",root.recommendationId(),"u",user)).query((rs,n)->new HumanDecisionSummary(
				rs.getObject(1,UUID.class),Conclusion.valueOf(rs.getString(2)),rs.getString(3),
				wholeSecond(rs.getTimestamp(4).toInstant()),rs.getString(5))).optional().orElse(null);
		BigDecimal buys=positions.stream().map(DecisionPosition::valueDelta).map(BigDecimal::new)
				.filter(v->v.signum()>0).reduce(BigDecimal.ZERO,BigDecimal::add);
		BigDecimal sells=positions.stream().map(DecisionPosition::valueDelta).map(BigDecimal::new)
				.filter(v->v.signum()<0).map(BigDecimal::negate).reduce(BigDecimal.ZERO,BigDecimal::add);
		BigDecimal taxes=positions.stream().map(DecisionPosition::estimatedTax).filter(java.util.Objects::nonNull)
				.map(BigDecimal::new).reduce(BigDecimal.ZERO,BigDecimal::add);
		DecisionEconomics economics=root.finalAssetValue()==null?null:new DecisionEconomics(decimal(root.newMoney()),
				decimal(root.transactionCostBps()),decimal(root.slippageBps()),decimal(buys),decimal(sells),
				decimal(root.grossTraded()),decimal(root.totalCost()),"NOT_ESTIMATED",root.taxState(),
				"AVAILABLE_APPLIED".equals(root.taxState())?decimal(taxes):null,decimal(taxes),decimal(root.turnover()),
				decimal(root.grossTraded().divide(root.finalAssetValue(),java.math.MathContext.DECIMAL128)),
				decimal(root.finalCash()),decimal(root.finalAssetValue()));
		String candidate="INFEASIBLE".equals(root.state())?"NO_FEASIBLE_CANDIDATE":"CANDIDATE_FOR_HUMAN_REVIEW";
		return new ScenarioResponse(scenario,portfolio,root.contextId(),root.type(),root.state(),root.cutoff(),root.economicsVersion(),
				candidate,List.copyOf(evidence),List.copyOf(positions),economics,List.copyOf(reasons),
				new RecommendationSummary(root.recommendationId(),root.recommendationState(),List.copyOf(recommendationReasons),root.recommendationHash()),
				decision,new DecisionAuthority(true,false,false,false,false,true),root.contentHash());
	}

	private ScenarioResponse findByKey(UUID user,UUID portfolio,String key){
		UUID id=jdbc.sql("SELECT id FROM app.portfolio_decision_scenario_v1 WHERE user_id=:u AND portfolio_id=:p AND idempotency_key=:k")
				.params(Map.of("u",user,"p",portfolio,"k",key)).query(UUID.class).optional().orElse(null);
		return id==null?null:read(user,portfolio,id);
	}
	private void lockIdempotency(UUID user, String namespace, String key) {
		jdbc.sql("SELECT true FROM pg_advisory_xact_lock(hashtextextended(:identity, 0))")
				.param("identity", "TASK5|" + namespace + "|" + user + "|" + key)
				.query(Boolean.class).single();
	}
	private EvaluationResponse findEvaluationByKey(UUID user, UUID portfolio, String key) {
		UUID id=jdbc.sql("SELECT id FROM app.simulated_portfolio_evaluation_v1 WHERE user_id=:u AND portfolio_id=:p AND idempotency_key=:k")
				.params(Map.of("u",user,"p",portfolio,"k",key)).query(UUID.class).optional().orElse(null);
		return id==null?null:readEvaluation(user,portfolio,id);
	}
	private EvaluationResponse replayObservation(CurrentUser user,UUID portfolio,UUID evaluation,String key,String expected) {
		String stored=jdbc.sql("SELECT request_hash FROM app.simulated_portfolio_observation_command_v1 WHERE user_id=:user AND idempotency_key=:key AND sealed_at IS NOT NULL")
				.params(Map.of("user",user.userId(),"key",key)).query(String.class).optional().orElseThrow(PortfolioDecisionService::conflict);
		if(!stored.equals(expected))throw conflict();
		return readEvaluation(user.userId(),portfolio,evaluation);
	}
	private EvaluationResponse replayCommand(CurrentUser user,UUID portfolio,UUID evaluation,String key,
			String expected,String table) {
		if(!table.equals("app.simulated_portfolio_external_cash_flow_v1")
				&&!table.equals("app.simulated_portfolio_maturation_command_v1"))throw new IllegalArgumentException("Unsupported replay table");
		String stored=jdbc.sql("SELECT content_hash FROM "+table+" WHERE user_id=:user AND idempotency_key=:key")
				.params(Map.of("user",user.userId(),"key",key)).query(String.class).optional().orElseThrow(PortfolioDecisionService::conflict);
		if(!stored.equals(expected))throw conflict();
		return readEvaluation(user.userId(),portfolio,evaluation);
	}
	private EvaluationResponse readEvaluation(UUID user, UUID portfolio, UUID id) {
		EvaluationHeader header=loadEvaluationHeader(user,portfolio,id);
		List<EvaluationMaturity> maturities=jdbc.sql("""
				SELECT horizon_sessions,effective_state,terminal_reason,observed_at
				FROM app.simulated_portfolio_latest_maturity_v1
				WHERE evaluation_id=:id AND user_id=:user ORDER BY horizon_sessions
				""").params(Map.of("id",id,"user",user)).query((rs,n)->new EvaluationMaturity(
				rs.getInt(1),rs.getString(2),rs.getString(3),
				rs.getTimestamp(4)==null?null:rs.getTimestamp(4).toInstant()
						.truncatedTo(java.time.temporal.ChronoUnit.SECONDS))).list();
		List<EvaluationPeriodSummary> summaries=jdbc.sql("""
				SELECT command.horizon_sessions,summary.period_start,summary.period_end,summary.observation_count,
				 summary.accepted_return,summary.hold_current_return,
				 benchmark_return,accepted_excess_vs_hold,accepted_excess_vs_benchmark,
				 accepted_entry_implementation_cost,derived_total_cost
				FROM app.simulated_portfolio_period_summary_v2 summary
				JOIN app.simulated_portfolio_maturation_command_v1 command ON command.id=summary.maturation_command_id
				WHERE summary.evaluation_id=:id AND summary.user_id=:user ORDER BY command.horizon_sessions
				""").params(Map.of("id",id,"user",user)).query((rs,n)->new EvaluationPeriodSummary(
				rs.getInt(1),rs.getObject(2,java.time.LocalDate.class).toString(),rs.getObject(3,java.time.LocalDate.class).toString(),
				rs.getInt(1)+1,rs.getInt(4),null,decimal(rs.getBigDecimal(5)),
				decimal(rs.getBigDecimal(7)),decimal(rs.getBigDecimal(9)),decimal(rs.getBigDecimal(6)),
				decimal(rs.getBigDecimal(8)),null,"0",decimal(rs.getBigDecimal(11)),"1")).list();
		String state=maturities.stream().allMatch(value->"AWAITING_NATURAL_MATURITY".equals(value.state()))
				?"AWAITING_NATURAL_MATURITY":maturities.stream().allMatch(value->!"AWAITING_NATURAL_MATURITY".equals(value.state()))
				?"MATURED":"PARTIALLY_MATURED";
		return new EvaluationResponse(header.id(),header.portfolioId(),header.humanDecisionId(),header.startingContextId(),
				header.acceptedScenarioId(),header.holdScenarioId(),state,header.benchmarkCode(),
				header.simulatedOnly(),List.copyOf(maturities),
				List.copyOf(summaries),header.recordedAt());
	}
	private EvaluationHeader loadEvaluationHeader(UUID user,UUID portfolio,UUID id){return jdbc.sql("""
				SELECT id,portfolio_id,human_decision_id,starting_context_id,accepted_scenario_id,
				 hold_current_scenario_id,
				 benchmark_code,simulated_only,recorded_at
				FROM app.simulated_portfolio_evaluation_v1
				WHERE id=:id AND user_id=:user AND portfolio_id=:portfolio AND sealed_at IS NOT NULL
				""").params(Map.of("id",id,"user",user,"portfolio",portfolio)).query((rs,n)->new EvaluationHeader(
				rs.getObject(1,UUID.class),rs.getObject(2,UUID.class),rs.getObject(3,UUID.class),
				rs.getObject(4,UUID.class),rs.getObject(5,UUID.class),rs.getObject(6,UUID.class),
				rs.getString(7),rs.getBoolean(8),rs.getTimestamp(9).toInstant()
						.truncatedTo(java.time.temporal.ChronoUnit.SECONDS)))
				.optional().orElseThrow(PortfolioDecisionService::notFound);}
	private void requireEvaluationScenario(UUID user, UUID scenario, UUID decision) {
		int count=jdbc.sql("""
				SELECT count(*) FROM app.portfolio_human_decision_v1 d
				JOIN app.portfolio_recommendation_v1 r ON r.id=d.recommendation_id AND r.user_id=d.user_id
				WHERE d.id=:decision AND d.user_id=:user AND r.scenario_id=:scenario
				""").params(Map.of("decision",decision,"user",user,"scenario",scenario)).query(Integer.class).single();
		if(count!=1)throw notFound();
	}
	private void createOpeningLedger(UUID evaluation,UUID user,UUID context,UUID acceptedScenario,
			UUID holdScenario,UUID session) {
		List<OpeningSource> accepted=jdbc.sql("""
				SELECT security_public_id,target_value
				FROM app.portfolio_scenario_position_v1 WHERE scenario_id=:scenario ORDER BY ordinal""")
				.param("scenario",acceptedScenario).query((rs,n)->new OpeningSource(
					rs.getObject(1,UUID.class),rs.getBigDecimal(2))).list();
		List<OpeningSource> hold=jdbc.sql("""
				SELECT position.security_public_id,sum(position.quantity)
				FROM app.unified_portfolio_account_binding_v1 binding JOIN app.position_snapshot position
				 ON position.snapshot_id=binding.account_snapshot_id AND position.user_id=binding.user_id
				WHERE binding.context_id=:context GROUP BY position.security_public_id ORDER BY position.security_public_id""")
				.param("context",context).query((rs,n)->new OpeningSource(rs.getObject(1,UUID.class),rs.getBigDecimal(2))).list();
		BigDecimal commonBase=jdbc.sql("""
				SELECT context.invested_value+context.cash_value+scenario.new_money_amount
				FROM app.unified_portfolio_context_v1 context
				JOIN app.portfolio_decision_scenario_v1 scenario ON scenario.id=:scenario
				WHERE context.id=:context
				""").params(Map.of("context",context,"scenario",acceptedScenario))
				.query(BigDecimal.class).single();
		BigDecimal acceptedCost=jdbc.sql("SELECT estimated_total_cost FROM app.portfolio_decision_scenario_v1 WHERE id=:id")
				.param("id",acceptedScenario).query(BigDecimal.class).single();
		jdbc.sql("""
				INSERT INTO app.simulated_portfolio_evaluation_v31_contract_v1
				(evaluation_id,user_id,expected_accepted_positions,expected_hold_positions,common_capital_base,
				 accepted_entry_implementation_cost,hold_entry_implementation_cost,contract_version)
				VALUES (:evaluation,:user,:accepted,:hold,:base,:cost,0,'simulated-portfolio-evaluation-v1.1.0')""")
				.params(Map.of("evaluation",evaluation,"user",user,"accepted",accepted.size(),"hold",hold.size(),
						"base",commonBase,"cost",acceptedCost)).update();
		insertOpeningPositions(evaluation,user,"ACCEPTED",session,accepted,true);
		insertOpeningPositions(evaluation,user,"HOLD_CURRENT",session,hold,false);
		BigDecimal acceptedCash=jdbc.sql("SELECT final_cash FROM app.portfolio_decision_scenario_v1 WHERE id=:id")
				.param("id",acceptedScenario).query(BigDecimal.class).single();
		BigDecimal holdCash=jdbc.sql("SELECT current_cash+new_money_amount FROM app.portfolio_decision_scenario_v1 WHERE id=:id")
				.param("id",holdScenario).query(BigDecimal.class).single();
		for(var laneCash:List.of(Map.entry("ACCEPTED",acceptedCash),Map.entry("HOLD_CURRENT",holdCash)))
			jdbc.sql("INSERT INTO app.simulated_portfolio_opening_cash_v1(evaluation_id,user_id,lane_type,cash_value) VALUES (:evaluation,:user,:lane,:cash)")
				.params(Map.of("evaluation",evaluation,"user",user,"lane",laneCash.getKey(),"cash",laneCash.getValue())).update();
	}
	private void insertOpeningPositions(UUID evaluation,UUID user,String lane,UUID session,
			List<OpeningSource> sources,boolean targetValue) {
		int ordinal=0;
		for(OpeningSource source:sources) {
			SelectorRow selector=loadUniqueSelector(source.securityId(),session);
			BigDecimal quantity=targetValue?jdbc.sql("SELECT :value::numeric/:price::numeric")
					.params(Map.of("value",source.value(),"price",selector.price())).query(BigDecimal.class).single():source.value();
			jdbc.sql("""
					INSERT INTO app.simulated_portfolio_opening_position_v1
					(evaluation_id,user_id,lane_type,ordinal,security_public_id,quantity,
					 entry_selection_request_id,entry_selection_result_hash,entry_price)
					VALUES (:evaluation,:user,:lane,:ordinal,:security,:quantity,:request,:hash,:price)""")
					.params(Map.ofEntries(Map.entry("evaluation",evaluation),Map.entry("user",user),Map.entry("lane",lane),
							Map.entry("ordinal",++ordinal),Map.entry("security",source.securityId()),Map.entry("quantity",quantity),
							Map.entry("request",selector.requestId()),Map.entry("hash",selector.resultHash()),Map.entry("price",selector.price()))).update();
		}
	}
	private SelectorRow loadUniqueSelector(UUID security,UUID session) {
		List<SelectorRow> rows=jdbc.sql("""
				SELECT q.request_id,r.result_content_hash,
				app.task5_v31_selector_price_v1(q.request_id,q.security_id,q.completed_session_id)
				FROM analytics.evidence_selection_request_v1 q JOIN analytics.evidence_selection_result_v1 r ON r.request_id=q.request_id
				JOIN analytics.evidence_selection_seal_v1 seal ON seal.request_id=q.request_id
				WHERE q.security_id=:security AND q.completed_session_id=:session AND r.state='VALID'""")
				.params(Map.of("security",security,"session",session)).query((rs,n)->new SelectorRow(
					rs.getObject(1,UUID.class),rs.getString(2),rs.getBigDecimal(3))).list();
		if(rows.size()!=1)throw invalid("ENTRY_PRICE_SELECTOR_CARDINALITY_INVALID");return rows.get(0);
	}
	private void insertObservationSelectors(UUID commandId,UUID user,String lane,
			List<ObservationSelectorInput> selectors) {
		Set<UUID> securities=new HashSet<>();int ordinal=0;
		for(ObservationSelectorInput selector:selectors) {
			if(!securities.add(selector.securityId()))throw invalid("DUPLICATE_OBSERVATION_SECURITY");
			String resultHash=jdbc.sql("SELECT result_content_hash FROM analytics.evidence_selection_result_v1 WHERE request_id=:id AND state='VALID'")
					.param("id",selector.selectionRequestId()).query(String.class).optional()
					.orElseThrow(PortfolioDecisionService::notFound);
			jdbc.sql("""
					INSERT INTO app.simulated_portfolio_observation_selector_v1
					(command_id,user_id,lane_type,ordinal,security_public_id,selection_request_id,selection_result_hash)
					VALUES (:command,:user,:lane,:ordinal,:security,:request,:hash)""")
					.params(Map.of("command",commandId,"user",user,"lane",lane,"ordinal",++ordinal,
							"security",selector.securityId(),"request",selector.selectionRequestId(),"hash",resultHash)).update();
		}
	}
	private HumanDecisionResponse findDecisionByKey(UUID user,String key){
		return jdbc.sql("""
				SELECT d.id,d.recommendation_id,d.conclusion,d.rationale,d.supersedes_decision_id,d.decided_at,d.recorded_at,r.scenario_id
				FROM app.portfolio_human_decision_v1 d JOIN app.portfolio_recommendation_v1 r ON r.id=d.recommendation_id
				WHERE d.user_id=:u AND d.idempotency_key=:k""").params(Map.of("u",user,"k",key)).query((rs,n)->new HumanDecisionResponse(
				rs.getObject("id",UUID.class),rs.getObject("scenario_id",UUID.class),rs.getObject("recommendation_id",UUID.class),
				Conclusion.valueOf(rs.getString("conclusion")),rs.getString("rationale"),rs.getObject("supersedes_decision_id",UUID.class),
				wholeSecond(rs.getTimestamp("decided_at").toInstant()),
				wholeSecond(rs.getTimestamp("recorded_at").toInstant()))).optional().orElse(null);
	}
	private static Instant wholeSecond(Instant value) {
		return value.truncatedTo(java.time.temporal.ChronoUnit.SECONDS);
	}

	private ContextRow loadContext(UUID user,UUID portfolio,UUID id){return jdbc.sql("""
		SELECT content_hash,cash_value,liability_value FROM app.unified_portfolio_context_v1
		WHERE id=:id AND user_id=:u AND portfolio_id=:p AND sealed_at IS NOT NULL""").params(Map.of("id",id,"u",user,"p",portfolio))
			.query((rs,n)->new ContextRow(rs.getString(1),rs.getBigDecimal(2),rs.getBigDecimal(3))).optional().orElseThrow(PortfolioDecisionService::notFound);}
	private PolicyRow loadPolicy(UUID user,UUID portfolio,UUID id){return jdbc.sql("""
		SELECT maximum_position_count,maximum_position_weight,maximum_sector_weight,minimum_cash_weight,
		 maximum_leverage_ratio,maximum_speculative_weight,request_hash FROM app.constraint_policy_version
		WHERE id=:id AND user_id=:u AND scope_type='PORTFOLIO' AND portfolio_id=:p""").params(Map.of("id",id,"u",user,"p",portfolio))
			.query((rs,n)->new PolicyRow(required(rs.getObject(1,Integer.class)),required(rs.getBigDecimal(2)),required(rs.getBigDecimal(3)),
				required(rs.getBigDecimal(4)),required(rs.getBigDecimal(5)),required(rs.getBigDecimal(6)),rs.getString(7)))
			.optional().orElseThrow(PortfolioDecisionService::notFound);}
	private void requireManifest(UUID user,UUID portfolio,UUID context,UUID manifest){int n=jdbc.sql("""
		SELECT count(*) FROM app.portfolio_context_evidence_manifest_v1 WHERE id=:id AND user_id=:u AND portfolio_id=:p
		AND context_id=:c AND sealed_at IS NOT NULL""").params(Map.of("id",manifest,"u",user,"p",portfolio,"c",context)).query(Integer.class).single();if(n!=1)throw notFound();}
	private List<PositionRow> loadPositions(UUID user,UUID context,UUID manifest){return jdbc.sql("""
		SELECT p.security_public_id,p.ticker,p.sleeve_type,p.sector_code,p.data_state,p.market_value,
		 CASE WHEN p.sleeve_type='LONG_TERM_CORE' THEN e.fundamental_assessment_id
		      WHEN p.sleeve_type='QUANT_TRADING' THEN e.quant_decision_id ELSE NULL END model_reference_id
		FROM app.unified_portfolio_position_v1 p LEFT JOIN app.unified_portfolio_sleeve_v1 s
		 ON s.context_id=p.context_id AND s.user_id=p.user_id AND s.sleeve_type=p.sleeve_type
		JOIN app.portfolio_context_evidence_manifest_v1 m ON m.id=:m AND m.context_id=p.context_id
		 AND m.user_id=p.user_id AND m.sealed_at IS NOT NULL
		LEFT JOIN app.portfolio_context_position_evidence_v1 e ON e.manifest_id=m.id AND e.user_id=p.user_id AND e.security_public_id=p.security_public_id
		WHERE p.context_id=:c AND p.user_id=:u ORDER BY p.security_public_id""")
		.params(Map.of("c",context,"u",user,"m",manifest)).query((rs,n)->new PositionRow(
			rs.getObject(1,UUID.class),rs.getString(2),rs.getString(3),rs.getString(4),rs.getString(5),rs.getBigDecimal(6),
			rs.getObject(7,UUID.class))).list();}
	private Map<UUID,CandidateInput> candidates(CreateScenarioRequest request,List<PositionRow> positions){Map<UUID,CandidateInput> result=new HashMap<>();
		for(CandidateInput item:request.candidates())if(result.put(item.securityId(),item)!=null)throw invalid("DUPLICATE_SCENARIO_CANDIDATE");
		Set<UUID> expected=new HashSet<>();for(PositionRow p:positions)expected.add(p.securityId());if(!result.keySet().equals(expected))throw invalid("SCENARIO_SECURITY_SET_MISMATCH");
		boolean targets=request.scenarioType()==ScenarioType.CONSTRAINED_REBALANCE||request.scenarioType()==ScenarioType.TARGET_PORTFOLIO;
		for(CandidateInput item:result.values())if(targets!=(item.targetMarketValue()!=null))throw invalid("SCENARIO_TARGET_SEMANTICS_INVALID");return result;}

	private static Set<String> fields(JsonNode node){return new HashSet<>(node.propertyNames());}
	private static String text(JsonNode n,String f){JsonNode v=n.get(f);if(v==null||!v.isTextual())throw upstream();return v.textValue();}
	private static BigDecimal decimalValue(JsonNode n,String f){try{return new BigDecimal(text(n,f));}catch(RuntimeException e){throw upstream();}}
	private static BigDecimal nullableDecimal(JsonNode n,String f){JsonNode value=n.get(f);return value==null||value.isNull()?null:decimalValue(n,f);}
	private static String decimal(BigDecimal v){return v.stripTrailingZeros().toPlainString();}
	private static String decimalOrNull(BigDecimal v){return v==null?null:decimal(v);}
	private static boolean hashValue(String v){return v!=null&&v.matches("sha256:[0-9a-f]{64}");}
	private static String normalizedHash(String value){return hashValue(value)?value:hash(value);}
	private static String hash(Object value){return "sha256:"+sha256(String.valueOf(value).getBytes(StandardCharsets.UTF_8));}
	private static String sha256(byte[] value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value));}catch(NoSuchAlgorithmException e){throw new IllegalStateException(e);}}
	private static byte[] canonical(JsonNode value){try{return MAPPER.writeValueAsString(sorted(value)).getBytes(StandardCharsets.UTF_8);}catch(RuntimeException e){throw upstream();}}
	private static Object sorted(JsonNode n){if(n.isObject()){var m=new TreeMap<String,Object>();n.properties().forEach(e->m.put(e.getKey(),sorted(e.getValue())));return m;}if(n.isArray()){var a=new ArrayList<>();for(JsonNode c:n)a.add(sorted(c));return a;}if(n.isTextual())return n.textValue();if(n.isBoolean())return n.booleanValue();if(n.isIntegralNumber())return n.bigIntegerValue();if(n.isNull())return null;throw upstream();}
	private static void requireKey(String key){if(key==null||key.isBlank()||key.length()>128)throw invalid("IDEMPOTENCY_KEY_INVALID");}
	private static <T>T required(T value){if(value==null)throw invalid("PORTFOLIO_CONSTRAINT_POLICY_INCOMPLETE");return value;}
	private static Object nullable(Object value){return value==null?new org.springframework.jdbc.core.SqlParameterValue(java.sql.Types.NULL,null):value;}
	private static PortfolioContextException invalid(String code){return new PortfolioContextException(code,"The portfolio scenario request is invalid.",400);}
	private static PortfolioContextException notFound(){return new PortfolioContextException("PORTFOLIO_DECISION_NOT_FOUND","The requested portfolio decision resource was not found.",404);}
	private static PortfolioContextException conflict(){return new PortfolioContextException("PORTFOLIO_DECISION_CONFLICT","The portfolio decision conflicts with immutable state.",409);}
	private static PortfolioContextException upstream(){return new PortfolioContextException("INVALID_PORTFOLIO_SCENARIO_RESULT","The analytics service returned an invalid portfolio scenario result.",502);}
	private record ContextRow(String contentHash,BigDecimal cash,BigDecimal liability){}
	private record PolicyRow(int maxCount,BigDecimal maxPosition,BigDecimal maxSector,BigDecimal minCash,BigDecimal maxLeverage,BigDecimal maxSpeculative,String requestHash){}
	private record PositionRow(UUID securityId,String ticker,String sleeve,String sector,String state,BigDecimal marketValue,UUID modelReferenceId){}
	private record SessionRow(UUID id,java.time.LocalDate sessionDate,String calendarId,String calendarVersion,
			String contentHash){}
	private record ScenarioRoot(UUID contextId,UUID manifestId,ScenarioType type,String state,String economicsVersion,
			Instant cutoff,BigDecimal newMoney,BigDecimal transactionCostBps,BigDecimal slippageBps,String taxState,
			BigDecimal finalCash,BigDecimal finalAssetValue,BigDecimal grossTraded,BigDecimal totalCost,BigDecimal turnover,
			String contentHash,UUID recommendationId,String recommendationState,String recommendationHash){}
	private record ComparisonRoot(UUID id,UUID contextId,int expectedCount,String contentHash,Instant sealedAt){}
	private record ScenarioProjectionRoot(ScenarioType type,String state,String contentHash,BigDecimal newMoney,
			BigDecimal transactionCostBps,BigDecimal slippageBps,String taxState,BigDecimal currentCash,
			BigDecimal finalCash,BigDecimal finalAssetValue,BigDecimal grossTraded,BigDecimal totalCost,
			BigDecimal turnover,BigDecimal currentInvested){}
	private record EvaluationHeader(UUID id,UUID portfolioId,UUID humanDecisionId,UUID startingContextId,
			UUID acceptedScenarioId,UUID holdScenarioId,String benchmarkCode,boolean simulatedOnly,
			Instant recordedAt){}
	private record OpeningSource(UUID securityId,BigDecimal value){}
	private record SelectorRow(UUID requestId,String resultHash,BigDecimal price){}
}
