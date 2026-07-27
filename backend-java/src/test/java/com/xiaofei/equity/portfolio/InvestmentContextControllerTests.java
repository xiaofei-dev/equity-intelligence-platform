package com.xiaofei.equity.portfolio;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
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
import com.xiaofei.equity.usercontext.UserContextExceptionHandler;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest({
	InvestmentContextController.class,
	UserContextExceptionHandler.class
})
class InvestmentContextControllerTests {

	private static final CurrentUser CURRENT_USER = new CurrentUser(
			UUID.fromString("00000000-0000-0000-0000-000000000101"),
			UUID.fromString("00000000-0000-0000-0000-000000000201"),
			"tester-one");

	@Autowired
	private MockMvc mockMvc;

	@MockitoBean
	private ClosedTestIdentityResolver identityResolver;

	@MockitoBean
	private InvestmentContextService investmentContextService;

	@Test
	void createsAnImmutableInvestmentProfileVersion() throws Exception {
		UUID profileId = UUID.fromString("00000000-0000-0000-0000-000000000501");
		when(identityResolver.resolve("tester-one")).thenReturn(CURRENT_USER);
		when(investmentContextService.createProfile(
				eq(CURRENT_USER), eq("profile-v1"), any()))
			.thenReturn(new InvestmentContextContracts.InvestmentProfileResponse(
					profileId,
					1,
					InvestmentContextContracts.InvestmentApproach.DEFENSIVE,
					InvestmentContextContracts.InvestmentHorizon.LONG_TERM,
					InvestmentContextContracts.RiskTolerance.MODERATE,
					null,
					null,
					Instant.parse("2026-07-26T20:00:00Z"),
					Instant.parse("2026-07-26T20:00:01Z"),
					List.of(),
					List.of()));

		mockMvc.perform(post("/api/v1/me/investment-profile")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "profile-v1")
				.contentType(MediaType.APPLICATION_JSON)
				.content("""
						{
						  "investmentApproach": "DEFENSIVE",
						  "primaryHorizon": "LONG_TERM",
						  "riskTolerance": "MODERATE",
						  "effectiveAt": "2026-07-26T20:00:00Z",
						  "goals": [],
						  "sectorPreferences": []
						}
						"""))
			.andExpect(status().isCreated())
			.andExpect(jsonPath("$.id").value(profileId.toString()))
			.andExpect(jsonPath("$.versionNumber").value(1));
	}

	@Test
	void createsAnAccountScopedLiabilityForTheResolvedUser() throws Exception {
		UUID accountId = UUID.fromString("00000000-0000-0000-0000-000000000301");
		UUID liabilityId = UUID.fromString("00000000-0000-0000-0000-000000000801");
		when(identityResolver.resolve("tester-one")).thenReturn(CURRENT_USER);
		when(investmentContextService.createLiability(eq(CURRENT_USER), any()))
			.thenReturn(new InvestmentContextContracts.LiabilityResponse(
					liabilityId,
					accountId,
					"Margin Balance",
					InvestmentContextContracts.LiabilityType.MARGIN,
					"USD",
					"ACTIVE",
					Instant.parse("2026-07-26T20:00:00Z")));

		mockMvc.perform(post("/api/v1/me/liabilities")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.contentType(MediaType.APPLICATION_JSON)
				.content("""
						{
						  "accountId": "%s",
						  "name": "Margin Balance",
						  "liabilityType": "MARGIN",
						  "currency": "USD"
						}
						""".formatted(accountId)))
			.andExpect(status().isCreated())
			.andExpect(jsonPath("$.id").value(liabilityId.toString()))
			.andExpect(jsonPath("$.accountId").value(accountId.toString()));
	}

	@Test
	void returnsResolvedConstraintsForAnOwnedPortfolio() throws Exception {
		UUID portfolioId = UUID.fromString("00000000-0000-0000-0000-000000000401");
		when(identityResolver.resolve("tester-one")).thenReturn(CURRENT_USER);
		when(investmentContextService.resolvePortfolioConstraints(
				CURRENT_USER, portfolioId))
			.thenReturn(new InvestmentContextContracts.ResolvedPortfolioConstraints(
					portfolioId,
					new InvestmentContextContracts.ConstraintValues(
							20, null, null, null, null, null),
					List.of()));

		mockMvc.perform(get("/api/v1/me/constraints/resolved")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.param("portfolioId", portfolioId.toString()))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.portfolioId").value(portfolioId.toString()))
			.andExpect(jsonPath("$.portfolioValues.maximumPositionCount").value(20));
	}
}
