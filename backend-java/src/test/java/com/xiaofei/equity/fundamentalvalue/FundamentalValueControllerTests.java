package com.xiaofei.equity.fundamentalvalue;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import com.xiaofei.equity.fundamentalvalue.FundamentalValueContract.DecisionResponse;
import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;
import com.xiaofei.equity.usercontext.CurrentUser;
import com.xiaofei.equity.usercontext.UserContextExceptionHandler;

@WebMvcTest({
	FundamentalValueController.class,
	FundamentalValueExceptionHandler.class,
	UserContextExceptionHandler.class
})
class FundamentalValueControllerTests {

	private static final UUID ASSEMBLY_ID = UUID.fromString(
			"10000000-0000-4000-8000-000000000001");

	@Autowired
	private MockMvc mockMvc;

	@MockitoBean
	private ClosedTestIdentityResolver identityResolver;

	@MockitoBean
	private FundamentalValueService service;

	@BeforeEach
	void resolveIdentity() {
		when(identityResolver.resolve("tester-one")).thenReturn(new CurrentUser(
				UUID.randomUUID(), UUID.randomUUID(), "tester-one"));
	}

	@Test
	void publishesMissingAsSuccessfulNonInvestmentDecision() throws Exception {
		when(service.create(any(), any())).thenReturn(missing());
		mockMvc.perform(post("/api/v1/fundamental-value/decisions")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "fv-1")
				.contentType(MediaType.APPLICATION_JSON)
				.content("""
						{
						  "contractVersion":"internal-fundamental-value-command-v1.0.0",
						  "routingId":"10000000-0000-4000-8000-000000000002",
						  "classificationRequestId":"10000000-0000-4000-8000-000000000003",
						  "operandRequestIds":[],
						  "projectionYears":5
						}
						"""))
			.andExpect(status().isCreated())
			.andExpect(header().string("Location",
					"/api/v1/fundamental-value/decisions/" + ASSEMBLY_ID))
			.andExpect(jsonPath("$.state").value("MISSING"))
			.andExpect(jsonPath("$.coreInvocationAuthorized").value(false))
			.andExpect(jsonPath("$.finalPortfolioWeightAuthorized").value(false));
	}

	@Test
	void requiresIdentityAndIdempotencyHeaders() throws Exception {
		mockMvc.perform(post("/api/v1/fundamental-value/decisions")
				.contentType(MediaType.APPLICATION_JSON).content("{}"))
			.andExpect(status().isBadRequest());
	}

	@Test
	void rejectsUnknownProviderNativePublicRequestField() throws Exception {
		mockMvc.perform(post("/api/v1/fundamental-value/decisions")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "fv-unknown")
				.contentType(MediaType.APPLICATION_JSON)
				.content("""
						{
						  "contractVersion":"internal-fundamental-value-command-v1.0.0",
						  "routingId":"10000000-0000-4000-8000-000000000002",
						  "classificationRequestId":"10000000-0000-4000-8000-000000000003",
						  "operandRequestIds":[],
						  "projectionYears":5,
						  "providerCode":"forbidden"
						}
						"""))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.code").value("INVALID_FUNDAMENTAL_VALUE_REQUEST"));
		verifyNoInteractions(service);
	}

	@Test
	void projectionYearsUsesExactIntegerWireSemantics() throws Exception {
		for (String raw : List.of("\"5\"", "5.0", "true", "null", "2", "11",
				"999999999999999999999999999999999")) {
			mockMvc.perform(post("/api/v1/fundamental-value/decisions")
					.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
					.header("Idempotency-Key", "fv-years")
					.contentType(MediaType.APPLICATION_JSON)
					.content(requestJson(raw, null, null)))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.code").value("INVALID_FUNDAMENTAL_VALUE_REQUEST"));
		}
		mockMvc.perform(post("/api/v1/fundamental-value/decisions")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
				.header("Idempotency-Key", "fv-years-missing")
				.contentType(MediaType.APPLICATION_JSON)
				.content(requestJson(null, null, null)))
			.andExpect(status().isBadRequest());
	}

	@Test
	void canonicalProjectionYearBoundariesPassPublicWireParsing() throws Exception {
		when(service.create(any(), any())).thenReturn(missing());
		for (String raw : List.of("3", "10")) {
			mockMvc.perform(post("/api/v1/fundamental-value/decisions")
					.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
					.header("Idempotency-Key", "fv-years-" + raw)
					.contentType(MediaType.APPLICATION_JSON)
					.content(requestJson(raw, null, null)))
				.andExpect(status().isCreated());
		}
	}

	@Test
	void durableIdsRequireCanonicalLowercaseHyphenatedStrings() throws Exception {
		List<String> invalid = List.of(
				"\"10000000-0000-4000-8000-0000000000AA\"",
				"\"{10000000-0000-4000-8000-0000000000aa}\"",
				"\"100000000000400080000000000000aa\"",
				"\" 10000000-0000-4000-8000-0000000000aa \"",
				"7", "true", "null");
		for (String raw : invalid) {
			mockMvc.perform(post("/api/v1/fundamental-value/decisions")
					.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
					.header("Idempotency-Key", "fv-id")
					.contentType(MediaType.APPLICATION_JSON)
					.content(requestJson("5", raw, null)))
				.andExpect(status().isBadRequest());
			mockMvc.perform(post("/api/v1/fundamental-value/decisions")
					.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
					.header("Idempotency-Key", "fv-classification-id")
					.contentType(MediaType.APPLICATION_JSON)
					.content(requestJson("5", null, null).replace(
							"\"10000000-0000-4000-8000-000000000003\"", raw)))
				.andExpect(status().isBadRequest());
			mockMvc.perform(post("/api/v1/fundamental-value/decisions")
					.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one")
					.header("Idempotency-Key", "fv-operand-id")
					.contentType(MediaType.APPLICATION_JSON)
					.content(requestJson("5", null, raw)))
				.andExpect(status().isBadRequest());
		}
	}

	@Test
	void publicReadRequiresCanonicalPathIdAndPreservesMissingAsNotFound() throws Exception {
		for (String raw : List.of(
				"10000000-0000-4000-8000-0000000000AA",
				"100000000000400080000000000000aa", "1-1-1-1-1", "7")) {
			mockMvc.perform(get("/api/v1/fundamental-value/decisions/" + raw)
					.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
				.andExpect(status().isBadRequest());
		}
		when(service.read(ASSEMBLY_ID)).thenThrow(new FundamentalValueGatewayException(
				"FUNDAMENTAL_VALUE_DECISION_NOT_FOUND",
				"The Fundamental Value decision was not found.", 404));
		mockMvc.perform(get("/api/v1/fundamental-value/decisions/" + ASSEMBLY_ID)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isNotFound())
			.andExpect(jsonPath("$.code").value("FUNDAMENTAL_VALUE_DECISION_NOT_FOUND"));
	}

	@Test
	void publicReadProjectsTheCompleteDurableIdentityEnvelope() throws Exception {
		when(service.read(ASSEMBLY_ID)).thenReturn(missing());
		mockMvc.perform(get("/api/v1/fundamental-value/decisions/" + ASSEMBLY_ID)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.contractVersion").value(
					"internal-fundamental-value-result-v1.1.0"))
			.andExpect(jsonPath("$.identity.securityId").value(
					"10000000-0000-4000-8000-000000000010"))
			.andExpect(jsonPath("$.identity.companyId").value(
					"10000000-0000-4000-8000-000000000011"))
			.andExpect(jsonPath("$.identity.instrumentId").value(
					"10000000-0000-4000-8000-000000000012"))
			.andExpect(jsonPath("$.identity.shareClassId").value(
					"10000000-0000-4000-8000-000000000013"))
			.andExpect(jsonPath("$.identity.listingId").value(
					"10000000-0000-4000-8000-000000000014"))
			.andExpect(jsonPath("$.identity.tickerAssignmentId").value(
					"10000000-0000-4000-8000-000000000015"))
			.andExpect(jsonPath("$.identity.ticker").value("TEST"))
			.andExpect(jsonPath("$.identity.mic").value("XNYS"))
			.andExpect(jsonPath("$.identity.currency").value("USD"))
			.andExpect(jsonPath("$.identity.completedSessionDate").value("2026-07-29"));
	}

	private static String requestJson(String years, String routingId, String operandId) {
		String routing = routingId == null
				? "\"10000000-0000-4000-8000-000000000002\"" : routingId;
		String operands = operandId == null ? "[]" : "[{\"operandCode\":\"cash\","
				+ "\"requestId\":" + operandId + "}]";
		String yearProperty = years == null ? "" : ",\"projectionYears\":" + years;
		return "{\"contractVersion\":\"internal-fundamental-value-command-v1.0.0\","
				+ "\"routingId\":" + routing + ","
				+ "\"classificationRequestId\":"
				+ "\"10000000-0000-4000-8000-000000000003\","
				+ "\"operandRequestIds\":" + operands + yearProperty + "}";
	}

	private static DecisionResponse missing() {
		return new DecisionResponse(FundamentalValueContract.RESULT_VERSION,
				ASSEMBLY_ID, null, new FundamentalValueContract.DecisionIdentity(
						UUID.fromString("10000000-0000-4000-8000-000000000010"),
						UUID.fromString("10000000-0000-4000-8000-000000000011"),
						UUID.fromString("10000000-0000-4000-8000-000000000012"),
						UUID.fromString("10000000-0000-4000-8000-000000000013"),
						UUID.fromString("10000000-0000-4000-8000-000000000014"),
						UUID.fromString("10000000-0000-4000-8000-000000000015"),
						"TEST", "XNYS", "USD", LocalDate.parse("2026-07-29")),
				"MISSING", "APPLICABLE", "MATURE_OPERATING_COMPANY",
				List.of("REQUIRED_OPERAND_MISSING"), false,
				"sha256:" + "a".repeat(64), "sha256:" + "b".repeat(64),
				Instant.parse("2026-07-29T20:05:00Z"),
				Instant.parse("2026-07-29T20:07:00Z"), null, null, null, null,
				false, false);
	}
}
