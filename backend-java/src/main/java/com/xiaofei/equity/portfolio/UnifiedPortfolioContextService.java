package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.UnifiedPortfolioContracts.*;

import java.nio.charset.StandardCharsets;
import java.math.BigDecimal;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import com.xiaofei.equity.usercontext.CurrentUser;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;
import tools.jackson.databind.json.JsonMapper;

@Service
public class UnifiedPortfolioContextService {
	private static final JsonMapper MAPPER = JsonMapper.builder().build();
	private static final Set<String> ROOT_FIELDS = Set.of(
			"resultVersion", "calculationVersion", "asOfTime", "baseCurrency", "state",
			"totals", "positions", "sectors", "sleeves", "constraints", "risk", "authority", "contentHash");
	private static final Set<String> AUTHORITY_FIELDS = Set.of(
			"finalWeightAuthority", "orderAuthority", "automaticBrokerageExecution",
			"llmDecisionAuthority", "humanDecisionRequired");
	private static final Set<String> CONSTRAINT_FIELDS = Set.of(
			"maximumPositionWeight", "maximumSectorWeight", "minimumCashWeight",
			"maximumLeverageRatio");
	private static final Set<String> TOTAL_FIELDS = Set.of(
			"cashValue", "investedValue", "assetValue", "liabilityValue",
			"netPortfolioValue", "cashWeight", "leverageRatio");
	private static final Set<String> POSITION_FIELDS = Set.of(
			"securityId", "ticker", "sleeve", "sectorCode", "dataState", "marketValue", "assetWeight");
	private static final Set<String> SECTOR_FIELDS = Set.of("sectorCode", "marketValue", "assetWeight");
	private static final Set<String> SLEEVE_FIELDS = Set.of(
			"sleeve", "marketValue", "assetWeight", "positionCount", "modelVersion",
			"modelEvidenceLabel", "researchUseAllowed", "evidenceReferenceId", "evidenceReferenceHash");
	private static final Set<String> RISK_FIELDS = Set.of("status", "reasonCodes", "constraintVersion");
	private static final java.util.regex.Pattern DECIMAL = java.util.regex.Pattern.compile(
			"-?(0|[1-9][0-9]*)(\\.[0-9]+)?");
	private static final java.util.regex.Pattern HASH = java.util.regex.Pattern.compile("sha256:[0-9a-f]{64}");

	private final JdbcClient jdbcClient;
	private final UnifiedPortfolioAnalyticsClient analyticsClient;

	public UnifiedPortfolioContextService(
			JdbcClient jdbcClient, UnifiedPortfolioAnalyticsClient analyticsClient) {
		this.jdbcClient = jdbcClient;
		this.analyticsClient = analyticsClient;
	}

	@Transactional
	public ContextResponse create(
			CurrentUser user, UUID portfolioId, String idempotencyKey, CreateContextRequest request) {
		requireIdempotency(idempotencyKey);
		requirePortfolio(user.userId(), portfolioId);
		validateAccountSnapshots(user.userId(), portfolioId, request.accountSnapshotIds(), request.riskInput());
		validateConstraintPolicy(user.userId(), portfolioId, request.constraintPolicyVersionId(),
				request.riskInput());
		String requestHash = sha256(canonical(MAPPER.valueToTree(request)));
		ContextResponse replay = findByIdempotency(user.userId(), idempotencyKey, requestHash);
		if (replay != null) return replay;
		JsonNode result = analyticsClient.evaluate(request.riskInput());
		validateResult(result, request.riskInput());
		UUID contextId = UUID.randomUUID();
		Instant recordedAt = Instant.now().truncatedTo(java.time.temporal.ChronoUnit.SECONDS);
		insertHeader(user, portfolioId, contextId, idempotencyKey, requestHash, result, recordedAt,
				request.accountSnapshotIds().size(), request.constraintPolicyVersionId());
		insertBindings(user.userId(), contextId, request.accountSnapshotIds());
		insertPositions(user.userId(), contextId, result.path("positions"));
		insertSleeves(user.userId(), contextId, result.path("sleeves"));
		insertReasons(user.userId(), contextId, result.path("risk").path("reasonCodes"));
		jdbcClient.sql("""
				UPDATE app.unified_portfolio_context_v1 SET sealed_at = CURRENT_TIMESTAMP
				WHERE id = :id AND user_id = :userId AND sealed_at IS NULL
				""").params(Map.of("id", contextId, "userId", user.userId())).update();
		return new ContextResponse(contextId, portfolioId, result, null, recordedAt.toString());
	}

	@Transactional
	public CurrentEvidenceContextResponse createCurrentEvidence(CurrentUser user,UUID portfolioId,String idempotencyKey,
			CreateCurrentEvidenceContextRequest request) {
		requireIdempotency(idempotencyKey); requirePortfolio(user.userId(),portfolioId);
		String requestHash=sha256(canonical(MAPPER.valueToTree(request)));
		CurrentEvidenceContextResponse replay=findCurrentEvidenceByIdempotency(
				user,portfolioId,idempotencyKey+":manifest",requestHash);
		if(replay!=null)return replay;
		if(request.accountSnapshotIds().size()!=new HashSet<>(request.accountSnapshotIds()).size())
			throw validation("DUPLICATE_ACCOUNT_SNAPSHOT");
		Map<UUID,CurrentEvidenceReference> references=new java.util.HashMap<>();
		for(CurrentEvidenceReference reference:request.evidenceReferences()) {
			if(references.put(reference.securityId(),reference)!=null)throw validation("DUPLICATE_EVIDENCE_REFERENCE");
			if((reference.sleeve()==SleeveType.UNASSIGNED)!=(reference.modelReferenceId()==null))
				throw validation("MODEL_REFERENCE_SEMANTICS_INVALID");
		}
		CurrentAssemblySource source=currentAssemblySource(user.userId(),portfolioId,request, references);
		JsonNode assembled=analyticsClient.assembleCurrentEvidence(source.command());
		JsonNode manifest=assembled.path("evidenceManifest"),risk=assembled.path("riskContext");
		if(!manifest.isObject()||!risk.isObject()||!HASH.matcher(manifest.path("manifestHash").asText()).matches())
			throw new PortfolioContextException("INVALID_CURRENT_PORTFOLIO_EVIDENCE_RESULT","Analytics returned invalid current evidence.",502);
		RiskInput trusted=MAPPER.convertValue(source.commandRiskInput(risk),RiskInput.class);
		CreateContextRequest trustedRequest=new CreateContextRequest(request.accountSnapshotIds(),request.constraintPolicyVersionId(),trusted);
		ContextResponse context=create(user,portfolioId,idempotencyKey+":context",trustedRequest);
		UUID manifestId=persistEvidenceManifest(user,portfolioId,context.contextId(),
				idempotencyKey+":manifest",requestHash,manifest);
		return new CurrentEvidenceContextResponse(context,manifestId,manifest.path("manifestHash").asText());
	}

