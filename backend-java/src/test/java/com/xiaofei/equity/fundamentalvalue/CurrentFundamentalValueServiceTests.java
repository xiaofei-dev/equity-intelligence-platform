package com.xiaofei.equity.fundamentalvalue;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;

import org.junit.jupiter.api.Test;

import com.xiaofei.equity.fundamentalvalue.CurrentFundamentalValueContract.InternalAssessment;

import tools.jackson.databind.json.JsonMapper;

class CurrentFundamentalValueServiceTests {

	private static final Path FIXTURE = Path.of("..", "contracts", "fundamental-value-v1",
			"internal-current-assessment-response.example.json");
	private static final JsonMapper MAPPER = JsonMapper.builder().build();

	@Test
	void validatesAndDefensivelyProjectsTheCrossLanguageFixture() throws Exception {
		InternalAssessment internal = MAPPER.readValue(Files.readString(FIXTURE),
				InternalAssessment.class);
		CurrentFundamentalValueAnalyticsClient client = org.mockito.Mockito.mock(
				CurrentFundamentalValueAnalyticsClient.class);
		when(client.read(internal.assessmentId())).thenReturn(internal);

		var response = new CurrentFundamentalValueService(client).read(internal.assessmentId());
		assertThat(response.modelEvidenceLabel()).isEqualTo("NOT_VALIDATED");
		assertThat(response.investmentView()).isNotSameAs(internal.investmentView());
		assertThat(response.deterministicActionAuthorized()).isFalse();
		assertThat(response.deterministicRankingAuthorized()).isFalse();
		assertThat(response.finalPortfolioWeightAuthorized()).isFalse();
		assertThat(response.automaticBrokerageExecutionAuthorized()).isFalse();
	}

	@Test
	void bindsLatestReadbackToTheRequestedSymbol() throws Exception {
		InternalAssessment internal = MAPPER.readValue(Files.readString(FIXTURE),
				InternalAssessment.class);
		CurrentFundamentalValueAnalyticsClient client = org.mockito.Mockito.mock(
				CurrentFundamentalValueAnalyticsClient.class);
		when(client.readLatest("TEST")).thenReturn(internal);
		assertThat(new CurrentFundamentalValueService(client).readLatest("TEST")
				.identity().ticker()).isEqualTo("TEST");
		when(client.readLatest("GOOG")).thenReturn(internal);
		assertThatThrownBy(() -> new CurrentFundamentalValueService(client).readLatest("GOOG"))
				.isInstanceOfSatisfying(FundamentalValueGatewayException.class,
						error -> assertThat(error.code()).isEqualTo(
								"CURRENT_FUNDAMENTAL_VALUE_UPSTREAM_CONTRACT_INVALID"));
	}

	@Test
	void rejectsIdentityHashAuthorityAndNestedEconomicDrift() throws Exception {
		String original = Files.readString(FIXTURE);
		for (String changed : new String[] {
				original.replace("48c10755-be38-55da-b154-1be736dc3cbc",
						"10000000-0000-4000-8000-000000000099"),
				original.replace("\"deterministicActionAuthorized\": false",
						"\"deterministicActionAuthorized\": true"),
				original.replace("\"score\": \"76.91\"", "\"score\": \"101\""),
				original.replace("\"central\": \"120\", \"high\": \"155\"",
						"\"central\": \"160\", \"high\": \"155\"") }) {
			InternalAssessment invalid = MAPPER.readValue(changed, InternalAssessment.class);
			CurrentFundamentalValueAnalyticsClient client = org.mockito.Mockito.mock(
					CurrentFundamentalValueAnalyticsClient.class);
			UUID requested = UUID.fromString("48c10755-be38-55da-b154-1be736dc3cbc");
			when(client.read(requested)).thenReturn(invalid);
			assertThatThrownBy(() -> new CurrentFundamentalValueService(client).read(requested))
					.isInstanceOfSatisfying(FundamentalValueGatewayException.class,
							error -> assertThat(error.code()).isEqualTo(
								"CURRENT_FUNDAMENTAL_VALUE_UPSTREAM_CONTRACT_INVALID"));
		}
	}
}
