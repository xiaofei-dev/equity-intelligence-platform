package com.xiaofei.equity.usercontext;

import java.util.Map;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ClosedTestIdentityResolver {

	public static final String IDENTITY_HEADER = "X-Test-Identity";

	private final JdbcClient jdbcClient;

	private final boolean enabled;

	private final String issuer;

	public ClosedTestIdentityResolver(
			JdbcClient jdbcClient,
			@Value("${equity.identity.closed-test.enabled:false}") boolean enabled,
			@Value("${equity.identity.closed-test.issuer:equity-local}") String issuer) {
		this.jdbcClient = jdbcClient;
		this.enabled = enabled;
		this.issuer = issuer;
	}

	@Transactional
	public CurrentUser resolve(String externalSubject) {
		if (!enabled) {
			throw new UserContextException(
					"TEST_IDENTITY_MODE_DISABLED",
					"Closed-test identity resolution is disabled.",
					503);
		}
		if (externalSubject == null || externalSubject.isBlank()) {
			throw new UserContextException(
					"USER_CONTEXT_MISSING",
					"An external test identity is required.",
					401);
		}

		CurrentUser currentUser = jdbcClient.sql("""
				SELECT identity.user_id, identity.id
				FROM app.authentication_identity identity
				JOIN app.user_account app_user ON app_user.id = identity.user_id
				WHERE identity.provider = 'LOCAL_TEST'
				  AND identity.issuer = :issuer
				  AND identity.subject = :subject
				  AND app_user.status = 'ACTIVE'
				""")
			.params(Map.of("issuer", issuer, "subject", externalSubject))
			.query((resultSet, rowNumber) -> new CurrentUser(
					resultSet.getObject("user_id", UUID.class),
					resultSet.getObject("id", UUID.class),
					externalSubject))
			.optional()
			.orElseThrow(() -> new UserContextException(
					"USER_CONTEXT_NOT_FOUND",
					"The test identity is not recognized.",
					401));

		jdbcClient.sql("""
				UPDATE app.authentication_identity
				SET last_seen_at = CURRENT_TIMESTAMP
				WHERE id = :identityId AND user_id = :userId
				""")
			.params(Map.of(
					"identityId", currentUser.identityId(),
					"userId", currentUser.userId()))
			.update();
		return currentUser;
	}
}