	public ContextResponse latest(CurrentUser user, UUID portfolioId) {
		requirePortfolio(user.userId(), portfolioId);
		return jdbcClient.sql("""
				SELECT context.id,context.portfolio_id,context.public_payload::text,context.recorded_at,
				       review.id,review.conclusion,review.rationale,review.content_hash,review.reviewed_at
				FROM app.unified_portfolio_context_v1 context
				LEFT JOIN app.unified_portfolio_review_v1 review
				  ON review.context_id=context.id AND review.user_id=context.user_id
				WHERE context.user_id = :userId AND context.portfolio_id = :portfolioId
				  AND context.sealed_at IS NOT NULL
				ORDER BY context.as_of_time DESC, context.recorded_at DESC, context.id DESC LIMIT 1
				""").params(Map.of("userId", user.userId(), "portfolioId", portfolioId))
				.query((rs, row) -> response(rs.getObject(1, UUID.class), rs.getObject(2, UUID.class),
						rs.getString(3), rs.getTimestamp(4).toInstant(), rs.getObject(5, UUID.class),
						rs.getString(6), rs.getString(7), rs.getString(8), rs.getTimestamp(9)))
						.optional().orElseThrow(this::notFound);
	}

	public ContextResponse get(CurrentUser user, UUID portfolioId, UUID contextId) {
		return jdbcClient.sql("""
				SELECT context.id,context.portfolio_id,context.public_payload::text,context.recorded_at,
				       review.id,review.conclusion,review.rationale,review.content_hash,review.reviewed_at
				FROM app.unified_portfolio_context_v1 context
				LEFT JOIN app.unified_portfolio_review_v1 review
				  ON review.context_id=context.id AND review.user_id=context.user_id
				WHERE context.id = :id AND context.user_id = :userId
				  AND context.portfolio_id = :portfolioId AND context.sealed_at IS NOT NULL
				""").params(Map.of("id", contextId, "userId", user.userId(), "portfolioId", portfolioId))
				.query((rs, row) -> response(rs.getObject(1, UUID.class), rs.getObject(2, UUID.class),
						rs.getString(3), rs.getTimestamp(4).toInstant(), rs.getObject(5, UUID.class),
						rs.getString(6), rs.getString(7), rs.getString(8), rs.getTimestamp(9)))
						.optional().orElseThrow(this::notFound);
	}

	@Transactional
	public ReviewResponse review(CurrentUser user, UUID portfolioId, UUID contextId,
			String idempotencyKey, ReviewRequest request) {
		requireIdempotency(idempotencyKey);
		ContextResponse context = get(user, portfolioId, contextId);
		String requestHash = sha256(canonical(MAPPER.valueToTree(Map.of(
				"contextId", contextId.toString(), "conclusion", request.conclusion().name(),
				"rationale", request.rationale()))));
		ReviewResponse replay = findReviewByIdempotency(user.userId(), idempotencyKey, requestHash);
		if (replay != null) return replay;
		UUID reviewId = UUID.randomUUID();
		Instant reviewedAt = Instant.now().truncatedTo(java.time.temporal.ChronoUnit.SECONDS);
		String contentHash = sha256(canonical(MAPPER.valueToTree(Map.of(
				"contextId", contextId.toString(), "contextContentHash",
				context.riskContext().path("contentHash").textValue(),
				"conclusion", request.conclusion().name(), "rationale", request.rationale(),
				"reviewedAt", reviewedAt.toString()))));
		try {
			jdbcClient.sql("""
					INSERT INTO app.unified_portfolio_review_v1
					(id,user_id,context_id,created_by_identity_id,conclusion,rationale,idempotency_key,
					 request_hash,content_hash,reviewed_at,recorded_at)
					VALUES (:id,:userId,:context,:identity,:conclusion,:rationale,:key,:requestHash,
					 :contentHash,:reviewedAt,:reviewedAt)
					""").params(Map.ofEntries(Map.entry("id", reviewId), Map.entry("userId", user.userId()),
					Map.entry("context", contextId), Map.entry("identity", user.identityId()),
					Map.entry("conclusion", request.conclusion().name()),
					Map.entry("rationale", request.rationale()), Map.entry("key", idempotencyKey),
					Map.entry("requestHash", requestHash), Map.entry("contentHash", contentHash),
					Map.entry("reviewedAt", Timestamp.from(reviewedAt)))).update();
		} catch (org.springframework.dao.DataIntegrityViolationException error) {
			throw new PortfolioContextException("PORTFOLIO_CONTEXT_REVIEW_CONFLICT",
					"The portfolio context already has a different human review.", 409);
		}
		return new ReviewResponse(reviewId, contextId, request.conclusion(), request.rationale(),
				contentHash, reviewedAt.toString(), reviewedAt.toString());
	}

