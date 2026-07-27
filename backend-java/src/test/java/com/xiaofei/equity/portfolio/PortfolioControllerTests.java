package com.xiaofei.equity.portfolio;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;
import com.xiaofei.equity.usercontext.CurrentUser;
import com.xiaofei.equity.usercontext.UserContextException;
import com.xiaofei.equity.usercontext.UserContextExceptionHandler;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest({
	PortfolioController.class,
	UserContextExceptionHandler.class
})
class PortfolioControllerTests {

	private static final UUID USER_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000101");

	private static final UUID IDENTITY_ID = UUID.fromString(
			"00000000-0000-0000-0000-000000000201");

	@Autowired
	private MockMvc mockMvc;

	@MockitoBean
	private ClosedTestIdentityResolver identityResolver;

	@MockitoBean
	private PortfolioService portfolioService;

	@Test
	void listsOnlyResourcesForResolvedIdentity() throws Exception {
		CurrentUser currentUser = new CurrentUser(USER_ID, IDENTITY_ID, "tester-one");
		UUID accountId = UUID.fromString("00000000-0000-0000-0000-000000000301");
		when(identityResolver.resolve("tester-one")).thenReturn(currentUser);
		when(portfolioService.listAccounts(currentUser)).thenReturn(List.of(
				new PortfolioContracts.AccountResponse(
						accountId,
						"Primary Account",
						PortfolioContracts.AccountType.REAL,
						"USD",
						"ACTIVE",
						Instant.parse("2026-07-26T12:00:00Z"))));

		mockMvc.perform(get("/api/v1/me/accounts")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$[0].id").value(accountId.toString()))
			.andExpect(jsonPath("$[0].name").value("Primary Account"));
	}

	@Test
	void createsAccountWithoutAcceptingAUserIdentifier() throws Exception {
		CurrentUser currentUser = new CurrentUser(USER_ID, IDENTITY_ID, "tester-one");
		UUID accountId = UUID.fromString("00000000-0000-0000-0000-000000000301");
		when(identityResolver.resolve("tester-one")).thenReturn(currentUser);
		when(portfolioService.createAccount(eq(currentUser), any()))
			.thenReturn(new PortfolioContracts.AccountResponse(
					accountId,
					"Primary Account",
					PortfolioContracts.AccountType.REAL,
					"USD",
					"ACTIVE",
					Instant.parse("2026-07-26T12:00:00Z")));

		mockMvc.perform(post("/api/v1/me/accounts")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.contentType(MediaType.APPLICATION_JSON)
				.content("""
						{
						  "name": "Primary Account",
						  "accountType": "REAL",
						  "baseCurrency": "USD"
						}
						"""))
			.andExpect(status().isCreated())
			.andExpect(header().string(
					"Location", "/api/v1/me/accounts/" + accountId))
			.andExpect(jsonPath("$.id").value(accountId.toString()));
	}

	@Test
	void returnsStableErrorForUnknownIdentity() throws Exception {
		when(identityResolver.resolve("unknown")).thenThrow(new UserContextException(
				"USER_CONTEXT_NOT_FOUND",
				"The test identity is not recognized.",
				401));

		mockMvc.perform(get("/api/v1/me/accounts")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "unknown"))
			.andExpect(status().isUnauthorized())
			.andExpect(jsonPath("$.code").value("USER_CONTEXT_NOT_FOUND"));
	}

	@Test
	void requiresIdempotencyKeyForSnapshotEndpoint() throws Exception {
		CurrentUser currentUser = new CurrentUser(USER_ID, IDENTITY_ID, "tester-one");
		when(identityResolver.resolve("tester-one")).thenReturn(currentUser);

		mockMvc.perform(post("/api/v1/me/accounts/{accountId}/snapshots", UUID.randomUUID())
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.contentType(MediaType.APPLICATION_JSON)
				.content("""
						{
						  "asOfTime": "2026-07-26T12:00:00Z",
						  "sourceType": "MANUAL",
						  "completeness": "COMPLETE",
						  "cashBalances": [],
						  "positions": []
						}
						"""))
			.andExpect(status().isBadRequest());
	}
}
