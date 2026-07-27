package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.PortfolioContracts.*;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.xiaofei.equity.usercontext.CurrentUser;
import com.xiaofei.equity.usercontext.UserContextException;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PortfolioService {

	private final JdbcClient jdbcClient;

	public PortfolioService(JdbcClient jdbcClient) {
		this.jdbcClient = jdbcClient;
	}

	@Transactional
	public AccountResponse createAccount(CurrentUser user, CreateAccountRequest request) {
		if (!"USD".equals(request.baseCurrency())) {
			throw validation("UNSUPPORTED_BASE_CURRENCY", "USD is the only supported account base currency.");
		}
		UUID id = UUID.randomUUID();
		Instant now = Instant.now();
		jdbcClient.sql("""
				INSERT INTO app.investment_account (
				    id, user_id, name, account_type, base_currency, created_at
				) VALUES (
				    :id, :userId, :name, :accountType, :baseCurrency, :createdAt
				)
				""")
			.params(Map.of(
					"id", id,
					"userId", user.userId(),
					"name", request.name(),
					"accountType", request.accountType().name(),
					"baseCurrency", request.baseCurrency(),
					"createdAt", Timestamp.from(now)))
			.update();
		audit(user, "ACCOUNT_CREATED", "investment_account", id, "SUCCEEDED");
		return new AccountResponse(id, request.name(), request.accountType(),
				request.baseCurrency(), "ACTIVE", now);
	}

	public List<AccountResponse> listAccounts(CurrentUser user) {
		return jdbcClient.sql("""
				SELECT id, name, account_type, base_currency, status, created_at
				FROM app.investment_account
				WHERE user_id = :userId
				ORDER BY created_at, id
				""")
			.param("userId", user.userId())
			.query((rs, rowNumber) -> new AccountResponse(
					rs.getObject("id", UUID.class),
					rs.getString("name"),
					AccountType.valueOf(rs.getString("account_type")),
					rs.getString("base_currency"),
					rs.getString("status"),
					rs.getTimestamp("created_at").toInstant()))
			.list();
	}

	@Transactional
	public SnapshotAccepted createSnapshot(
			CurrentUser user,
			UUID accountId,
			String idempotencyKey,
			CreateSnapshotRequest request) {
		requireOwnedAccount(user.userId(), accountId);
		if (idempotencyKey == null || idempotencyKey.isBlank()) {
			throw validation("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.");
		}
		if (request.positions().stream().anyMatch(position -> position.quantity().signum() == 0)) {
			throw validation("ZERO_QUANTITY_POSITION", "Zero-quantity positions must not be stored.");
		}
		long distinctCashCurrencies = request.cashBalances().stream()
			.map(CashBalanceInput::currency).distinct().count();
		long distinctSecurities = request.positions().stream()
			.map(PositionInput::securityPublicId).distinct().count();
		if (distinctCashCurrencies != request.cashBalances().size()
				|| distinctSecurities != request.positions().size()) {
			throw validation("DUPLICATE_SNAPSHOT_ITEM", "Snapshot items must be unique.");
		}

		String contentHash = sha256(canonicalSnapshot(request));
		SnapshotAccepted existing = findSnapshotByIdempotency(user.userId(), accountId, idempotencyKey);
		if (existing != null) {
			if (!existing.contentHash().equals(contentHash)) {
				throw new UserContextException(
						"IDEMPOTENCY_KEY_CONFLICT",
						"Idempotency-Key was already used with different content.",
						409);
			}
			return existing;
		}

		UUID snapshotId = UUID.randomUUID();
		Instant recordedAt = Instant.now();
		jdbcClient.sql("""
				INSERT INTO app.account_snapshot (
				    id, user_id, account_id, as_of_time, source_type,
				    source_reference, completeness, content_hash,
				    idempotency_key, recorded_at
				) VALUES (
				    :id, :userId, :accountId, :asOfTime, :sourceType,
				    :sourceReference, :completeness, :contentHash,
				    :idempotencyKey, :recordedAt
				)
				""")
			.params(Map.ofEntries(
					Map.entry("id", snapshotId),
					Map.entry("userId", user.userId()),
					Map.entry("accountId", accountId),
					Map.entry("asOfTime", Timestamp.from(request.asOfTime())),
					Map.entry("sourceType", request.sourceType().name()),
					Map.entry("sourceReference", nullable(request.sourceReference())),
					Map.entry("completeness", request.completeness().name()),
					Map.entry("contentHash", contentHash),
					Map.entry("idempotencyKey", idempotencyKey),
					Map.entry("recordedAt", Timestamp.from(recordedAt))))
			.update();

		for (CashBalanceInput cash : request.cashBalances()) {
			jdbcClient.sql("""
					INSERT INTO app.cash_balance_snapshot (
					    snapshot_id, user_id, currency, settled_amount,
					    unsettled_amount, restricted_amount
					) VALUES (
					    :snapshotId, :userId, :currency, :settled,
					    :unsettled, :restricted
					)
					""")
				.params(Map.of(
						"snapshotId", snapshotId,
						"userId", user.userId(),
						"currency", cash.currency(),
						"settled", cash.settledAmount(),
						"unsettled", cash.unsettledAmount(),
						"restricted", cash.restrictedAmount()))
				.update();
		}
		for (PositionInput position : request.positions()) {
			jdbcClient.sql("""
					INSERT INTO app.position_snapshot (
					    snapshot_id, user_id, security_public_id, quantity,
					    average_cost, cost_currency
					) VALUES (
					    :snapshotId, :userId, :securityId, :quantity,
					    :averageCost, :costCurrency
					)
					""")
				.params(Map.of(
						"snapshotId", snapshotId,
						"userId", user.userId(),
						"securityId", position.securityPublicId(),
						"quantity", position.quantity(),
						"averageCost", position.averageCost(),
						"costCurrency", position.costCurrency()))
				.update();
		}
		jdbcClient.sql("""
				UPDATE app.account_snapshot
				SET sealed_at = CURRENT_TIMESTAMP
				WHERE id = :snapshotId AND user_id = :userId AND sealed_at IS NULL
				""")
			.params(Map.of("snapshotId", snapshotId, "userId", user.userId()))
			.update();
		audit(user, "ACCOUNT_SNAPSHOT_RECORDED", "account_snapshot", snapshotId, "SUCCEEDED");
		return new SnapshotAccepted(snapshotId, accountId, request.asOfTime(),
				request.completeness(), contentHash, recordedAt);
	}

	@Transactional
	public PortfolioResponse createPortfolio(CurrentUser user, CreatePortfolioRequest request) {
		UUID id = UUID.randomUUID();
		Instant now = Instant.now();
		jdbcClient.sql("""
				INSERT INTO app.portfolio (
				    id, user_id, name, base_currency, created_at
				) VALUES (:id, :userId, :name, :baseCurrency, :createdAt)
				""")
			.params(Map.of(
					"id", id,
					"userId", user.userId(),
					"name", request.name(),
					"baseCurrency", request.baseCurrency(),
					"createdAt", Timestamp.from(now)))
			.update();
		audit(user, "PORTFOLIO_CREATED", "portfolio", id, "SUCCEEDED");
		return new PortfolioResponse(id, request.name(), request.baseCurrency(),
				"ACTIVE", List.of(), now);
	}

	public List<PortfolioResponse> listPortfolios(CurrentUser user) {
		List<PortfolioResponse> portfolios = jdbcClient.sql("""
				SELECT id, name, base_currency, status, created_at
				FROM app.portfolio
				WHERE user_id = :userId
				ORDER BY created_at, id
				""")
			.param("userId", user.userId())
			.query((rs, rowNumber) -> new PortfolioResponse(
					rs.getObject("id", UUID.class),
					rs.getString("name"),
					rs.getString("base_currency"),
					rs.getString("status"),
					List.of(),
					rs.getTimestamp("created_at").toInstant()))
			.list();
		return portfolios.stream()
			.map(portfolio -> new PortfolioResponse(
					portfolio.id(), portfolio.name(), portfolio.baseCurrency(),
					portfolio.status(), accountIds(user.userId(), portfolio.id()),
					portfolio.createdAt()))
			.toList();
	}

	@Transactional
	public PortfolioResponse replacePortfolioAccounts(
			CurrentUser user,
			UUID portfolioId,
			ReplacePortfolioAccountsRequest request) {
		PortfolioResponse portfolio = requireOwnedPortfolio(user.userId(), portfolioId);
		LinkedHashSet<UUID> accountIds = new LinkedHashSet<>(request.accountIds());
		if (accountIds.size() != request.accountIds().size()) {
			throw validation("DUPLICATE_PORTFOLIO_ACCOUNT", "Portfolio accounts must be unique.");
		}
		for (UUID accountId : accountIds) {
			requireOwnedAccount(user.userId(), accountId);
		}
		jdbcClient.sql("""
				DELETE FROM app.portfolio_account_membership
				WHERE portfolio_id = :portfolioId AND user_id = :userId
				""")
			.params(Map.of("portfolioId", portfolioId, "userId", user.userId()))
			.update();
		for (UUID accountId : accountIds) {
			jdbcClient.sql("""
					INSERT INTO app.portfolio_account_membership (
					    portfolio_id, account_id, user_id
					) VALUES (:portfolioId, :accountId, :userId)
					""")
				.params(Map.of(
						"portfolioId", portfolioId,
						"accountId", accountId,
						"userId", user.userId()))
				.update();
		}
		audit(user, "PORTFOLIO_ACCOUNTS_REPLACED", "portfolio", portfolioId, "SUCCEEDED");
		return new PortfolioResponse(
				portfolio.id(), portfolio.name(), portfolio.baseCurrency(),
				portfolio.status(), List.copyOf(accountIds), portfolio.createdAt());
	}

	@Transactional
	public PortfolioLiabilityMembershipResponse replacePortfolioLiabilities(
			CurrentUser user,
			UUID portfolioId,
			ReplacePortfolioLiabilitiesRequest request) {
		requireOwnedPortfolio(user.userId(), portfolioId);
		LinkedHashSet<UUID> liabilityIds = new LinkedHashSet<>(request.liabilityIds());
		if (liabilityIds.size() != request.liabilityIds().size()) {
			throw validation(
					"DUPLICATE_PORTFOLIO_LIABILITY",
					"Portfolio liabilities must be unique.");
		}
		for (UUID liabilityId : liabilityIds) {
			boolean valid = jdbcClient.sql("""
					SELECT COUNT(*)
					FROM app.financial_liability
					WHERE id = :liabilityId AND user_id = :userId
					  AND account_id IS NULL AND status = 'ACTIVE'
					""")
				.params(Map.of("liabilityId", liabilityId, "userId", user.userId()))
				.query(Integer.class).single() > 0;
			if (!valid) {
				throw notFound();
			}
		}
		jdbcClient.sql("""
				DELETE FROM app.portfolio_liability_membership
				WHERE portfolio_id = :portfolioId AND user_id = :userId
				""")
			.params(Map.of("portfolioId", portfolioId, "userId", user.userId()))
			.update();
		for (UUID liabilityId : liabilityIds) {
			jdbcClient.sql("""
					INSERT INTO app.portfolio_liability_membership (
					    portfolio_id, liability_id, user_id
					) VALUES (:portfolioId, :liabilityId, :userId)
					""")
				.params(Map.of(
						"portfolioId", portfolioId,
						"liabilityId", liabilityId,
						"userId", user.userId()))
				.update();
		}
		audit(user, "PORTFOLIO_LIABILITIES_REPLACED", "portfolio", portfolioId, "SUCCEEDED");
		return new PortfolioLiabilityMembershipResponse(
				portfolioId, List.copyOf(liabilityIds));
	}

	@Transactional
	public ScenarioAccepted createScenario(
			CurrentUser user,
			UUID portfolioId,
			String idempotencyKey,
			CreateScenarioRequest request) {
		requireOwnedPortfolio(user.userId(), portfolioId);
		if (idempotencyKey == null || idempotencyKey.isBlank()) {
			throw validation("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.");
		}
		ScenarioAccepted existing = findScenarioByIdempotency(user.userId(), idempotencyKey);
		if (existing != null) {
			if (!existing.portfolioId().equals(portfolioId)
					|| existing.scenarioType() != request.scenarioType()
					|| existing.newMoneyAmount().compareTo(request.newMoneyAmount()) != 0) {
				throw new UserContextException(
						"IDEMPOTENCY_KEY_CONFLICT",
						"Idempotency-Key was already used with different content.",
						409);
			}
			return existing;
		}

		List<UUID> snapshots = latestCompleteAccountSnapshots(user.userId(), portfolioId);
		int accountCount = accountIds(user.userId(), portfolioId).size();
		if (accountCount == 0 || snapshots.size() != accountCount) {
			throw validation(
					"COMPLETE_ACCOUNT_SNAPSHOT_REQUIRED",
					"Every portfolio account requires a complete snapshot.");
		}

		UUID scenarioId = UUID.randomUUID();
		Instant now = Instant.now();
		jdbcClient.sql("""
				INSERT INTO app.portfolio_scenario (
				    id, user_id, portfolio_id, scenario_type, status,
				    new_money_amount, idempotency_key, created_by_identity_id,
				    created_at
				) VALUES (
				    :id, :userId, :portfolioId, :scenarioType, 'DRAFT',
				    :newMoneyAmount, :idempotencyKey, :identityId, :createdAt
				)
				""")
			.params(Map.of(
					"id", scenarioId,
					"userId", user.userId(),
					"portfolioId", portfolioId,
					"scenarioType", request.scenarioType().name(),
					"newMoneyAmount", request.newMoneyAmount(),
					"idempotencyKey", idempotencyKey,
					"identityId", user.identityId(),
					"createdAt", Timestamp.from(now)))
			.update();

		for (UUID snapshotId : snapshots) {
			insertScenarioInputFromTable(
					scenarioId, user.userId(), "ACCOUNT_SNAPSHOT",
					"app.account_snapshot", snapshotId, "content_hash");
		}

		SourceReference profile = latestRequiredSource(
				"""
				SELECT id, request_hash
				FROM app.investment_profile_version
				WHERE user_id = :userId
				ORDER BY version_number DESC
				LIMIT 1
				""",
				Map.of("userId", user.userId()),
				"INVESTMENT_PROFILE_REQUIRED",
				"An investment profile is required before creating a scenario.");
		insertScenarioInput(
				scenarioId, user.userId(), "INVESTMENT_PROFILE",
				profile.id(), profile.hash());

		List<SourceReference> policies = applicableConstraintPolicies(
				user.userId(), portfolioId);
		if (policies.stream().noneMatch(reference -> reference.scopeType().equals("USER"))) {
			throw validation(
					"USER_CONSTRAINT_POLICY_REQUIRED",
					"A user-level constraint policy is required before creating a scenario.");
		}
		for (SourceReference policy : policies) {
			insertScenarioInput(
					scenarioId, user.userId(), "CONSTRAINT_POLICY",
					policy.id(), policy.hash());
		}

		for (SourceReference liability : latestIncludedLiabilityBalances(
				user.userId(), portfolioId)) {
			insertScenarioInput(
					scenarioId, user.userId(), "LIABILITY_SNAPSHOT",
					liability.id(), liability.hash());
		}

		if (request.scenarioType() == ScenarioType.NEW_MONEY) {
			jdbcClient.sql("""
					INSERT INTO app.rebalancing_permission (
					    scenario_id, user_id, security_public_id, permission
					)
					SELECT DISTINCT :scenarioId, :userId, position.security_public_id, 'LOCKED'
					FROM app.portfolio_scenario_input input
					JOIN app.position_snapshot position
					  ON position.snapshot_id = input.source_id
					 AND position.user_id = input.user_id
					WHERE input.scenario_id = :scenarioId
					  AND input.input_type = 'ACCOUNT_SNAPSHOT'
					""")
				.params(Map.of("scenarioId", scenarioId, "userId", user.userId()))
				.update();
		}
		audit(user, "PORTFOLIO_SCENARIO_CREATED", "portfolio_scenario", scenarioId, "SUCCEEDED");
		return new ScenarioAccepted(scenarioId, portfolioId, request.scenarioType(),
				"DRAFT", request.newMoneyAmount(), snapshots.size(), now);
	}

	private void requireOwnedAccount(UUID userId, UUID accountId) {
		boolean exists = jdbcClient.sql("""
				SELECT COUNT(*) FROM app.investment_account
				WHERE id = :accountId AND user_id = :userId AND status = 'ACTIVE'
				""")
			.params(Map.of("accountId", accountId, "userId", userId))
			.query(Integer.class).single() > 0;
		if (!exists) {
			throw notFound();
		}
	}

	private PortfolioResponse requireOwnedPortfolio(UUID userId, UUID portfolioId) {
		return jdbcClient.sql("""
				SELECT id, name, base_currency, status, created_at
				FROM app.portfolio
				WHERE id = :portfolioId AND user_id = :userId AND status = 'ACTIVE'
				""")
			.params(Map.of("portfolioId", portfolioId, "userId", userId))
			.query((rs, rowNumber) -> new PortfolioResponse(
					rs.getObject("id", UUID.class),
					rs.getString("name"),
					rs.getString("base_currency"),
					rs.getString("status"),
					accountIds(userId, portfolioId),
					rs.getTimestamp("created_at").toInstant()))
			.optional()
			.orElseThrow(PortfolioService::notFound);
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

	private List<UUID> latestCompleteAccountSnapshots(UUID userId, UUID portfolioId) {
		return jdbcClient.sql("""
				SELECT snapshot.id
				FROM app.portfolio_account_membership membership
				JOIN LATERAL (
				    SELECT candidate.id
				    FROM app.account_snapshot candidate
				    WHERE candidate.account_id = membership.account_id
				      AND candidate.user_id = membership.user_id
				      AND candidate.completeness = 'COMPLETE'
				      AND candidate.sealed_at IS NOT NULL
				    ORDER BY candidate.as_of_time DESC, candidate.recorded_at DESC
				    LIMIT 1
				) snapshot ON TRUE
				WHERE membership.portfolio_id = :portfolioId
				  AND membership.user_id = :userId
				ORDER BY membership.account_id
				""")
			.params(Map.of("portfolioId", portfolioId, "userId", userId))
			.query(UUID.class).list();
	}

	private List<SourceReference> applicableConstraintPolicies(
			UUID userId, UUID portfolioId) {
		return jdbcClient.sql("""
				WITH applicable AS (
				    SELECT policy.*,
				           ROW_NUMBER() OVER (
				               PARTITION BY policy.scope_type,
				                   COALESCE(policy.portfolio_id, policy.account_id)
				               ORDER BY policy.version_number DESC
				           ) AS version_rank
				    FROM app.constraint_policy_version policy
				    WHERE policy.user_id = :userId
				      AND (
				          policy.scope_type = 'USER'
				          OR (policy.scope_type = 'PORTFOLIO'
				              AND policy.portfolio_id = :portfolioId)
				          OR (policy.scope_type = 'ACCOUNT' AND policy.account_id IN (
				              SELECT membership.account_id
				              FROM app.portfolio_account_membership membership
				              WHERE membership.portfolio_id = :portfolioId
				                AND membership.user_id = :userId
				          ))
				      )
				)
				SELECT id, request_hash, scope_type
				FROM applicable
				WHERE version_rank = 1
				ORDER BY scope_type, id
				""")
			.params(Map.of("userId", userId, "portfolioId", portfolioId))
			.query((rs, rowNumber) -> new SourceReference(
					rs.getObject("id", UUID.class),
					rs.getString("request_hash"),
					rs.getString("scope_type")))
			.list();
	}

	private List<SourceReference> latestIncludedLiabilityBalances(
			UUID userId, UUID portfolioId) {
		return jdbcClient.sql("""
				WITH included_liability AS (
				    SELECT liability.id
				    FROM app.financial_liability liability
				    JOIN app.portfolio_account_membership membership
				      ON membership.account_id = liability.account_id
				     AND membership.user_id = liability.user_id
				    WHERE membership.portfolio_id = :portfolioId
				      AND membership.user_id = :userId
				      AND liability.status = 'ACTIVE'
				    UNION
				    SELECT liability.id
				    FROM app.financial_liability liability
				    JOIN app.portfolio_liability_membership membership
				      ON membership.liability_id = liability.id
				     AND membership.user_id = liability.user_id
				    WHERE membership.portfolio_id = :portfolioId
				      AND membership.user_id = :userId
				      AND liability.account_id IS NULL
				      AND liability.status = 'ACTIVE'
				)
				SELECT included.id AS liability_id, balance.id, balance.request_hash
				FROM included_liability included
				LEFT JOIN LATERAL (
				    SELECT candidate.id, candidate.request_hash
				    FROM app.liability_balance_snapshot candidate
				    WHERE candidate.liability_id = included.id
				      AND candidate.user_id = :userId
				    ORDER BY candidate.as_of_time DESC, candidate.recorded_at DESC
				    LIMIT 1
				) balance ON TRUE
				ORDER BY balance.id
				""")
			.params(Map.of("userId", userId, "portfolioId", portfolioId))
			.query((rs, rowNumber) -> {
				UUID balanceId = rs.getObject("id", UUID.class);
				if (balanceId == null) {
					throw validation(
							"LIABILITY_BALANCE_REQUIRED",
							"Every included liability requires a balance snapshot.");
				}
				return new SourceReference(
						balanceId,
						rs.getString("request_hash"),
						"LIABILITY");
			})
			.list();
	}

	private SourceReference latestRequiredSource(
			String sql,
			Map<String, ?> params,
			String errorCode,
			String errorMessage) {
		return jdbcClient.sql(sql)
			.params(params)
			.query((rs, rowNumber) -> new SourceReference(
					rs.getObject("id", UUID.class),
					rs.getString("request_hash"),
					""))
			.optional()
			.orElseThrow(() -> validation(errorCode, errorMessage));
	}

	private void insertScenarioInputFromTable(
			UUID scenarioId,
			UUID userId,
			String inputType,
			String table,
			UUID sourceId,
			String hashColumn) {
		jdbcClient.sql("""
				INSERT INTO app.portfolio_scenario_input (
				    scenario_id, user_id, input_type, source_id, payload_hash
				)
				SELECT :scenarioId, :userId, :inputType, id, %s
				FROM %s
				WHERE id = :sourceId AND user_id = :userId
				""".formatted(hashColumn, table))
			.params(Map.of(
					"scenarioId", scenarioId,
					"userId", userId,
					"inputType", inputType,
					"sourceId", sourceId))
			.update();
	}

	private void insertScenarioInput(
			UUID scenarioId,
			UUID userId,
			String inputType,
			UUID sourceId,
			String hash) {
		jdbcClient.sql("""
				INSERT INTO app.portfolio_scenario_input (
				    scenario_id, user_id, input_type, source_id, payload_hash
				) VALUES (
				    :scenarioId, :userId, :inputType, :sourceId, :payloadHash
				)
				""")
			.params(Map.of(
					"scenarioId", scenarioId,
					"userId", userId,
					"inputType", inputType,
					"sourceId", sourceId,
					"payloadHash", hash))
			.update();
	}

	private SnapshotAccepted findSnapshotByIdempotency(
			UUID userId, UUID accountId, String idempotencyKey) {
		return jdbcClient.sql("""
				SELECT id, account_id, as_of_time, completeness, content_hash, recorded_at
				FROM app.account_snapshot
				WHERE user_id = :userId
				  AND account_id = :accountId
				  AND idempotency_key = :idempotencyKey
				  AND sealed_at IS NOT NULL
				""")
			.params(Map.of(
					"userId", userId,
					"accountId", accountId,
					"idempotencyKey", idempotencyKey))
			.query((rs, rowNumber) -> new SnapshotAccepted(
					rs.getObject("id", UUID.class),
					rs.getObject("account_id", UUID.class),
					rs.getTimestamp("as_of_time").toInstant(),
					SnapshotCompleteness.valueOf(rs.getString("completeness")),
					rs.getString("content_hash"),
					rs.getTimestamp("recorded_at").toInstant()))
			.optional().orElse(null);
	}

	private ScenarioAccepted findScenarioByIdempotency(UUID userId, String idempotencyKey) {
		return jdbcClient.sql("""
				SELECT id, portfolio_id, scenario_type, status, new_money_amount, created_at,
				       (SELECT COUNT(*) FROM app.portfolio_scenario_input input
				        WHERE input.scenario_id = scenario.id
				          AND input.input_type = 'ACCOUNT_SNAPSHOT') AS snapshot_count
				FROM app.portfolio_scenario scenario
				WHERE user_id = :userId AND idempotency_key = :idempotencyKey
				""")
			.params(Map.of("userId", userId, "idempotencyKey", idempotencyKey))
			.query((rs, rowNumber) -> new ScenarioAccepted(
					rs.getObject("id", UUID.class),
					rs.getObject("portfolio_id", UUID.class),
					ScenarioType.valueOf(rs.getString("scenario_type")),
					rs.getString("status"),
					rs.getBigDecimal("new_money_amount"),
					rs.getInt("snapshot_count"),
					rs.getTimestamp("created_at").toInstant()))
			.optional().orElse(null);
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

	private static String canonicalSnapshot(CreateSnapshotRequest request) {
		StringBuilder canonical = new StringBuilder()
			.append(request.asOfTime()).append('|')
			.append(request.sourceType()).append('|')
			.append(request.sourceReference()).append('|')
			.append(request.completeness());
		request.cashBalances().stream()
			.sorted(java.util.Comparator.comparing(CashBalanceInput::currency))
			.forEach(cash -> canonical.append("|cash:")
				.append(cash.currency()).append(':')
				.append(cash.settledAmount().stripTrailingZeros().toPlainString()).append(':')
				.append(cash.unsettledAmount().stripTrailingZeros().toPlainString()).append(':')
				.append(cash.restrictedAmount().stripTrailingZeros().toPlainString()));
		request.positions().stream()
			.sorted(java.util.Comparator.comparing(position -> position.securityPublicId().toString()))
			.forEach(position -> canonical.append("|position:")
				.append(position.securityPublicId()).append(':')
				.append(position.quantity().stripTrailingZeros().toPlainString()).append(':')
				.append(position.averageCost().stripTrailingZeros().toPlainString()).append(':')
				.append(position.costCurrency()));
		return canonical.toString();
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

	private static Object nullable(Object value) {
		return value == null ? new org.springframework.jdbc.core.SqlParameterValue(
				java.sql.Types.VARCHAR, null) : value;
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

	private record SourceReference(UUID id, String hash, String scopeType) {
	}
}