	private void insertHeader(CurrentUser user, UUID portfolioId, UUID contextId,
			String key, String requestHash, JsonNode result, Instant recordedAt, int accountCount,
			UUID constraintPolicyVersionId) {
		JsonNode totals = result.path("totals");
		JsonNode constraints = result.path("constraints");
		jdbcClient.sql("""
				INSERT INTO app.unified_portfolio_context_v1 (
				 id,user_id,portfolio_id,created_by_identity_id,constraint_policy_version_id,
				 contract_version,calculation_version,
				 as_of_time,base_currency,context_state,risk_status,cash_value,invested_value,
				 asset_value,liability_value,net_portfolio_value,cash_weight,leverage_ratio,
				 maximum_position_weight,maximum_sector_weight,minimum_cash_weight,maximum_leverage_ratio,
				 account_binding_count,position_count,risk_reason_count,idempotency_key,
				 source_request_hash,content_hash,public_payload,recorded_at
				) VALUES (
				 :id,:userId,:portfolioId,:identityId,:policyId,:contract,:calculation,CAST(:asOf AS timestamptz),
				 'USD',:state,:risk,:cash,:invested,:assets,:liability,:net,:cashWeight,:leverage,
				 :maxPosition,:maxSector,:minCash,:maxLeverage,
				 :accounts,:positions,:reasons,:key,:requestHash,:contentHash,CAST(:payload AS jsonb),:recordedAt
				)
				""").params(Map.ofEntries(
				Map.entry("id", contextId), Map.entry("userId", user.userId()),
				Map.entry("portfolioId", portfolioId), Map.entry("identityId", user.identityId()),
				Map.entry("policyId", constraintPolicyVersionId),
				Map.entry("contract", result.path("resultVersion").textValue()),
				Map.entry("calculation", result.path("calculationVersion").textValue()),
				Map.entry("asOf", result.path("asOfTime").textValue()),
				Map.entry("state", result.path("state").textValue()),
				Map.entry("risk", result.path("risk").path("status").textValue()),
				Map.entry("cash", decimal(totals, "cashValue")),
				Map.entry("invested", decimal(totals, "investedValue")),
				Map.entry("assets", decimal(totals, "assetValue")),
				Map.entry("liability", decimal(totals, "liabilityValue")),
				Map.entry("net", decimal(totals, "netPortfolioValue")),
				Map.entry("cashWeight", decimal(totals, "cashWeight")),
				Map.entry("leverage", decimal(totals, "leverageRatio")),
				Map.entry("maxPosition", decimal(constraints, "maximumPositionWeight")),
				Map.entry("maxSector", decimal(constraints, "maximumSectorWeight")),
				Map.entry("minCash", decimal(constraints, "minimumCashWeight")),
				Map.entry("maxLeverage", decimal(constraints, "maximumLeverageRatio")),
				Map.entry("accounts", accountCount), Map.entry("positions", result.path("positions").size()),
				Map.entry("reasons", result.path("risk").path("reasonCodes").size()),
				Map.entry("key", key), Map.entry("requestHash", requestHash),
				Map.entry("contentHash", result.path("contentHash").textValue()),
				Map.entry("payload", result.toString()), Map.entry("recordedAt", Timestamp.from(recordedAt))))
				.update();
	}

	private void insertBindings(UUID userId, UUID contextId, List<UUID> snapshotIds) {
		for (int index = 0; index < snapshotIds.size(); index++) jdbcClient.sql("""
				INSERT INTO app.unified_portfolio_account_binding_v1
				(context_id,user_id,ordinal,account_snapshot_id) VALUES (:context,:userId,:ordinal,:snapshot)
				""").params(Map.of("context", contextId, "userId", userId, "ordinal", index + 1,
				"snapshot", snapshotIds.get(index))).update();
	}

	private void insertPositions(UUID userId, UUID contextId, JsonNode rows) {
		for (int index = 0; index < rows.size(); index++) {
			JsonNode row = rows.get(index);
			var params = new java.util.HashMap<String, Object>();
			params.put("context", contextId); params.put("userId", userId); params.put("ordinal", index + 1);
			params.put("security", UUID.fromString(row.path("securityId").textValue()));
			params.put("ticker", row.path("ticker").textValue()); params.put("sleeve", row.path("sleeve").textValue());
			params.put("sector", row.path("sectorCode").textValue()); params.put("state", row.path("dataState").textValue());
			params.put("value", nullableDecimal(row, "marketValue")); params.put("weight", nullableDecimal(row, "assetWeight"));
			jdbcClient.sql("""
					INSERT INTO app.unified_portfolio_position_v1
					(context_id,user_id,ordinal,security_public_id,ticker,sleeve_type,sector_code,data_state,market_value,asset_weight)
					VALUES (:context,:userId,:ordinal,:security,:ticker,:sleeve,:sector,:state,:value,:weight)
					""").params(params).update();
		}
	}

	private void insertSleeves(UUID userId, UUID contextId, JsonNode rows) {
		for (JsonNode row : rows) jdbcClient.sql("""
				INSERT INTO app.unified_portfolio_sleeve_v1
				(context_id,user_id,sleeve_type,market_value,asset_weight,position_count,model_version,
				 model_evidence_label,research_use_allowed,evidence_reference_id,evidence_reference_hash)
				VALUES (:context,:userId,:sleeve,:value,:weight,:count,:model,:label,:allowed,:reference,:hash)
				""").params(Map.ofEntries(Map.entry("context", contextId), Map.entry("userId", userId),
				Map.entry("sleeve", row.path("sleeve").textValue()), Map.entry("value", decimal(row, "marketValue")),
				Map.entry("weight", decimal(row, "assetWeight")), Map.entry("count", row.path("positionCount").intValue()),
				Map.entry("model", row.path("modelVersion").textValue()), Map.entry("label", row.path("modelEvidenceLabel").textValue()),
				Map.entry("allowed", row.path("researchUseAllowed").booleanValue()),
				Map.entry("reference", row.path("evidenceReferenceId").textValue()),
				Map.entry("hash", row.path("evidenceReferenceHash").textValue()))).update();
	}

	private void insertReasons(UUID userId, UUID contextId, JsonNode rows) {
		for (int index = 0; index < rows.size(); index++) jdbcClient.sql("""
				INSERT INTO app.unified_portfolio_risk_reason_v1
				(context_id,user_id,ordinal,reason_code) VALUES (:context,:userId,:ordinal,:reason)
				""").params(Map.of("context", contextId, "userId", userId, "ordinal", index + 1,
				"reason", rows.get(index).textValue())).update();
	}

