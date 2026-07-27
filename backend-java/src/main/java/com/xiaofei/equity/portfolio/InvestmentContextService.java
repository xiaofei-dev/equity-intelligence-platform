package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.InvestmentContextContracts.*;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import com.xiaofei.equity.usercontext.CurrentUser;
import com.xiaofei.equity.usercontext.UserContextException;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class InvestmentContextService {

	private final JdbcClient jdbcClient;

	public InvestmentContextService(JdbcClient jdbcClient) {
		this.jdbcClient = jdbcClient;
	}

	@Transactional
	public InvestmentProfileResponse createProfile(
			CurrentUser user,
			String idempotencyKey,
			CreateInvestmentProfileRequest request) {
		requireIdempotencyKey(idempotencyKey);
		validateGoals(request.goals());
		validateSectorPreferences(request.sectorPreferences());
		String requestHash = requestHash(request);

		InvestmentProfileResponse existing = findProfileByIdempotency(user.userId(), idempotencyKey);
		if (existing != null) {
			String storedHash = jdbcClient.sql("""
					SELECT request_hash
					FROM app.investment_profile_version
					WHERE user_id = :userId AND idempotency_key = :idempotencyKey
					""")
				.params(Map.of("userId", user.userId(), "idempotencyKey", idempotencyKey))
				.query(String.class).single();
			requireMatchingIdempotency(storedHash, requestHash);
			return existing;
		}

		int version = jdbcClient.sql("""
				SELECT COALESCE(MAX(version_number), 0) + 1
				FROM app.investment_profile_version
				WHERE user_id = :userId
				""")
			.param("userId", user.userId())
			.query(Integer.class).single();
		UUID profileId = UUID.randomUUID();
		Instant recordedAt = Instant.now();
		Map<String, Object> params = new HashMap<>();
		params.put("id", profileId);
		params.put("userId", user.userId());
		params.put("version", version);
		params.put("approach", request.investmentApproach().name());
		params.put("horizon", request.primaryHorizon().name());
		params.put("risk", request.riskTolerance().name());
		params.put("liquidityNeeds", request.liquidityNeeds());
		params.put("notes", request.notes());
		params.put("idempotencyKey", idempotencyKey);
		params.put("requestHash", requestHash);
		params.put("effectiveAt", Timestamp.from(request.effectiveAt()));
		params.put("recordedAt", Timestamp.from(recordedAt));
		jdbcClient.sql("""
				INSERT INTO app.investment_profile_version (
				    id, user_id, version_number, investment_approach,
				    primary_horizon, risk_tolerance, liquidity_needs, notes,
				    idempotency_key, request_hash, effective_at, recorded_at
				) VALUES (
				    :id, :userId, :version, :approach,
				    :horizon, :risk, :liquidityNeeds, :notes,
				    :idempotencyKey, :requestHash, :effectiveAt, :recordedAt
				)
				""")
			.params(params).update();

		for (GoalInput goal : request.goals()) {
			Map<String, Object> goalParams = new HashMap<>();
			goalParams.put("id", UUID.randomUUID());
			goalParams.put("userId", user.userId());
			goalParams.put("profileId", profileId);
			goalParams.put("goalType", goal.goalType());
			goalParams.put("priority", goal.priority());
			goalParams.put("targetDate", goal.targetDate());
			goalParams.put("targetAmount", goal.targetAmount());
			goalParams.put("currency", goal.currency());
			goalParams.put("description", goal.description());
			jdbcClient.sql("""
					INSERT INTO app.investment_goal (
					    id, user_id, profile_version_id, goal_type, priority,
					    target_date, target_amount, currency, description
					) VALUES (
					    :id, :userId, :profileId, :goalType, :priority,
					    :targetDate, :targetAmount, :currency, :description
					)
					""")
				.params(goalParams).update();
		}
		for (SectorPreferenceInput preference : request.sectorPreferences()) {
			jdbcClient.sql("""
					INSERT INTO app.sector_preference (
					    id, user_id, profile_version_id, taxonomy_code,
					    taxonomy_version, sector_code, preference
					) VALUES (
					    :id, :userId, :profileId, :taxonomyCode,
					    :taxonomyVersion, :sectorCode, :preference
					)
					""")
				.params(Map.of(
						"id", UUID.randomUUID(),
						"userId", user.userId(),
						"profileId", profileId,
						"taxonomyCode", preference.taxonomyCode(),
						"taxonomyVersion", preference.taxonomyVersion(),
						"sectorCode", preference.sectorCode(),
						"preference", preference.preference().name()))
				.update();
		}
		audit(user, "INVESTMENT_PROFILE_RECORDED", "investment_profile_version",
				profileId, "SUCCEEDED");
		return new InvestmentProfileResponse(
				profileId, version, request.investmentApproach(),
				request.primaryHorizon(), request.riskTolerance(),
				request.liquidityNeeds(), request.notes(), request.effectiveAt(),
				recordedAt, request.goals(), request.sectorPreferences());
	}

	public InvestmentProfileResponse latestProfile(CurrentUser user) {
		return jdbcClient.sql("""
				SELECT id, version_number, investment_approach, primary_horizon,
				       risk_tolerance, liquidity_needs, notes, effective_at, recorded_at
				FROM app.investment_profile_version
				WHERE user_id = :userId
				ORDER BY version_number DESC
				LIMIT 1
				""")
			.param("userId", user.userId())
			.query((rs, rowNumber) -> profileResponse(user.userId(), rs))
			.optional()
			.orElseThrow(InvestmentContextService::notFound);
	}

	@Transactional
	public LiabilityResponse createLiability(CurrentUser user, CreateLiabilityRequest request) {
		if (request.accountId() != null) {
			requireOwnedAccount(user.userId(), request.accountId());
		}
		UUID id = UUID.randomUUID();
		Instant now = Instant.now();
		Map<String, Object> params = new HashMap<>();
		params.put("id", id);
		params.put("userId", user.userId());
		params.put("accountId", request.accountId());
		params.put("name", request.name());
		params.put("type", request.liabilityType().name());
		params.put("currency", request.currency());
		params.put("createdAt", Timestamp.from(now));
		jdbcClient.sql("""
				INSERT INTO app.financial_liability (
				    id, user_id, account_id, name, liability_type, currency, created_at
				) VALUES (
				    :id, :userId, :accountId, :name, :type, :currency, :createdAt
				)
				""")
			.params(params).update();
		audit(user, "LIABILITY_CREATED", "financial_liability", id, "SUCCEEDED");
		return new LiabilityResponse(
				id, request.accountId(), request.name(), request.liabilityType(),
				request.currency(), "ACTIVE", now);
	}

	public List<LiabilityResponse> listLiabilities(CurrentUser user) {
		return jdbcClient.sql("""
				SELECT id, account_id, name, liability_type, currency, status, created_at
				FROM app.financial_liability
				WHERE user_id = :userId
				ORDER BY created_at, id
				""")
			.param("userId", user.userId())
			.query((rs, rowNumber) -> new LiabilityResponse(
					rs.getObject("id", UUID.class),
					rs.getObject("account_id", UUID.class),
					rs.getString("name"),
					LiabilityType.valueOf(rs.getString("liability_type")),
					rs.getString("currency"),
					rs.getString("status"),
					rs.getTimestamp("created_at").toInstant()))
			.list();
	}

	@Transactional
	public LiabilityBalanceAccepted recordLiabilityBalance(
			CurrentUser user,
			UUID liabilityId,
			String idempotencyKey,
			CreateLiabilityBalanceRequest request) {
		requireIdempotencyKey(idempotencyKey);
		requireOwnedLiability(user.userId(), liabilityId);
		String requestHash = requestHash(request);
		LiabilityBalanceAccepted existing = findLiabilityBalance(
				user.userId(), liabilityId, idempotencyKey);
		if (existing != null) {
			String storedHash = jdbcClient.sql("""
					SELECT request_hash
					FROM app.liability_balance_snapshot
					WHERE user_id = :userId AND liability_id = :liabilityId
					  AND idempotency_key = :idempotencyKey
					""")
				.params(Map.of(
						"userId", user.userId(),
						"liabilityId", liabilityId,
						"idempotencyKey", idempotencyKey))
				.query(String.class).single();
			requireMatchingIdempotency(storedHash, requestHash);
			return existing;
		}

		UUID id = UUID.randomUUID();
		Instant recordedAt = Instant.now();
		Map<String, Object> params = new HashMap<>();
		params.put("id", id);
		params.put("userId", user.userId());
		params.put("liabilityId", liabilityId);
		params.put("asOfTime", Timestamp.from(request.asOfTime()));
		params.put("balance", request.balance());
		params.put("annualInterestRate", request.annualInterestRate());
		params.put("sourceType", request.sourceType().name());
		params.put("idempotencyKey", idempotencyKey);
		params.put("requestHash", requestHash);
		params.put("recordedAt", Timestamp.from(recordedAt));
		jdbcClient.sql("""
				INSERT INTO app.liability_balance_snapshot (
				    id, user_id, liability_id, as_of_time, balance,
				    annual_interest_rate, source_type, idempotency_key,
				    request_hash, recorded_at
				) VALUES (
				    :id, :userId, :liabilityId, :asOfTime, :balance,
				    :annualInterestRate, :sourceType, :idempotencyKey,
				    :requestHash, :recordedAt
				)
				""")
			.params(params).update();
		audit(user, "LIABILITY_BALANCE_RECORDED", "liability_balance_snapshot",
				id, "SUCCEEDED");
		return new LiabilityBalanceAccepted(
				id, liabilityId, request.asOfTime(), request.balance(),
				request.annualInterestRate(), recordedAt);
	}

	@Transactional
	public ConstraintPolicyResponse createConstraintPolicy(
			CurrentUser user,
			String idempotencyKey,
			CreateConstraintPolicyRequest request) {
		requireIdempotencyKey(idempotencyKey);
		validateScope(user.userId(), request);
		validateSectorConstraints(request.sectorConstraints());
		String requestHash = requestHash(request);
		ConstraintPolicyResponse existing = findPolicyByIdempotency(
				user.userId(), idempotencyKey);
		if (existing != null) {
			String storedHash = jdbcClient.sql("""
					SELECT request_hash
					FROM app.constraint_policy_version
					WHERE user_id = :userId AND idempotency_key = :idempotencyKey
					""")
				.params(Map.of("userId", user.userId(), "idempotencyKey", idempotencyKey))
				.query(String.class).single();
			requireMatchingIdempotency(storedHash, requestHash);
			return existing;
		}

		ConstraintValues parent = parentConstraints(user.userId(), request);
		ConstraintValues proposed = values(request);
		ConstraintPolicyRules.requireTightening(parent, proposed);
		validateSectorTightening(user.userId(), request);

		int version = nextPolicyVersion(user.userId(), request);
		UUID policyId = UUID.randomUUID();
		Instant recordedAt = Instant.now();
		Map<String, Object> params = new HashMap<>();
		params.put("id", policyId);
		params.put("userId", user.userId());
		params.put("scopeType", request.scopeType().name());
		params.put("portfolioId", request.portfolioId());
		params.put("accountId", request.accountId());
		params.put("version", version);
		params.put("maximumPositionCount", request.maximumPositionCount());
		params.put("maximumPositionWeight", request.maximumPositionWeight());
		params.put("maximumSectorWeight", request.maximumSectorWeight());
		params.put("minimumCashWeight", request.minimumCashWeight());
		params.put("maximumLeverageRatio", request.maximumLeverageRatio());
		params.put("maximumSpeculativeWeight", request.maximumSpeculativeWeight());
		params.put("idempotencyKey", idempotencyKey);
		params.put("requestHash", requestHash);
		params.put("effectiveAt", Timestamp.from(request.effectiveAt()));
		params.put("recordedAt", Timestamp.from(recordedAt));
		jdbcClient.sql("""
				INSERT INTO app.constraint_policy_version (
				    id, user_id, scope_type, portfolio_id, account_id,
				    version_number, maximum_position_count, maximum_position_weight,
				    maximum_sector_weight, minimum_cash_weight,
				    maximum_leverage_ratio, maximum_speculative_weight,
				    idempotency_key, request_hash, effective_at, recorded_at
				) VALUES (
				    :id, :userId, :scopeType, :portfolioId, :accountId,
				    :version, :maximumPositionCount, :maximumPositionWeight,
				    :maximumSectorWeight, :minimumCashWeight,
				    :maximumLeverageRatio, :maximumSpeculativeWeight,
				    :idempotencyKey, :requestHash, :effectiveAt, :recordedAt
				)
				""")
			.params(params).update();

		for (SectorConstraintInput sector : request.sectorConstraints()) {
			Map<String, Object> sectorParams = new HashMap<>();
			sectorParams.put("id", UUID.randomUUID());
			sectorParams.put("userId", user.userId());
			sectorParams.put("policyId", policyId);
			sectorParams.put("taxonomyCode", sector.taxonomyCode());
			sectorParams.put("taxonomyVersion", sector.taxonomyVersion());
			sectorParams.put("sectorCode", sector.sectorCode());
			sectorParams.put("maximumWeight", sector.maximumWeight());
			sectorParams.put("excluded", sector.excluded());
			jdbcClient.sql("""
					INSERT INTO app.sector_constraint (
					    id, user_id, policy_version_id, taxonomy_code,
					    taxonomy_version, sector_code, maximum_weight, excluded
					) VALUES (
					    :id, :userId, :policyId, :taxonomyCode,
					    :taxonomyVersion, :sectorCode, :maximumWeight, :excluded
					)
					""")
				.params(sectorParams).update();
		}
		audit(user, "CONSTRAINT_POLICY_RECORDED", "constraint_policy_version",
				policyId, "SUCCEEDED");
		return new ConstraintPolicyResponse(
				policyId, request.scopeType(), request.portfolioId(),
				request.accountId(), version, proposed, request.effectiveAt(),
				recordedAt, request.sectorConstraints());
	}

	public ResolvedPortfolioConstraints resolvePortfolioConstraints(
			CurrentUser user, UUID portfolioId) {
		requireOwnedPortfolio(user.userId(), portfolioId);
		ConstraintValues userValues = latestPolicyValues(
				user.userId(), ConstraintScope.USER, null);
		ConstraintValues portfolioValues = ConstraintPolicyRules.resolve(
				userValues, latestPolicyValues(
				user.userId(), ConstraintScope.PORTFOLIO, portfolioId));
		List<ResolvedAccountConstraints> accounts = accountIds(user.userId(), portfolioId)
			.stream()
			.map(accountId -> new ResolvedAccountConstraints(
					accountId,
					ConstraintPolicyRules.resolve(portfolioValues, latestPolicyValues(
							user.userId(), ConstraintScope.ACCOUNT, accountId))))
			.toList();
		return new ResolvedPortfolioConstraints(portfolioId, portfolioValues, accounts);
	}

	private InvestmentProfileResponse findProfileByIdempotency(
			UUID userId, String idempotencyKey) {
		return jdbcClient.sql("""
				SELECT id, version_number, investment_approach, primary_horizon,
				       risk_tolerance, liquidity_needs, notes, effective_at, recorded_at
				FROM app.investment_profile_version
				WHERE user_id = :userId AND idempotency_key = :idempotencyKey
				""")
			.params(Map.of("userId", userId, "idempotencyKey", idempotencyKey))
			.query((rs, rowNumber) -> profileResponse(userId, rs))
			.optional().orElse(null);
	}

	private InvestmentProfileResponse profileResponse(UUID userId, java.sql.ResultSet rs)
			throws java.sql.SQLException {
		UUID profileId = rs.getObject("id", UUID.class);
		List<GoalInput> goals = jdbcClient.sql("""
				SELECT goal_type, priority, target_date, target_amount, currency, description
				FROM app.investment_goal
				WHERE user_id = :userId AND profile_version_id = :profileId
				ORDER BY priority, id
				""")
			.params(Map.of("userId", userId, "profileId", profileId))
			.query((goalRs, rowNumber) -> new GoalInput(
					goalRs.getString("goal_type"),
					goalRs.getInt("priority"),
					goalRs.getObject("target_date", java.time.LocalDate.class),
					goalRs.getBigDecimal("target_amount"),
					goalRs.getString("currency"),
					goalRs.getString("description")))
			.list();
		List<SectorPreferenceInput> preferences = jdbcClient.sql("""
				SELECT taxonomy_code, taxonomy_version, sector_code, preference
				FROM app.sector_preference
				WHERE user_id = :userId AND profile_version_id = :profileId
				ORDER BY taxonomy_code, taxonomy_version, sector_code
				""")
			.params(Map.of("userId", userId, "profileId", profileId))
			.query((preferenceRs, rowNumber) -> new SectorPreferenceInput(
					preferenceRs.getString("taxonomy_code"),
					preferenceRs.getString("taxonomy_version"),
					preferenceRs.getString("sector_code"),
					SectorPreferenceValue.valueOf(preferenceRs.getString("preference"))))
			.list();
		return new InvestmentProfileResponse(
				profileId,
				rs.getInt("version_number"),
				InvestmentApproach.valueOf(rs.getString("investment_approach")),
				InvestmentHorizon.valueOf(rs.getString("primary_horizon")),
				RiskTolerance.valueOf(rs.getString("risk_tolerance")),
				rs.getString("liquidity_needs"),
				rs.getString("notes"),
				rs.getTimestamp("effective_at").toInstant(),
				rs.getTimestamp("recorded_at").toInstant(),
				goals,
				preferences);
	}

	private LiabilityBalanceAccepted findLiabilityBalance(
			UUID userId, UUID liabilityId, String idempotencyKey) {
		return jdbcClient.sql("""
				SELECT id, liability_id, as_of_time, balance,
				       annual_interest_rate, recorded_at
				FROM app.liability_balance_snapshot
				WHERE user_id = :userId AND liability_id = :liabilityId
				  AND idempotency_key = :idempotencyKey
				""")
			.params(Map.of(
					"userId", userId,
					"liabilityId", liabilityId,
					"idempotencyKey", idempotencyKey))
			.query((rs, rowNumber) -> new LiabilityBalanceAccepted(
					rs.getObject("id", UUID.class),
					rs.getObject("liability_id", UUID.class),
					rs.getTimestamp("as_of_time").toInstant(),
					rs.getBigDecimal("balance"),
					rs.getBigDecimal("annual_interest_rate"),
					rs.getTimestamp("recorded_at").toInstant()))
			.optional().orElse(null);
	}

	private ConstraintPolicyResponse findPolicyByIdempotency(
			UUID userId, String idempotencyKey) {
		return jdbcClient.sql("""
				SELECT *
				FROM app.constraint_policy_version
				WHERE user_id = :userId AND idempotency_key = :idempotencyKey
				""")
			.params(Map.of("userId", userId, "idempotencyKey", idempotencyKey))
			.query((rs, rowNumber) -> policyResponse(userId, rs))
			.optional().orElse(null);
	}

	private ConstraintPolicyResponse policyResponse(UUID userId, java.sql.ResultSet rs)
			throws java.sql.SQLException {
		UUID policyId = rs.getObject("id", UUID.class);
		List<SectorConstraintInput> sectors = jdbcClient.sql("""
				SELECT taxonomy_code, taxonomy_version, sector_code,
				       maximum_weight, excluded
				FROM app.sector_constraint
				WHERE user_id = :userId AND policy_version_id = :policyId
				ORDER BY taxonomy_code, taxonomy_version, sector_code
				""")
			.params(Map.of("userId", userId, "policyId", policyId))
			.query((sectorRs, rowNumber) -> new SectorConstraintInput(
					sectorRs.getString("taxonomy_code"),
					sectorRs.getString("taxonomy_version"),
					sectorRs.getString("sector_code"),
					sectorRs.getBigDecimal("maximum_weight"),
					sectorRs.getBoolean("excluded")))
			.list();
		return new ConstraintPolicyResponse(
				policyId,
				ConstraintScope.valueOf(rs.getString("scope_type")),
				rs.getObject("portfolio_id", UUID.class),
				rs.getObject("account_id", UUID.class),
				rs.getInt("version_number"),
				new ConstraintValues(
						(Integer) rs.getObject("maximum_position_count"),
						rs.getBigDecimal("maximum_position_weight"),
						rs.getBigDecimal("maximum_sector_weight"),
						rs.getBigDecimal("minimum_cash_weight"),
						rs.getBigDecimal("maximum_leverage_ratio"),
						rs.getBigDecimal("maximum_speculative_weight")),
				rs.getTimestamp("effective_at").toInstant(),
				rs.getTimestamp("recorded_at").toInstant(),
				sectors);
	}

	private void validateScope(UUID userId, CreateConstraintPolicyRequest request) {
		boolean valid = switch (request.scopeType()) {
			case USER -> request.portfolioId() == null && request.accountId() == null;
			case PORTFOLIO -> request.portfolioId() != null && request.accountId() == null;
			case ACCOUNT -> request.portfolioId() == null && request.accountId() != null;
		};
		if (!valid) {
			throw validation(
					"INVALID_CONSTRAINT_SCOPE",
					"Constraint scope identifiers do not match scopeType.");
		}
		if (request.portfolioId() != null) {
			requireOwnedPortfolio(userId, request.portfolioId());
		}
		if (request.accountId() != null) {
			requireOwnedAccount(userId, request.accountId());
		}
	}

	private ConstraintValues parentConstraints(
			UUID userId, CreateConstraintPolicyRequest request) {
		if (request.scopeType() == ConstraintScope.USER) {
			return null;
		}
		return latestPolicyValues(userId, ConstraintScope.USER, null);
	}

	private ConstraintValues latestPolicyValues(
			UUID userId, ConstraintScope scope, UUID scopeId) {
		String idColumn = switch (scope) {
			case USER -> "portfolio_id IS NULL AND account_id IS NULL";
			case PORTFOLIO -> "portfolio_id = :scopeId";
			case ACCOUNT -> "account_id = :scopeId";
		};
		Map<String, Object> params = new HashMap<>();
		params.put("userId", userId);
		params.put("scopeId", scopeId);
		return jdbcClient.sql("""
				SELECT maximum_position_count, maximum_position_weight,
				       maximum_sector_weight, minimum_cash_weight,
				       maximum_leverage_ratio, maximum_speculative_weight
				FROM app.constraint_policy_version
				WHERE user_id = :userId AND scope_type = :scopeType
				  AND %s
				ORDER BY version_number DESC
				LIMIT 1
				""".formatted(idColumn))
			.params(params)
			.param("scopeType", scope.name())
			.query((rs, rowNumber) -> new ConstraintValues(
					(Integer) rs.getObject("maximum_position_count"),
					rs.getBigDecimal("maximum_position_weight"),
					rs.getBigDecimal("maximum_sector_weight"),
					rs.getBigDecimal("minimum_cash_weight"),
					rs.getBigDecimal("maximum_leverage_ratio"),
					rs.getBigDecimal("maximum_speculative_weight")))
			.optional().orElse(null);
	}

	private int nextPolicyVersion(UUID userId, CreateConstraintPolicyRequest request) {
		Map<String, Object> params = new HashMap<>();
		params.put("userId", userId);
		params.put("scopeType", request.scopeType().name());
		params.put("portfolioId", request.portfolioId());
		params.put("accountId", request.accountId());
		return jdbcClient.sql("""
				SELECT COALESCE(MAX(version_number), 0) + 1
				FROM app.constraint_policy_version
				WHERE user_id = :userId AND scope_type = :scopeType
				  AND portfolio_id IS NOT DISTINCT FROM :portfolioId
				  AND account_id IS NOT DISTINCT FROM :accountId
				""")
			.params(params).query(Integer.class).single();
	}

	private void validateSectorTightening(
			UUID userId, CreateConstraintPolicyRequest request) {
		if (request.scopeType() == ConstraintScope.USER) {
			return;
		}
		List<SectorConstraintInput> parentSectors = latestSectorConstraints(
				userId, ConstraintScope.USER, null);
		for (SectorConstraintInput child : request.sectorConstraints()) {
			parentSectors.stream()
				.filter(parent -> sameSector(parent, child))
				.findFirst()
				.ifPresent(parent -> {
					if (parent.excluded() && !child.excluded()) {
						throw constraintRelaxation();
					}
					requireMaximumTightening(parent.maximumWeight(), child.maximumWeight());
				});
		}
	}

	private List<SectorConstraintInput> latestSectorConstraints(
			UUID userId, ConstraintScope scope, UUID scopeId) {
		String idColumn = switch (scope) {
			case USER -> "policy.portfolio_id IS NULL AND policy.account_id IS NULL";
			case PORTFOLIO -> "policy.portfolio_id = :scopeId";
			case ACCOUNT -> "policy.account_id = :scopeId";
		};
		Map<String, Object> params = new HashMap<>();
		params.put("userId", userId);
		params.put("scopeId", scopeId);
		return jdbcClient.sql("""
				SELECT sector.taxonomy_code, sector.taxonomy_version,
				       sector.sector_code, sector.maximum_weight, sector.excluded
				FROM app.sector_constraint sector
				JOIN app.constraint_policy_version policy
				  ON policy.id = sector.policy_version_id
				 AND policy.user_id = sector.user_id
				WHERE policy.user_id = :userId AND policy.scope_type = :scopeType
				  AND %s
				  AND policy.version_number = (
				      SELECT MAX(latest.version_number)
				      FROM app.constraint_policy_version latest
				      WHERE latest.user_id = policy.user_id
				        AND latest.scope_type = policy.scope_type
				        AND latest.portfolio_id IS NOT DISTINCT FROM policy.portfolio_id
				        AND latest.account_id IS NOT DISTINCT FROM policy.account_id
				  )
				""".formatted(idColumn))
			.params(params)
			.param("scopeType", scope.name())
			.query((rs, rowNumber) -> new SectorConstraintInput(
					rs.getString("taxonomy_code"),
					rs.getString("taxonomy_version"),
					rs.getString("sector_code"),
					rs.getBigDecimal("maximum_weight"),
					rs.getBoolean("excluded")))
			.list();
	}

	private static ConstraintValues values(CreateConstraintPolicyRequest request) {
		return new ConstraintValues(
				request.maximumPositionCount(),
				request.maximumPositionWeight(),
				request.maximumSectorWeight(),
				request.minimumCashWeight(),
				request.maximumLeverageRatio(),
				request.maximumSpeculativeWeight());
	}

	private static <T extends Comparable<T>> void requireMaximumTightening(
			T parent, T child) {
		if (parent != null && child != null && child.compareTo(parent) > 0) {
			throw constraintRelaxation();
		}
	}

	private void validateGoals(List<GoalInput> goals) {
		if (goals.stream().map(GoalInput::priority).distinct().count() != goals.size()) {
			throw validation("DUPLICATE_GOAL_PRIORITY", "Goal priorities must be unique.");
		}
		for (GoalInput goal : goals) {
			if ((goal.targetAmount() == null) != (goal.currency() == null)) {
				throw validation(
						"INVALID_GOAL_AMOUNT",
						"Target amount and currency must be supplied together.");
			}
		}
	}

	private void validateSectorPreferences(List<SectorPreferenceInput> preferences) {
		long distinct = preferences.stream()
			.map(preference -> preference.taxonomyCode() + "|"
					+ preference.taxonomyVersion() + "|" + preference.sectorCode())
			.distinct().count();
		if (distinct != preferences.size()) {
			throw validation(
					"DUPLICATE_SECTOR_PREFERENCE",
					"Sector preferences must be unique within a profile version.");
		}
	}

	private void validateSectorConstraints(List<SectorConstraintInput> constraints) {
		long distinct = constraints.stream()
			.map(constraint -> constraint.taxonomyCode() + "|"
					+ constraint.taxonomyVersion() + "|" + constraint.sectorCode())
			.distinct().count();
		if (distinct != constraints.size()) {
			throw validation(
					"DUPLICATE_SECTOR_CONSTRAINT",
					"Sector constraints must be unique within a policy version.");
		}
	}

	private void requireOwnedAccount(UUID userId, UUID accountId) {
		requireOwned("app.investment_account", userId, accountId);
	}

	private void requireOwnedPortfolio(UUID userId, UUID portfolioId) {
		requireOwned("app.portfolio", userId, portfolioId);
	}

	private void requireOwnedLiability(UUID userId, UUID liabilityId) {
		requireOwned("app.financial_liability", userId, liabilityId);
	}

	private void requireOwned(String table, UUID userId, UUID resourceId) {
		int count = jdbcClient.sql("""
				SELECT COUNT(*) FROM %s
				WHERE id = :resourceId AND user_id = :userId AND status = 'ACTIVE'
				""".formatted(table))
			.params(Map.of("resourceId", resourceId, "userId", userId))
			.query(Integer.class).single();
		if (count == 0) {
			throw notFound();
		}
	}

	private List<UUID> accountIds(UUID userId, UUID portfolioId) {
		return jdbcClient.sql("""
				SELECT account_id
				FROM app.portfolio_account_membership
				WHERE portfolio_id = :portfolioId AND user_id = :userId
				ORDER BY account_id
				""")
			.params(Map.of("portfolioId", portfolioId, "userId", userId))
			.query(UUID.class).list();
	}

	private static boolean sameSector(
			SectorConstraintInput first, SectorConstraintInput second) {
		return first.taxonomyCode().equals(second.taxonomyCode())
				&& first.taxonomyVersion().equals(second.taxonomyVersion())
				&& first.sectorCode().equals(second.sectorCode());
	}

	private void audit(
			CurrentUser user, String action, String entityType, UUID entityId, String outcome) {
		jdbcClient.sql("""
				INSERT INTO app.audit_event (
				    user_id, actor_identity_id, correlation_id, action,
				    entity_type, entity_id, outcome
				) VALUES (
				    :userId, :identityId, :correlationId, :action,
				    :entityType, :entityId, :outcome
				)
				""")
			.params(Map.of(
					"userId", user.userId(),
					"identityId", user.identityId(),
					"correlationId", UUID.randomUUID().toString(),
					"action", action,
					"entityType", entityType,
					"entityId", entityId,
					"outcome", outcome))
			.update();
	}

	private static String requestHash(Object request) {
		return sha256(request.toString());
	}

	private static String sha256(String value) {
		try {
			return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
				.digest(value.getBytes(StandardCharsets.UTF_8)));
		}
		catch (NoSuchAlgorithmException exception) {
			throw new IllegalStateException("SHA-256 is unavailable.", exception);
		}
	}

	private static void requireIdempotencyKey(String idempotencyKey) {
		if (idempotencyKey == null || idempotencyKey.isBlank()) {
			throw validation("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.");
		}
	}

	private static void requireMatchingIdempotency(String storedHash, String requestHash) {
		if (!Objects.equals(storedHash, requestHash)) {
			throw new UserContextException(
					"IDEMPOTENCY_KEY_CONFLICT",
					"Idempotency-Key was already used with different content.",
					409);
		}
	}

	private static UserContextException constraintRelaxation() {
		return validation(
				"CONSTRAINT_RELAXATION_NOT_ALLOWED",
				"A more specific policy cannot relax an inherited constraint.");
	}

	private static UserContextException validation(String code, String message) {
		return new UserContextException(code, message, 422);
	}

	private static UserContextException notFound() {
		return new UserContextException(
				"RESOURCE_NOT_FOUND",
				"The requested resource was not found.",
				404);
	}
}
