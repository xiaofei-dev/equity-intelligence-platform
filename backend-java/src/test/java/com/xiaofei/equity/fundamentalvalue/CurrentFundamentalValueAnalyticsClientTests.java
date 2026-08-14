package com.xiaofei.equity.fundamentalvalue;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withResourceNotFound;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class CurrentFundamentalValueAnalyticsClientTests {

	private static final UUID ID = UUID.fromString("48c10755-be38-55da-b154-1be736dc3cbc");
	private static final Path FIXTURE = Path.of("..", "contracts", "fundamental-value-v1",
			"internal-current-assessment-response.example.json");

	@Test
	void readsOnlyTheCurrentAssessmentInternalPath() throws Exception {
		RestClient.Builder builder = RestClient.builder().baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new CurrentFundamentalValueAnalyticsClient(builder.build());
		server.expect(once(), requestTo("http://analytics.test"
				+ CurrentFundamentalValueAnalyticsClient.INTERNAL_ROOT + "/" + ID))
			.andExpect(method(HttpMethod.GET))
			.andRespond(withSuccess(Files.readString(FIXTURE), MediaType.APPLICATION_JSON));

		assertThat(client.read(ID).modelEvidenceLabel()).isEqualTo("NOT_VALIDATED");
		server.verify();
	}

	@Test
	void readsTheStrictLatestSymbolPath() throws Exception {
		RestClient.Builder builder = RestClient.builder().baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new CurrentFundamentalValueAnalyticsClient(builder.build());
		server.expect(once(), requestTo("http://analytics.test"
				+ CurrentFundamentalValueAnalyticsClient.INTERNAL_ROOT + "/latest/TEST"))
			.andExpect(method(HttpMethod.GET))
			.andRespond(withSuccess(Files.readString(FIXTURE), MediaType.APPLICATION_JSON));
		assertThat(client.readLatest("TEST").identity().ticker()).isEqualTo("TEST");
		server.verify();
	}

	@Test
	void sanitizesNotFoundAndRejectsUnknownWireFields() throws Exception {
		RestClient.Builder missingBuilder = RestClient.builder().baseUrl("http://analytics.test");
		MockRestServiceServer missingServer = MockRestServiceServer.bindTo(missingBuilder).build();
		var missingClient = new CurrentFundamentalValueAnalyticsClient(missingBuilder.build());
		missingServer.expect(once(), requestTo("http://analytics.test"
				+ CurrentFundamentalValueAnalyticsClient.INTERNAL_ROOT + "/" + ID))
			.andRespond(withResourceNotFound().body("private database detail"));
		assertThatThrownBy(() -> missingClient.read(ID))
				.isInstanceOfSatisfying(FundamentalValueGatewayException.class,
						error -> assertThat(error.code()).isEqualTo(
								"CURRENT_FUNDAMENTAL_VALUE_ASSESSMENT_NOT_FOUND"));

		RestClient.Builder invalidBuilder = RestClient.builder().baseUrl("http://analytics.test");
		MockRestServiceServer invalidServer = MockRestServiceServer.bindTo(invalidBuilder).build();
		var invalidClient = new CurrentFundamentalValueAnalyticsClient(invalidBuilder.build());
		String changed = Files.readString(FIXTURE).replaceFirst("\\{", "{\"rawPayload\":{},");
		invalidServer.expect(once(), requestTo("http://analytics.test"
				+ CurrentFundamentalValueAnalyticsClient.INTERNAL_ROOT + "/" + ID))
			.andRespond(withSuccess(changed, MediaType.APPLICATION_JSON));
		assertThatThrownBy(() -> invalidClient.read(ID))
				.isInstanceOfSatisfying(FundamentalValueGatewayException.class,
						error -> assertThat(error.code()).isEqualTo(
								"CURRENT_FUNDAMENTAL_VALUE_UPSTREAM_CONTRACT_INVALID"));
	}
}