	void validateResult(JsonNode result, RiskInput input) {
		requireExactFields(result, ROOT_FIELDS);
		if (!RESULT_VERSION.equals(result.path("resultVersion").textValue())
				|| !"UNIFIED-PORTFOLIO-RISK-CALCULATION-v1.0.0".equals(
						result.path("calculationVersion").textValue())
				|| !"USD".equals(result.path("baseCurrency").textValue())
				|| !("VALID".equals(result.path("state").textValue())
						|| "PARTIAL".equals(result.path("state").textValue()))
				|| !sameInstant(result.path("asOfTime").textValue(), input.asOfTime())
				|| !result.path("positions").isArray() || !result.path("sectors").isArray()
				|| !result.path("sleeves").isArray()
				|| result.path("positions").size() != input.positions().size()
				|| result.path("sleeves").size() != 2) throw invalidUpstream();
		boolean expectedPartial = input.positions().stream()
				.anyMatch(position -> position.dataState() != DataState.VALID);
		if (expectedPartial != "PARTIAL".equals(result.path("state").textValue())) throw invalidUpstream();
		requireExactFields(result.path("totals"), TOTAL_FIELDS);
		for (String field : TOTAL_FIELDS) requireDecimalText(result.path("totals"), field);
		JsonNode constraints = result.path("constraints");
		requireExactFields(constraints, CONSTRAINT_FIELDS);
		for (String field : CONSTRAINT_FIELDS) requireDecimalText(constraints, field);
		if (!sameDecimal(constraints, "maximumPositionWeight", input.constraints().maximumPositionWeight())
				|| !sameDecimal(constraints, "maximumSectorWeight", input.constraints().maximumSectorWeight())
				|| !sameDecimal(constraints, "minimumCashWeight", input.constraints().minimumCashWeight())
				|| !sameDecimal(constraints, "maximumLeverageRatio", input.constraints().maximumLeverageRatio())) {
			throw invalidUpstream();
		}
		JsonNode authority = result.path("authority");
		requireExactFields(authority, AUTHORITY_FIELDS);
		for (String field : AUTHORITY_FIELDS) if (!authority.path(field).isBoolean()) throw invalidUpstream();
		if (authority.path("finalWeightAuthority").booleanValue()
				|| authority.path("orderAuthority").booleanValue()
				|| authority.path("automaticBrokerageExecution").booleanValue()
				|| authority.path("llmDecisionAuthority").booleanValue()
				|| !authority.path("humanDecisionRequired").booleanValue()) throw invalidUpstream();
		String supplied = result.path("contentHash").textValue();
		JsonNode copy = result.deepCopy(); ((tools.jackson.databind.node.ObjectNode) copy).remove("contentHash");
		if (!sha256(canonical(copy)).equals(supplied)) throw invalidUpstream();
		for (int index = 0; index < input.positions().size(); index++) {
			PositionInput expected = input.positions().get(index);
			JsonNode actual = result.path("positions").get(index);
			requireExactFields(actual, POSITION_FIELDS);
			if ("VALID".equals(actual.path("dataState").textValue())) {
				requireDecimalText(actual, "marketValue");
				requireDecimalText(actual, "assetWeight");
			} else if (!actual.path("marketValue").isNull() || !actual.path("assetWeight").isNull()) {
				throw invalidUpstream();
			}
			if (!expected.securityId().toString().equals(actual.path("securityId").textValue())
					|| !expected.ticker().equals(actual.path("ticker").textValue())
					|| !expected.sleeve().name().equals(actual.path("sleeve").textValue())
					|| !expected.sectorCode().equals(actual.path("sectorCode").textValue())
					|| !expected.dataState().name().equals(actual.path("dataState").textValue())) {
				throw invalidUpstream();
			}
			if (expected.marketValue() != null
					&& new java.math.BigDecimal(expected.marketValue()).compareTo(
							new java.math.BigDecimal(actual.path("marketValue").textValue())) != 0) {
				throw invalidUpstream();
			}
		}
		for (int index = 0; index < input.sleeveEvidence().size(); index++) {
			SleeveEvidenceInput expected = input.sleeveEvidence().get(index);
			JsonNode actual = result.path("sleeves").get(index);
			requireExactFields(actual, SLEEVE_FIELDS);
			requireDecimalText(actual, "marketValue");
			requireDecimalText(actual, "assetWeight");
			if (!actual.path("positionCount").isIntegralNumber()
					|| !actual.path("researchUseAllowed").isBoolean()) throw invalidUpstream();
			if (!expected.sleeve().name().equals(actual.path("sleeve").textValue())
					|| !expected.modelVersion().equals(actual.path("modelVersion").textValue())
					|| !expected.evidenceLabel().name().equals(actual.path("modelEvidenceLabel").textValue())
					|| expected.researchUseAllowed() != actual.path("researchUseAllowed").booleanValue()
					|| !expected.referenceId().equals(actual.path("evidenceReferenceId").textValue())
					|| !expected.referenceHash().equals(actual.path("evidenceReferenceHash").textValue())) {
				throw invalidUpstream();
			}
		}
		for (JsonNode sector : result.path("sectors")) {
			requireExactFields(sector, SECTOR_FIELDS);
			if (!sector.path("sectorCode").isTextual()) throw invalidUpstream();
			requireDecimalText(sector, "marketValue");
			requireDecimalText(sector, "assetWeight");
		}
		JsonNode risk = result.path("risk");
		requireExactFields(risk, RISK_FIELDS);
		if (!("PASSED".equals(risk.path("status").textValue())
				|| "VIOLATED".equals(risk.path("status").textValue()))
				|| !"UNIFIED-PORTFOLIO-CONSTRAINTS-v1.0.0".equals(
						risk.path("constraintVersion").textValue())
				|| !risk.path("reasonCodes").isArray()) throw invalidUpstream();
		for (JsonNode reason : risk.path("reasonCodes")) {
			if (!reason.isTextual() || reason.textValue().isBlank()) throw invalidUpstream();
		}
		if (("PASSED".equals(risk.path("status").textValue())) != risk.path("reasonCodes").isEmpty()) {
			throw invalidUpstream();
		}
		if (!result.path("contentHash").isTextual()
				|| !HASH.matcher(result.path("contentHash").textValue()).matches()) throw invalidUpstream();
	}

	private void validateConstraintPolicy(UUID userId, UUID portfolioId, UUID policyId, RiskInput input) {
		var rows = jdbcClient.sql("""
				SELECT maximum_position_weight,maximum_sector_weight,minimum_cash_weight,
				       maximum_leverage_ratio,effective_at
				FROM app.constraint_policy_version
				WHERE id=:id AND user_id=:userId
				  AND (scope_type='USER' OR (scope_type='PORTFOLIO' AND portfolio_id=:portfolioId))
				""").params(Map.of("id", policyId, "userId", userId, "portfolioId", portfolioId))
				.query((rs, row) -> new Object[] {rs.getBigDecimal(1), rs.getBigDecimal(2),
						rs.getBigDecimal(3), rs.getBigDecimal(4), rs.getTimestamp(5).toInstant()})
				.optional().orElseThrow(this::notFound);
		if (rows[0] == null || rows[1] == null || rows[2] == null || rows[3] == null
				|| ((Instant) rows[4]).isAfter(Instant.parse(input.asOfTime()))
				|| ((java.math.BigDecimal) rows[0]).compareTo(new java.math.BigDecimal(input.constraints().maximumPositionWeight())) != 0
				|| ((java.math.BigDecimal) rows[1]).compareTo(new java.math.BigDecimal(input.constraints().maximumSectorWeight())) != 0
				|| ((java.math.BigDecimal) rows[2]).compareTo(new java.math.BigDecimal(input.constraints().minimumCashWeight())) != 0
				|| ((java.math.BigDecimal) rows[3]).compareTo(new java.math.BigDecimal(input.constraints().maximumLeverageRatio())) != 0) {
			throw validation("PORTFOLIO_CONSTRAINT_POLICY_MISMATCH");
		}
	}

