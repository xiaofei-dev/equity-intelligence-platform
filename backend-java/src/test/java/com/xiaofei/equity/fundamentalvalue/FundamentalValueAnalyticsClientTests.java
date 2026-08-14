package com.xiaofei.equity.fundamentalvalue;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withResourceNotFound;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;
import java.util.stream.Stream;

import com.xiaofei.equity.fundamentalvalue.FundamentalValueContract.DecisionRequest;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import tools.jackson.databind.json.JsonMapper;

class FundamentalValueAnalyticsClientTests {

	private static final UUID ASSEMBLY_ID = UUID.fromString(
			"10000000-0000-4000-8000-000000000001");
	private static final UUID VALID_ASSEMBLY_ID = UUID.fromString(
			"10000000-0000-4000-8000-000000000031");
	private static final JsonMapper MAPPER = JsonMapper.builder().build();

	@Test
	void createsByDurableIdsAndForwardsIdempotencyKey() throws Exception {
		RestClient.Builder builder = RestClient.builder().baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new FundamentalValueAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
				"http://analytics.test/internal/v1/fundamental-value/decisions"))
			.andExpect(method(HttpMethod.POST))
			.andExpect(header("Idempotency-Key", "stable-replay-key"))
			.andExpect(jsonPath("$.routingId").value("10000000-0000-4000-8000-000000000101"))
			.andRespond(withSuccess(Files.readString(Path.of("..", "contracts",
                    "fundamental-value-v1", "internal-missing-response-v1.1.example.json")),
					MediaType.APPLICATION_JSON));

		DecisionRequest request = new DecisionRequest(
				FundamentalValueContract.COMMAND_VERSION,
				UUID.fromString("10000000-0000-4000-8000-000000000101"),
				UUID.fromString("10000000-0000-4000-8000-000000000102"),
				java.util.List.of(), 5);
		assertThat(client.create(request, "stable-replay-key").state()).isEqualTo("MISSING");
		server.verify();
	}

	@Test
	void readsExactInternalDecisionPathAndFixture() throws Exception {
		RestClient.Builder builder = RestClient.builder().baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new FundamentalValueAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
				"http://analytics.test/internal/v1/fundamental-value/decisions/" + ASSEMBLY_ID))
			.andExpect(method(HttpMethod.GET))
			.andRespond(withSuccess(Files.readString(Path.of("..", "contracts",
					"fundamental-value-v1", "internal-missing-response-v1.1.example.json")),
					MediaType.APPLICATION_JSON));

		assertThat(client.read(ASSEMBLY_ID).state()).isEqualTo("MISSING");
		server.verify();
	}

	@Test
	void sanitizesNotFoundWithoutLeakingUpstreamBody() {
		RestClient.Builder builder = RestClient.builder().baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new FundamentalValueAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
				"http://analytics.test/internal/v1/fundamental-value/decisions/" + ASSEMBLY_ID))
			.andRespond(withResourceNotFound().body("secret database detail"));

		assertThatThrownBy(() -> client.read(ASSEMBLY_ID))
			.isInstanceOf(FundamentalValueGatewayException.class)
			.hasMessage("The Fundamental Value decision was not found.")
			.hasMessageNotContaining("secret");
	}

	@Test
	void omittedRequiredAuthorityBooleanFailsAsStableUpstreamContractError() throws Exception {
		RestClient.Builder builder = RestClient.builder().baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new FundamentalValueAnalyticsClient(builder.build());
		String invalid = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-missing-response-v1.1.example.json"))
				.replace("  \"finalPortfolioWeightAuthorized\": false,\n", "");
		server.expect(once(), requestTo(
				"http://analytics.test/internal/v1/fundamental-value/decisions/" + ASSEMBLY_ID))
			.andRespond(withSuccess(invalid, MediaType.APPLICATION_JSON));

		assertThatThrownBy(() -> client.read(ASSEMBLY_ID))
				.isInstanceOf(FundamentalValueGatewayException.class)
				.hasMessage("The analytics response violates the Fundamental Value contract.");
	}

	@ParameterizedTest(name = "frozen version nested={0} field={1} omitted={3}")
	@MethodSource("frozenVersionMutations")
	void everyFrozenVersionRejectsValueDriftAndOmission(boolean nested, String field,
			String replacement, boolean omit) throws Exception {
		var root = validFixture();
		var target = nested ? root.get("deterministicAssessment").asObject() : root;
		if (omit) {
			target.remove(field);
		}
		else {
			target.put(field, replacement);
		}
		if (nested) {
			reseal(root);
		}
		assertInvalidProjection(MAPPER.writeValueAsString(root));
	}

	private static Stream<Arguments> frozenVersionMutations() {
		return Stream.of(
				Arguments.of(false, "contractVersion",
						"internal-fundamental-value-result-v9.0.0", false),
				Arguments.of(false, "contractVersion", "", true),
				Arguments.of(true, "modelVersion", "model-v9", false),
				Arguments.of(true, "modelVersion", "", true),
				Arguments.of(true, "strategyVersion", "strategy-v9", false),
				Arguments.of(true, "strategyVersion", "", true),
				Arguments.of(true, "formulaVersion", "formula-v9", false),
				Arguments.of(true, "formulaVersion", "", true),
				Arguments.of(true, "aggregationVersion", "aggregation-v9", false),
				Arguments.of(true, "aggregationVersion", "", true),
				Arguments.of(true, "riskPolicyVersion", "risk-v9", false),
				Arguments.of(true, "riskPolicyVersion", "", true),
				Arguments.of(true, "assumptionPolicyVersion", "assumption-v9", false),
				Arguments.of(true, "assumptionPolicyVersion", "", true));
	}

	@ParameterizedTest(name = "authority nested={0} field={1} omitted={3}")
	@MethodSource("authorityMutations")
	void everyRootAndNestedAuthorityRejectsToggleAndOmission(boolean nested, String field,
			boolean toggledValue, boolean omit) throws Exception {
		var root = validFixture();
		var target = nested ? root.get("deterministicAssessment").asObject() : root;
		if (omit) {
			target.remove(field);
		}
		else {
			target.put(field, toggledValue);
		}
		if (nested) {
			reseal(root);
		}
		assertInvalidProjection(MAPPER.writeValueAsString(root));
	}

	private static Stream<Arguments> authorityMutations() {
		return Stream.of(
				Arguments.of(false, "coreInvocationAuthorized", false, false),
				Arguments.of(false, "coreInvocationAuthorized", false, true),
				Arguments.of(false, "finalPortfolioWeightAuthorized", true, false),
				Arguments.of(false, "finalPortfolioWeightAuthorized", true, true),
				Arguments.of(false, "automaticBrokerageExecutionAuthorized", true, false),
				Arguments.of(false, "automaticBrokerageExecutionAuthorized", true, true),
				Arguments.of(true, "deterministicRankingAuthorized", true, false),
				Arguments.of(true, "deterministicRankingAuthorized", true, true),
				Arguments.of(true, "finalPortfolioWeightAuthorized", true, false),
				Arguments.of(true, "finalPortfolioWeightAuthorized", true, true),
				Arguments.of(true, "automaticBrokerageExecutionAuthorized", true, false),
				Arguments.of(true, "automaticBrokerageExecutionAuthorized", true, true));
	}

	@Test
	void createMapsMissingReferenceInvalidContractAndConflictExactly() {
		for (var expected : java.util.List.of(
				new Object[] {HttpStatus.NOT_FOUND, 404, "FUNDAMENTAL_VALUE_REFERENCE_NOT_FOUND"},
				new Object[] {HttpStatus.UNPROCESSABLE_CONTENT, 400,
						"INVALID_FUNDAMENTAL_VALUE_REQUEST"},
				new Object[] {HttpStatus.CONFLICT, 409,
						"FUNDAMENTAL_VALUE_PERSISTENCE_CONFLICT"})) {
			RestClient.Builder builder = RestClient.builder().baseUrl("http://analytics.test");
			MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
			var client = new FundamentalValueAnalyticsClient(builder.build());
			server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/fundamental-value/decisions"))
				.andRespond(withStatus((HttpStatus) expected[0]));
			DecisionRequest request = new DecisionRequest(
					FundamentalValueContract.COMMAND_VERSION,
					UUID.fromString("10000000-0000-4000-8000-000000000101"),
					UUID.fromString("10000000-0000-4000-8000-000000000102"),
					java.util.List.of(), 5);
			assertThatThrownBy(() -> client.create(request, "stable-key"))
					.isInstanceOfSatisfying(FundamentalValueGatewayException.class, error -> {
						assertThat(error.status()).isEqualTo(expected[1]);
						assertThat(error.code()).isEqualTo(expected[2]);
					});
		}
	}

	@Test
	void upstreamResponseIdsMustRemainCanonicalWireText() throws Exception {
		String fixture = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-missing-response-v1.1.example.json"));
		for (String invalid : java.util.List.of(
				"10000000-0000-4000-8000-0000000000AA",
				"10000000000040008000000000000001", "1-1-1-1-1")) {
			RestClient.Builder builder = RestClient.builder().baseUrl("http://analytics.test");
			MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
			var client = new FundamentalValueAnalyticsClient(builder.build());
			String changed = fixture.replace(
					"10000000-0000-4000-8000-000000000001", invalid);
			server.expect(once(), requestTo(
					"http://analytics.test/internal/v1/fundamental-value/decisions/" + ASSEMBLY_ID))
				.andRespond(withSuccess(changed, MediaType.APPLICATION_JSON));
			assertThatThrownBy(() -> client.read(ASSEMBLY_ID))
					.isInstanceOfSatisfying(FundamentalValueGatewayException.class,
							error -> assertThat(error.status()).isEqualTo(502));
		}
	}

	private static tools.jackson.databind.node.ObjectNode validFixture() throws Exception {
		return MAPPER.readTree(Files.readString(Path.of("..", "contracts",
				"fundamental-value-v1", "internal-valid-response-v1.1.example.json"))).asObject();
	}

	private static void reseal(tools.jackson.databind.node.ObjectNode root) throws Exception {
		var assessment = root.get("deterministicAssessment").asObject();
		assessment.put("contentHash", FundamentalValueService.canonicalContentHash(assessment));
		UUID assemblyId = UUID.fromString(root.get("assemblyId").asText());
		root.put("assessmentId", FundamentalValueService.deterministicAssessmentId(
				assemblyId, assessment.get("contentHash").asText()).toString());
	}

	private static void assertInvalidProjection(String body) {
		RestClient.Builder builder = RestClient.builder().baseUrl("http://analytics.test");
		MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
		var client = new FundamentalValueAnalyticsClient(builder.build());
		server.expect(once(), requestTo(
				"http://analytics.test/internal/v1/fundamental-value/decisions/"
						+ VALID_ASSEMBLY_ID))
			.andRespond(withSuccess(body, MediaType.APPLICATION_JSON));

		assertThatThrownBy(() -> new FundamentalValueService(client).read(VALID_ASSEMBLY_ID))
				.isInstanceOfSatisfying(FundamentalValueGatewayException.class, error -> {
					assertThat(error.status()).isEqualTo(502);
					assertThat(error.code()).isEqualTo(
							"FUNDAMENTAL_VALUE_UPSTREAM_CONTRACT_INVALID");
				});
		server.verify();
	}
}
