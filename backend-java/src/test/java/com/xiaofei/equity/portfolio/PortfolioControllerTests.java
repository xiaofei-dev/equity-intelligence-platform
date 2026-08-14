package com.xiaofei.equity.portfolio;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.math.BigDecimal;
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
import org.springframework.mock.web.MockMultipartFile;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;

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

	@Test
	void previewsAndCommitsCsvThroughOwnedAccountWorkflow() throws Exception {
		CurrentUser currentUser = new CurrentUser(USER_ID, IDENTITY_ID, "tester-one");
		UUID accountId = UUID.fromString("00000000-0000-0000-0000-000000000301");
		UUID snapshotId = UUID.fromString("00000000-0000-0000-0000-000000000302");
		byte[] bytes = ("record_type,security_public_id,quantity,average_cost,currency,settled_amount,unsettled_amount,restricted_amount\n"
				+ "CASH,,,,USD,100000,0,0\n").getBytes(java.nio.charset.StandardCharsets.UTF_8);
		MockMultipartFile file = new MockMultipartFile("file", "portfolio.csv", "text/csv", bytes);
		when(identityResolver.resolve("tester-one")).thenReturn(currentUser);
		when(portfolioService.previewCsv(currentUser, accountId, bytes)).thenReturn(
				new PortfolioContracts.CsvSnapshotPreview(PortfolioCsvSnapshotParser.VERSION,
						"0".repeat(64), bytes.length, 1, 1, 0, true, List.of()));
		when(portfolioService.importCsvSnapshot(eq(currentUser), eq(accountId), eq("csv-key"),
				eq("0".repeat(64)), any(), eq(PortfolioContracts.SnapshotCompleteness.COMPLETE), eq(bytes))).thenReturn(
				new PortfolioContracts.SnapshotAccepted(snapshotId, accountId,
						Instant.parse("2026-08-13T20:00:00Z"),
						PortfolioContracts.SnapshotCompleteness.COMPLETE, "1".repeat(64),
						Instant.parse("2026-08-13T20:00:01Z")));

		mockMvc.perform(multipart("/api/v1/me/accounts/{accountId}/snapshots/csv/preview", accountId)
				.file(file).header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isOk()).andExpect(jsonPath("$.valid").value(true))
			.andExpect(jsonPath("$.positionCount").value(0));
		mockMvc.perform(multipart("/api/v1/me/accounts/{accountId}/snapshots/csv", accountId)
				.file(file).param("asOfTime", "2026-08-13T20:00:00Z")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "csv-key").header("Expected-File-Sha256", "0".repeat(64)))
			.andExpect(status().isCreated())
			.andExpect(header().string("Location", "/api/v1/me/accounts/" + accountId + "/snapshots/" + snapshotId));
		verify(portfolioService).previewCsv(currentUser, accountId, bytes);
	}

	@Test
	void readsLatestOwnedSnapshotWithImmutableChildren() throws Exception {
		CurrentUser currentUser = new CurrentUser(USER_ID, IDENTITY_ID, "tester-one");
		UUID accountId = UUID.fromString("00000000-0000-0000-0000-000000000301");
		UUID snapshotId = UUID.fromString("00000000-0000-0000-0000-000000000302");
		when(identityResolver.resolve("tester-one")).thenReturn(currentUser);
		when(portfolioService.latestSnapshot(currentUser, accountId)).thenReturn(
				new PortfolioContracts.SnapshotResponse(snapshotId, accountId,
						Instant.parse("2026-08-13T20:00:00Z"), PortfolioContracts.SnapshotSource.MANUAL,
						"user-entered", PortfolioContracts.SnapshotCompleteness.COMPLETE,
						"1".repeat(64), Instant.parse("2026-08-13T20:00:01Z"),
						Instant.parse("2026-08-13T20:00:01Z"),
						List.of(new PortfolioContracts.CashBalanceInput("USD", new BigDecimal("100000"),
								BigDecimal.ZERO, BigDecimal.ZERO)), List.of()));

		mockMvc.perform(get("/api/v1/me/accounts/{accountId}/snapshots/latest", accountId)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isOk()).andExpect(jsonPath("$.snapshotId").value(snapshotId.toString()))
			.andExpect(jsonPath("$.cashBalances[0].settledAmount").value(100000));
	}
}