	private void validateAccountSnapshots(UUID userId, UUID portfolioId, List<UUID> ids, RiskInput input) {
		if (ids.size() != new HashSet<>(ids).size()) throw validation("DUPLICATE_ACCOUNT_SNAPSHOT");
		List<UUID> sortedIds = ids.stream().sorted(Comparator.comparing(UUID::toString)).toList();
		if (!ids.equals(sortedIds)) throw validation("ACCOUNT_SNAPSHOTS_NOT_CANONICALLY_ORDERED");
		for (UUID id : ids) {
			int count = jdbcClient.sql("""
					SELECT count(*) FROM app.account_snapshot snapshot
					JOIN app.account_snapshot_task5_contract_v1 governed
					  ON governed.snapshot_id=snapshot.id AND governed.user_id=snapshot.user_id
					JOIN app.portfolio_account_membership membership
					  ON membership.account_id=snapshot.account_id AND membership.user_id=snapshot.user_id
					JOIN app.investment_account account
					  ON account.id=snapshot.account_id AND account.user_id=snapshot.user_id
					WHERE snapshot.id=:snapshot AND snapshot.user_id=:userId
					  AND membership.portfolio_id=:portfolio AND snapshot.sealed_at IS NOT NULL
					  AND snapshot.completeness='COMPLETE' AND account.base_currency='USD'
					  AND snapshot.as_of_time <= CAST(:asOf AS timestamptz)
					""").params(Map.of("snapshot", id, "userId", userId, "portfolio", portfolioId,
						"asOf", input.asOfTime()))
					.query(Integer.class).single();
			if (count != 1) throw notFound();
		}
		Set<UUID> expectedSecurities = new HashSet<>();
		for (PositionInput position : input.positions()) expectedSecurities.add(position.securityId());
		Set<UUID> actualSecurities = new HashSet<>(jdbcClient.sql("""
				SELECT DISTINCT security_public_id FROM app.position_snapshot
				WHERE user_id=:userId AND snapshot_id IN (:snapshotIds)
				""").param("userId", userId).param("snapshotIds", ids).query(UUID.class).list());
		if (!actualSecurities.equals(expectedSecurities)) {
			throw validation("PORTFOLIO_POSITION_SNAPSHOT_SET_MISMATCH");
		}
		java.math.BigDecimal cash = jdbcClient.sql("""
				SELECT COALESCE(sum(settled_amount + unsettled_amount - restricted_amount),0)
				FROM app.cash_balance_snapshot
				WHERE user_id=:userId AND snapshot_id IN (:snapshotIds) AND currency='USD'
				""").param("userId", userId).param("snapshotIds", ids)
				.query(java.math.BigDecimal.class).single();
		int nonUsdCash = jdbcClient.sql("""
				SELECT count(*) FROM app.cash_balance_snapshot
				WHERE user_id=:userId AND snapshot_id IN (:snapshotIds) AND currency<>'USD'
				""").param("userId", userId).param("snapshotIds", ids).query(Integer.class).single();
		if (nonUsdCash != 0 || cash.compareTo(new java.math.BigDecimal(input.cashValue())) != 0) {
			throw validation("PORTFOLIO_CASH_SNAPSHOT_MISMATCH");
		}
		java.math.BigDecimal liabilities = jdbcClient.sql("""
				SELECT COALESCE(sum(latest.balance),0) FROM app.portfolio_liability_membership membership
				JOIN app.financial_liability liability
				  ON liability.id=membership.liability_id AND liability.user_id=membership.user_id
				JOIN LATERAL (
				 SELECT balance FROM app.liability_balance_snapshot snapshot
				 WHERE snapshot.liability_id=membership.liability_id
				   AND snapshot.user_id=membership.user_id
				   AND snapshot.as_of_time <= CAST(:asOf AS timestamptz)
				 ORDER BY snapshot.as_of_time DESC, snapshot.id DESC LIMIT 1
				) latest ON TRUE
				WHERE membership.portfolio_id=:portfolio AND membership.user_id=:userId
				  AND liability.currency='USD' AND liability.status='ACTIVE'
				""").params(Map.of("portfolio", portfolioId, "userId", userId, "asOf", input.asOfTime()))
				.query(java.math.BigDecimal.class).single();
		int unavailableLiabilities = jdbcClient.sql("""
				SELECT count(*) FROM app.portfolio_liability_membership membership
				JOIN app.financial_liability liability
				  ON liability.id=membership.liability_id AND liability.user_id=membership.user_id
				LEFT JOIN LATERAL (
				 SELECT balance FROM app.liability_balance_snapshot snapshot
				 WHERE snapshot.liability_id=membership.liability_id
				   AND snapshot.user_id=membership.user_id
				   AND snapshot.as_of_time <= CAST(:asOf AS timestamptz)
				 ORDER BY snapshot.as_of_time DESC, snapshot.id DESC LIMIT 1
				) latest ON TRUE
				WHERE membership.portfolio_id=:portfolio AND membership.user_id=:userId
				  AND liability.status='ACTIVE'
				  AND (liability.currency<>'USD' OR latest.balance IS NULL)
				""").params(Map.of("portfolio", portfolioId, "userId", userId, "asOf", input.asOfTime()))
				.query(Integer.class).single();
		if (unavailableLiabilities != 0
				|| liabilities.compareTo(new java.math.BigDecimal(input.liabilityValue())) != 0) {
			throw validation("PORTFOLIO_LIABILITY_SNAPSHOT_MISMATCH");
		}
	}

	private ContextResponse findByIdempotency(UUID userId, String key, String requestHash) {
		return jdbcClient.sql("""
				SELECT context.id,context.portfolio_id,context.public_payload::text,context.recorded_at,
				       review.id,review.conclusion,review.rationale,review.content_hash,review.reviewed_at,
				       context.source_request_hash
				FROM app.unified_portfolio_context_v1 context
				LEFT JOIN app.unified_portfolio_review_v1 review
				  ON review.context_id=context.id AND review.user_id=context.user_id
				WHERE context.user_id=:userId AND context.idempotency_key=:key
				""").params(Map.of("userId", userId, "key", key)).query((rs, row) -> {
				if (!requestHash.equals(rs.getString(10))) throw new PortfolioContextException(
						"PORTFOLIO_CONTEXT_IDEMPOTENCY_CONFLICT", "Idempotency key content differs.", 409);
				return response(rs.getObject(1, UUID.class), rs.getObject(2, UUID.class), rs.getString(3),
						rs.getTimestamp(4).toInstant(), rs.getObject(5, UUID.class), rs.getString(6),
						rs.getString(7), rs.getString(8), rs.getTimestamp(9));
			}).optional().orElse(null);
	}

