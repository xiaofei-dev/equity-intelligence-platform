package com.xiaofei.equity.fundamentalvalue;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import com.xiaofei.equity.fundamentalvalue.CurrentFundamentalValueContract.AssessmentResponse;
import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;
import com.xiaofei.equity.usercontext.CurrentUser;
import com.xiaofei.equity.usercontext.UserContextExceptionHandler;

import tools.jackson.databind.json.JsonMapper;

@WebMvcTest({
	CurrentFundamentalValueController.class,
	CurrentFundamentalValueExceptionHandler.class,
	UserContextExceptionHandler.class
})
class CurrentFundamentalValueControllerTests {

	private static final UUID ID = UUID.fromString("48c10755-be38-55da-b154-1be736dc3cbc");

	@Autowired
	private MockMvc mockMvc;

	@MockitoBean
	private ClosedTestIdentityResolver identityResolver;

	@MockitoBean
	private CurrentFundamentalValueService service;

	@BeforeEach
	void resolveIdentity() {
		when(identityResolver.resolve("tester-one")).thenReturn(new CurrentUser(
				UUID.randomUUID(), UUID.randomUUID(), "tester-one"));
	}

	@Test
	void exposesOnlyTheAuthenticatedReadOnlyAssessmentRoute() throws Exception {
		Path fixture = Path.of("..", "contracts", "fundamental-value-v1",
				"internal-current-assessment-response.example.json");
		AssessmentResponse response = JsonMapper.builder().build().readValue(
				Files.readString(fixture), AssessmentResponse.class);
		when(service.read(ID)).thenReturn(response);

		mockMvc.perform(get("/api/v1/fundamental-value/current-assessments/{id}", ID)
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.modelEvidenceLabel").value("NOT_VALIDATED"))
			.andExpect(jsonPath("$.deterministicActionAuthorized").value(false))
			.andExpect(jsonPath("$.finalPortfolioWeightAuthorized").value(false))
			.andExpect(jsonPath("$.sourceSeals").doesNotExist())
			.andExpect(jsonPath("$.inputs").doesNotExist());
	}

	@Test
	void rejectsMissingIdentityAndMalformedAssessmentId() throws Exception {
		mockMvc.perform(get("/api/v1/fundamental-value/current-assessments/{id}", ID))
			.andExpect(status().isBadRequest());
		mockMvc.perform(get("/api/v1/fundamental-value/current-assessments/not-a-uuid")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.code").value(
					"INVALID_CURRENT_FUNDAMENTAL_VALUE_IDENTIFIER"));
	}

	@Test
	void exposesLatestBySymbolWithoutAClientKnownAssessmentId() throws Exception {
		Path fixture = Path.of("..", "contracts", "fundamental-value-v1",
				"internal-current-assessment-response.example.json");
		AssessmentResponse response = JsonMapper.builder().build().readValue(
				Files.readString(fixture), AssessmentResponse.class);
		when(service.readLatest("TEST")).thenReturn(response);
		mockMvc.perform(get("/api/v1/fundamental-value/current-assessments/latest/TEST")
				.header(ClosedTestIdentityResolver.IDENTITY_HEADER, "tester-one"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.identity.ticker").value("TEST"));
	}
}
