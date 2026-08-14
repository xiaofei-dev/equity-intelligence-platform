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
import java.util.UUID;

import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;
import com.xiaofei.equity.usercontext.CurrentUser;
import tools.jackson.databind.json.JsonMapper;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest({UnifiedPortfolioContextController.class, UnifiedPortfolioContextExceptionHandler.class})
class UnifiedPortfolioContextControllerTests {
	private static final UUID USER = UUID.fromString("00000000-0000-4000-8000-000000000001");
	private static final UUID IDENTITY = UUID.fromString("00000000-0000-4000-8000-000000000002");
	private static final UUID PORTFOLIO = UUID.fromString("00000000-0000-4000-8000-000000000003");
	private static final UUID CONTEXT = UUID.fromString("00000000-0000-4000-8000-000000000004");
	private static final UUID REVIEW = UUID.fromString("00000000-0000-4000-8000-000000000005");

	@Autowired MockMvc mvc;
	@MockitoBean ClosedTestIdentityResolver identityResolver;
	@MockitoBean UnifiedPortfolioContextService service;

	@Test
	void legacyCallerValuationContextCreationIsNotRegistered() throws Exception {
		mvc.perform(post("/api/v1/me/portfolios/{portfolioId}/contexts", PORTFOLIO)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "context-1")
				.contentType(MediaType.APPLICATION_JSON).content(validRequest()))
			.andExpect(status().isNotFound());
	}

	@Test
	void latestUsesResolvedIdentityAndStable404() throws Exception {
		CurrentUser user = new CurrentUser(USER, IDENTITY, "tester-one");
		when(identityResolver.resolve("tester-one")).thenReturn(user);
		when(service.latest(user, PORTFOLIO)).thenThrow(new PortfolioContextException(
				"PORTFOLIO_CONTEXT_NOT_FOUND", "The requested portfolio context was not found.", 404));
		mvc.perform(get("/api/v1/me/portfolios/{portfolioId}/contexts/latest", PORTFOLIO)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isNotFound())
			.andExpect(jsonPath("$.code").value("PORTFOLIO_CONTEXT_NOT_FOUND"));
	}

	@Test
	void recordsAHumanReviewWithoutOrderAuthority() throws Exception {
		CurrentUser user = new CurrentUser(USER, IDENTITY, "tester-one");
		when(identityResolver.resolve("tester-one")).thenReturn(user);
		when(service.review(eq(user), eq(PORTFOLIO), eq(CONTEXT), eq("review-1"), any()))
				.thenReturn(new UnifiedPortfolioContracts.ReviewResponse(REVIEW, CONTEXT,
						UnifiedPortfolioContracts.ReviewConclusion.REVIEW_REQUIRED,
						"Concentration requires review.", "sha256:" + "1".repeat(64),
						"2026-08-13T00:00:02Z", "2026-08-13T00:00:02Z"));
		mvc.perform(post("/api/v1/me/portfolios/{portfolioId}/contexts/{contextId}/reviews",
				PORTFOLIO, CONTEXT)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "review-1")
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"conclusion\":\"REVIEW_REQUIRED\",\"rationale\":\"Concentration requires review.\"}"))
			.andExpect(status().isCreated())
			.andExpect(jsonPath("$.reviewId").value(REVIEW.toString()))
			.andExpect(jsonPath("$.conclusion").value("REVIEW_REQUIRED"));
	}

	@Test
	void currentEvidencePublicBoundaryDoesNotForwardCallerSuppliedValues() throws Exception {
		CurrentUser user=new CurrentUser(USER, IDENTITY, "tester-one");when(identityResolver.resolve("tester-one")).thenReturn(user);
		when(service.createCurrentEvidence(eq(user),eq(PORTFOLIO),eq("current-1"),any())).thenReturn(
				new UnifiedPortfolioContracts.CurrentEvidenceContextResponse(
						new UnifiedPortfolioContracts.ContextResponse(CONTEXT,PORTFOLIO,JsonMapper.builder().build().readTree("{}"),null,"2026-08-13T00:00:00Z"),
						REVIEW,"sha256:"+"1".repeat(64)));
		mvc.perform(post("/api/v1/me/portfolios/{portfolioId}/contexts/current-evidence", PORTFOLIO)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER,"tester-one").header("Idempotency-Key","current-1")
				.contentType(MediaType.APPLICATION_JSON).content("""
						{"accountSnapshotIds":["00000000-0000-4000-8000-000000000010"],
						 "constraintPolicyVersionId":"00000000-0000-4000-8000-000000000011",
						 "evidenceReferences":[{"securityId":"00000000-0000-4000-8000-000000000012",
						 "selectionRequestId":"00000000-0000-4000-8000-000000000013","sleeve":"UNASSIGNED",
						 "modelReferenceId":null}],"cashValue":"999999"}
						"""))
			.andExpect(status().isCreated()).andExpect(jsonPath("$.context.contextId").value(CONTEXT.toString()))
			.andExpect(jsonPath("$.evidenceManifestId").value(REVIEW.toString()));
	}

	@Test
	void legacyCallerValuationCannotBypassValidationWithAlternatePayloads() throws Exception {
		mvc.perform(post("/api/v1/me/portfolios/{portfolioId}/contexts", PORTFOLIO)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "context-invalid")
				.contentType(MediaType.APPLICATION_JSON)
				.content(validRequest().replace(
						"\"accountSnapshotIds\":[\"00000000-0000-4000-8000-000000000007\"]",
						"\"accountSnapshotIds\":[]")))
			.andExpect(status().isNotFound());

		mvc.perform(post("/api/v1/me/portfolios/{portfolioId}/contexts", PORTFOLIO)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "context-invalid-2")
				.contentType(MediaType.APPLICATION_JSON)
				.content(validRequest().replace("\"researchUseAllowed\":true,\"referenceId\":\"quant\"",
						"\"referenceId\":\"quant\"")))
			.andExpect(status().isNotFound());
	}

	private static String validRequest() {
		return """
				{"accountSnapshotIds":["00000000-0000-4000-8000-000000000007"],
				"constraintPolicyVersionId":"00000000-0000-4000-8000-000000000006","riskInput":{
				"contractVersion":"unified-portfolio-risk-input-v1.0.0",
				"asOfTime":"2026-08-13T00:00:00Z","baseCurrency":"USD",
				"cashValue":"100000","liabilityValue":"0","positions":[],
				"sleeveEvidence":[
				 {"sleeve":"LONG_TERM_CORE","modelVersion":"FUNDAMENTAL-VALUE-v1.0.0",
				  "evidenceLabel":"NOT_VALIDATED","researchUseAllowed":true,"referenceId":"fv",
				  "referenceHash":"sha256:1111111111111111111111111111111111111111111111111111111111111111"},
				 {"sleeve":"QUANT_TRADING","modelVersion":"QUANT-TRADING-v1.1.0",
				  "evidenceLabel":"NOT_VALIDATED","researchUseAllowed":true,"referenceId":"quant",
				  "referenceHash":"sha256:2222222222222222222222222222222222222222222222222222222222222222"}],
				"constraints":{"maximumPositionWeight":"0.2","maximumSectorWeight":"0.3",
				"minimumCashWeight":"0.1","maximumLeverageRatio":"0"}}}
				""";
	}
}