	private ReviewResponse findReviewByIdempotency(UUID userId, String key, String requestHash) {
		return jdbcClient.sql("""
				SELECT id,context_id,conclusion,rationale,content_hash,reviewed_at,recorded_at,request_hash
				FROM app.unified_portfolio_review_v1 WHERE user_id=:userId AND idempotency_key=:key
				""").params(Map.of("userId", userId, "key", key)).query((rs, row) -> {
			if (!requestHash.equals(rs.getString(8))) throw new PortfolioContextException(
					"PORTFOLIO_CONTEXT_IDEMPOTENCY_CONFLICT", "Idempotency key content differs.", 409);
			return new ReviewResponse(rs.getObject(1, UUID.class), rs.getObject(2, UUID.class),
					ReviewConclusion.valueOf(rs.getString(3)), rs.getString(4), rs.getString(5),
					rs.getTimestamp(6).toInstant().toString(), rs.getTimestamp(7).toInstant().toString());
		}).optional().orElse(null);
	}

	private ContextResponse response(UUID id, UUID portfolioId, String payload, Instant recordedAt,
			UUID reviewId, String conclusion, String rationale, String reviewHash, Timestamp reviewedAt) {
		try {
			ReviewSummary review = reviewId == null ? null : new ReviewSummary(reviewId,
					ReviewConclusion.valueOf(conclusion), rationale, reviewHash,
					reviewedAt.toInstant().toString());
			return new ContextResponse(id, portfolioId, MAPPER.readTree(payload), review, recordedAt.toString());
		}
		catch (RuntimeException error) { throw invalidUpstream(); }
	}

	private CurrentAssemblySource currentAssemblySource(UUID user,UUID portfolio,
			CreateCurrentEvidenceContextRequest request,Map<UUID,CurrentEvidenceReference> references) {
		List<CurrentHolding> holdings=jdbcClient.sql("""
				SELECT p.security_public_id,s.symbol,sum(p.quantity),COALESCE(c.normalized_sector,'UNCLASSIFIED')
				FROM app.position_snapshot p JOIN app.account_snapshot a ON a.id=p.snapshot_id AND a.user_id=p.user_id
				JOIN app.account_snapshot_task5_contract_v1 governed
				 ON governed.snapshot_id=a.id AND governed.user_id=a.user_id
				JOIN app.portfolio_account_membership m ON m.account_id=a.account_id AND m.user_id=a.user_id
				JOIN analytics.security s ON s.public_id=p.security_public_id
				LEFT JOIN LATERAL (SELECT normalized_sector FROM analytics.security_classification x
				 WHERE x.security_id=s.id AND x.effective_from<=a.as_of_time::date
				 AND (x.effective_to IS NULL OR x.effective_to>a.as_of_time::date)
				 ORDER BY x.effective_from DESC,x.id DESC LIMIT 1) c ON true
				WHERE p.user_id=:user AND m.portfolio_id=:portfolio AND p.snapshot_id IN (:snapshots)
				AND a.sealed_at IS NOT NULL GROUP BY p.security_public_id,s.symbol,c.normalized_sector ORDER BY p.security_public_id
				""").params(Map.of("user",user,"portfolio",portfolio,"snapshots",request.accountSnapshotIds()))
				.query((rs,n)->new CurrentHolding(rs.getObject(1,UUID.class),rs.getString(2),rs.getBigDecimal(3),rs.getString(4))).list();
		if(holdings.isEmpty()||!holdings.stream().map(CurrentHolding::securityId).collect(java.util.stream.Collectors.toSet())
				.equals(references.keySet()))throw validation("CURRENT_EVIDENCE_SECURITY_SET_MISMATCH");
		CurrentTotals totals=jdbcClient.sql("""
				SELECT max(a.as_of_time),COALESCE(sum(c.settled_amount+c.unsettled_amount-c.restricted_amount),0)
				FROM app.account_snapshot a JOIN app.account_snapshot_task5_contract_v1 governed
				 ON governed.snapshot_id=a.id AND governed.user_id=a.user_id
				JOIN app.cash_balance_snapshot c ON c.snapshot_id=a.id AND c.user_id=a.user_id
				WHERE a.user_id=:user AND a.id IN (:snapshots) AND c.currency='USD' AND a.sealed_at IS NOT NULL
				""").params(Map.of("user",user,"snapshots",request.accountSnapshotIds())).query((rs,n)->new CurrentTotals(
				rs.getTimestamp(1).toInstant(),rs.getBigDecimal(2))).single();
		BigDecimal liabilities=jdbcClient.sql("""
				SELECT COALESCE(sum(latest.balance),0) FROM app.portfolio_liability_membership m
				JOIN LATERAL (SELECT balance FROM app.liability_balance_snapshot b WHERE b.liability_id=m.liability_id
				 AND b.user_id=m.user_id AND b.as_of_time<=:cutoff ORDER BY b.as_of_time DESC,b.id DESC LIMIT 1) latest ON true
				WHERE m.user_id=:user AND m.portfolio_id=:portfolio
				""").params(Map.of("user",user,"portfolio",portfolio,"cutoff",Timestamp.from(totals.asOf()))).query(BigDecimal.class).single();
		PolicyInput policy=jdbcClient.sql("""
				SELECT maximum_position_weight,maximum_sector_weight,minimum_cash_weight,maximum_leverage_ratio
				FROM app.constraint_policy_version WHERE id=:id AND user_id=:user AND portfolio_id=:portfolio
				AND scope_type='PORTFOLIO'
				""").params(Map.of("id",request.constraintPolicyVersionId(),"user",user,"portfolio",portfolio))
				.query((rs,n)->new PolicyInput(rs.getBigDecimal(1),rs.getBigDecimal(2),rs.getBigDecimal(3),rs.getBigDecimal(4)))
				.optional().orElseThrow(this::notFound);
		ObjectNode command=MAPPER.createObjectNode();command.put("assemblyVersion","current-portfolio-evidence-assembly-v1.0.0");
		command.put("asOfTime",totals.asOf().truncatedTo(java.time.temporal.ChronoUnit.SECONDS).toString());
		command.put("cashValue",decimalText(totals.cash()));command.put("liabilityValue",decimalText(liabilities));
		var rows=command.putArray("holdings"); for(CurrentHolding holding:holdings){CurrentEvidenceReference reference=references.get(holding.securityId());
			var row=rows.addObject();row.put("securityId",holding.securityId().toString());row.put("ticker",holding.ticker());
			row.put("quantity",decimalText(holding.quantity()));row.put("sleeve",reference.sleeve().name());
			row.put("sectorCode",holding.sector());row.put("selectionRequestId",reference.selectionRequestId().toString());
			if(reference.modelReferenceId()==null)row.putNull("modelReferenceId");else row.put("modelReferenceId",reference.modelReferenceId().toString());}
		ObjectNode constraints=command.putObject("constraints");constraints.put("maximumPositionWeight",decimalText(policy.maxPosition()));
		constraints.put("maximumSectorWeight",decimalText(policy.maxSector()));constraints.put("minimumCashWeight",decimalText(policy.minCash()));
		constraints.put("maximumLeverageRatio",decimalText(policy.maxLeverage()));
		return new CurrentAssemblySource(command);
	}

	private CurrentEvidenceContextResponse findCurrentEvidenceByIdempotency(CurrentUser user,UUID portfolio,
			String key,String requestHash) {
		return jdbcClient.sql("""
				SELECT id,context_id,request_hash,content_hash
				FROM app.portfolio_context_evidence_manifest_v1
				WHERE user_id=:user AND portfolio_id=:portfolio AND idempotency_key=:key
				  AND sealed_at IS NOT NULL
				""").params(Map.of("user",user.userId(),"portfolio",portfolio,"key",key))
				.query((rs,n)->{
					if(!requestHash.equals(rs.getString(3)))throw new PortfolioContextException(
							"PORTFOLIO_CONTEXT_IDEMPOTENCY_CONFLICT","Idempotency key content differs.",409);
					return new CurrentEvidenceContextResponse(get(user,portfolio,rs.getObject(2,UUID.class)),
							rs.getObject(1,UUID.class),rs.getString(4));
				}).optional().orElse(null);
	}

	private UUID persistEvidenceManifest(CurrentUser user,UUID portfolio,UUID context,String key,
			String requestHash,JsonNode manifest) {
		UUID id=UUID.randomUUID();Instant now=Instant.now().truncatedTo(java.time.temporal.ChronoUnit.SECONDS);
		List<UUID> selectionRequests=java.util.stream.StreamSupport.stream(manifest.path("positions").spliterator(),false)
				.map(row->row.path("selectionRequestId")).filter(JsonNode::isTextual)
				.map(node->UUID.fromString(node.asText())).toList();
		if(selectionRequests.isEmpty())throw validation("SEALED_INGESTION_CUTOFF_REQUIRED");
		Instant[] cutoffs=jdbcClient.sql("""
				SELECT min(decision_cutoff),max(decision_cutoff),min(sealed_ingestion_cutoff),max(sealed_ingestion_cutoff)
				FROM analytics.evidence_selection_request_v1 WHERE request_id IN (:ids)
				""").param("ids",selectionRequests).query((rs,n)->new Instant[]{rs.getTimestamp(1).toInstant(),
				rs.getTimestamp(2).toInstant(),rs.getTimestamp(3).toInstant(),rs.getTimestamp(4).toInstant()}).single();
		if(!cutoffs[0].equals(cutoffs[1])||!cutoffs[2].equals(cutoffs[3]))
			throw validation("EVIDENCE_SELECTION_CUTOFF_DRIFT");
		Instant decisionCutoff=cutoffs[0],sealedIngestionCutoff=cutoffs[2];
		jdbcClient.sql("""
				INSERT INTO app.portfolio_context_evidence_manifest_v1
				(id,user_id,portfolio_id,context_id,contract_version,decision_cutoff,sealed_ingestion_cutoff,position_count,idempotency_key,
				 request_hash,content_hash,recorded_at)
				VALUES (:id,:user,:portfolio,:context,'portfolio-context-evidence-manifest-v1.0.0',:cutoff,:ingestionCutoff,:count,
				 :key,:requestHash,:hash,:recorded)
				""").params(Map.ofEntries(Map.entry("id",id),Map.entry("user",user.userId()),
				Map.entry("portfolio",portfolio),Map.entry("context",context),
				Map.entry("cutoff",Timestamp.from(decisionCutoff)),
				Map.entry("count",manifest.path("positions").size()),
				Map.entry("ingestionCutoff",Timestamp.from(sealedIngestionCutoff)),Map.entry("key",key),
				Map.entry("hash",manifest.path("manifestHash").asText()),Map.entry("requestHash",requestHash),
				Map.entry("recorded",Timestamp.from(now)))).update();
		Map<String,JsonNode> modelReferences=new HashMap<>();for(JsonNode reference:manifest.path("perSecurityModelReferences"))
			modelReferences.put(reference.path("securityId").asText(),reference);
		int ordinal=0;for(JsonNode row:manifest.path("positions")){JsonNode reference=modelReferences.get(row.path("securityId").asText());
			boolean fundamental=reference!=null&&"LONG_TERM_CORE".equals(reference.path("sleeve").asText());
			boolean quant=reference!=null&&"QUANT_TRADING".equals(reference.path("sleeve").asText());jdbcClient.sql("""
				INSERT INTO app.portfolio_context_position_evidence_v1
				(manifest_id,user_id,ordinal,security_public_id,data_state,price_evidence_id,
				 price_selection_request_id,price_selection_result_hash,price_evidence_hash,price_ingested_at,
				 fundamental_assessment_id,fundamental_assessment_hash,fundamental_evidence_label,
				 quant_decision_id,quant_decision_hash,quant_evidence_label)
				VALUES (:manifest,:user,:ordinal,:security,:state,:evidence,:selectionRequest,
				 :selectionResultHash,:evidenceHash,:ingested,
				 :fv,:fvHash,:fvLabel,:quant,:quantHash,:quantLabel)
				""").params(Map.ofEntries(Map.entry("manifest",id),Map.entry("user",user.userId()),Map.entry("ordinal",++ordinal),
				Map.entry("security",UUID.fromString(row.path("securityId").asText())),Map.entry("state",row.path("priceState").asText()),
				Map.entry("evidence",nullableUuid(row,"evidenceId")),
				Map.entry("selectionRequest",nullableUuid(row,"selectionRequestId")),
				Map.entry("selectionResultHash",nullableText(row,"selectionResultHash")),
				Map.entry("evidenceHash",nullableText(row,"evidenceHash")),
				Map.entry("ingested",nullableInstant(row,"ingestedAt")),Map.entry("fv",fundamental?UUID.fromString(reference.path("referenceId").asText()):nullableSql()),
				Map.entry("fvHash",fundamental?reference.path("referenceHash").asText():nullableSql()),Map.entry("fvLabel",fundamental?reference.path("evidenceLabel").asText():nullableSql()),
				Map.entry("quant",quant?UUID.fromString(reference.path("referenceId").asText()):nullableSql()),Map.entry("quantHash",quant?reference.path("referenceHash").asText():nullableSql()),
				Map.entry("quantLabel",quant?reference.path("evidenceLabel").asText():nullableSql()))).update();}
		jdbcClient.sql("UPDATE app.portfolio_context_evidence_manifest_v1 SET sealed_at=:seal WHERE id=:id")
				.params(Map.of("seal",Timestamp.from(now),"id",id)).update();
		return id;
	}

	private static Object nullableUuid(JsonNode row,String field){return row.path(field).isNull()||row.path(field).isMissingNode()?nullableSql():UUID.fromString(row.path(field).asText());}
	private static Object nullableText(JsonNode row,String field){return row.path(field).isNull()||row.path(field).isMissingNode()?nullableSql():row.path(field).asText();}
	private static Object nullableInstant(JsonNode row,String field){return row.path(field).isNull()||row.path(field).isMissingNode()?nullableSql():Timestamp.from(Instant.parse(row.path(field).asText()));}
	private static Object nullableSql(){return new org.springframework.jdbc.core.SqlParameterValue(java.sql.Types.NULL,null);}
	private static String decimalText(BigDecimal value){return value.signum()==0?"0":value.stripTrailingZeros().toPlainString();}
	private record CurrentHolding(UUID securityId,String ticker,BigDecimal quantity,String sector){}
	private record CurrentTotals(Instant asOf,BigDecimal cash){}
	private record PolicyInput(BigDecimal maxPosition,BigDecimal maxSector,BigDecimal minCash,BigDecimal maxLeverage){}
	private record CurrentAssemblySource(ObjectNode command){
		JsonNode commandRiskInput(JsonNode risk){return currentRiskInput(risk);}
	}

	static JsonNode currentRiskInput(JsonNode risk){ObjectNode result=MAPPER.createObjectNode()
				.put("contractVersion",INPUT_VERSION).put("asOfTime",Instant.parse(risk.path("asOfTime").asText()).toString()).put("baseCurrency","USD")
				.put("cashValue",risk.path("totals").path("cashValue").asText()).put("liabilityValue",risk.path("totals").path("liabilityValue").asText());
			var positions=result.putArray("positions");for(JsonNode row:risk.path("positions")){var item=positions.addObject();
				item.put("securityId",row.path("securityId").asText());item.put("ticker",row.path("ticker").asText());
				item.put("sleeve",row.path("sleeve").asText());item.put("sectorCode",row.path("sectorCode").asText());
				if(row.path("marketValue").isNull())item.putNull("marketValue");else item.put("marketValue",row.path("marketValue").asText());
				item.put("dataState",row.path("dataState").asText());}
			var sleeves=result.putArray("sleeveEvidence");for(JsonNode row:risk.path("sleeves")){var item=sleeves.addObject();
				item.put("sleeve",row.path("sleeve").asText());item.put("modelVersion",row.path("modelVersion").asText());
				item.put("evidenceLabel",row.path("modelEvidenceLabel").asText());item.put("researchUseAllowed",row.path("researchUseAllowed").booleanValue());
				item.put("referenceId",row.path("evidenceReferenceId").asText());item.put("referenceHash",row.path("evidenceReferenceHash").asText());}
		ObjectNode constraints=result.putObject("constraints");for(String field:List.of("maximumPositionWeight","maximumSectorWeight","minimumCashWeight","maximumLeverageRatio"))
			constraints.put(field,risk.path("constraints").path(field).asText());return result;
	}

	private void requirePortfolio(UUID userId, UUID portfolioId) {
		int count = jdbcClient.sql("SELECT count(*) FROM app.portfolio WHERE id=:id AND user_id=:userId AND status='ACTIVE'")
				.params(Map.of("id", portfolioId, "userId", userId)).query(Integer.class).single();
		if (count != 1) throw notFound();
	}

	private static java.math.BigDecimal decimal(JsonNode node, String field) {
		return new java.math.BigDecimal(node.path(field).textValue());
	}
	private static java.math.BigDecimal nullableDecimal(JsonNode node, String field) {
		return node.path(field).isNull() ? null : decimal(node, field);
	}
	private static void requireExactFields(JsonNode node, Set<String> expected) {
		if (!node.isObject()) throw invalidUpstream();
		Set<String> actual = new HashSet<>(); node.propertyStream().forEach(entry -> actual.add(entry.getKey()));
		if (!actual.equals(expected)) throw invalidUpstream();
	}
	private static void requireDecimalText(JsonNode node, String field) {
		JsonNode value = node.path(field);
		if (!value.isTextual() || !DECIMAL.matcher(value.textValue()).matches()) throw invalidUpstream();
		try { new java.math.BigDecimal(value.textValue()); }
		catch (NumberFormatException error) {
			throw invalidUpstream();
		}
	}
	private static boolean sameInstant(String left, String right) {
		try { return Instant.parse(left).equals(Instant.parse(right)); }
		catch (RuntimeException error) { return false; }
	}
	private static boolean sameDecimal(JsonNode node, String field, String expected) {
		try { return new java.math.BigDecimal(node.path(field).textValue())
				.compareTo(new java.math.BigDecimal(expected)) == 0; }
		catch (RuntimeException error) { return false; }
	}
	private static void requireIdempotency(String value) {
		if (value == null || value.isBlank() || value.length() > 128) throw validation("IDEMPOTENCY_KEY_REQUIRED");
	}

	private static String canonical(JsonNode node) {
		if (node.isObject()) {
			List<Map.Entry<String, JsonNode>> fields = new ArrayList<>();
			node.propertyStream().forEach(fields::add); fields.sort(Comparator.comparing(Map.Entry::getKey));
			return "{" + fields.stream().map(entry -> quote(entry.getKey()) + ":" + canonical(entry.getValue()))
					.collect(java.util.stream.Collectors.joining(",")) + "}";
		}
		if (node.isArray()) {
			List<String> values = new ArrayList<>(); for (JsonNode item : node) values.add(canonical(item));
			return "[" + String.join(",", values) + "]";
		}
		return node.toString();
	}
	private static String quote(String value) { return MAPPER.valueToTree(value).toString(); }
	private static String sha256(String value) {
		try { return "sha256:" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
				.digest(value.getBytes(StandardCharsets.UTF_8))); }
		catch (NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
	}
	private static PortfolioContextException validation(String code) {
		return new PortfolioContextException(code, "The portfolio context request is invalid.", 422);
	}
	private static PortfolioContextException invalidUpstream() {
		return new PortfolioContextException("INVALID_PORTFOLIO_RISK_UPSTREAM_RESPONSE",
				"The analytics service returned an invalid portfolio risk result.", 502);
	}
	private PortfolioContextException notFound() {
		return new PortfolioContextException("PORTFOLIO_CONTEXT_NOT_FOUND",
				"The requested portfolio context was not found.", 404);
	}
}
