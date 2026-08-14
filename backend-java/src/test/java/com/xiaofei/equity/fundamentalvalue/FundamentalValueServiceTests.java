package com.xiaofei.equity.fundamentalvalue;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;
import java.util.stream.Stream;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

import com.xiaofei.equity.fundamentalvalue.FundamentalValueContract.InternalDecision;

import tools.jackson.databind.json.JsonMapper;

class FundamentalValueServiceTests {

	@Test
	void missingProjectionCannotGainAssessmentOrPortfolioAuthority() {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		UUID id = UUID.fromString("10000000-0000-4000-8000-000000000001");
		when(client.read(id)).thenReturn(missing(id, false));
		var response = new FundamentalValueService(client).read(id);
		assertThat(response.state()).isEqualTo("MISSING");
		assertThat(response.assessmentId()).isNull();
		assertThat(response.finalPortfolioWeightAuthorized()).isFalse();
	}

	@Test
	void authorityOnMissingResponseFailsClosed() {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		UUID id = UUID.fromString("10000000-0000-4000-8000-000000000001");
		when(client.read(id)).thenReturn(missing(id, true));
		assertThatThrownBy(() -> new FundamentalValueService(client).read(id))
				.isInstanceOf(FundamentalValueGatewayException.class)
				.hasMessageContaining("violates");
	}

	@Test
	void readRejectsAResponseForAnotherAssembly() {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		UUID requested = UUID.fromString("10000000-0000-4000-8000-000000000001");
		UUID returned = UUID.fromString("10000000-0000-4000-8000-000000000099");
		when(client.read(requested)).thenReturn(missing(returned, false));
		assertThatThrownBy(() -> new FundamentalValueService(client).read(requested))
				.isInstanceOfSatisfying(FundamentalValueGatewayException.class, error -> {
					assertThat(error.status()).isEqualTo(502);
					assertThat(error.code()).isEqualTo(
							"FUNDAMENTAL_VALUE_UPSTREAM_CONTRACT_INVALID");
				});
	}

	@Test
	void assessmentIdentityMustMatchAssemblyAndImmutableAssessmentContent() throws Exception {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		JsonMapper mapper = JsonMapper.builder().build();
		String json = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-valid-response-v1.1.example.json"));
		var root = mapper.readTree(json).asObject();
		root.put("assessmentId", "10000000-0000-4000-8000-000000000032");
		assertUpstreamContractInvalid(client, mapper.treeToValue(root, InternalDecision.class));
	}

	@Test
	void completedSessionCannotBeLaterThanDecisionCutoff() throws Exception {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		JsonMapper mapper = JsonMapper.builder().build();
		String json = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-valid-response-v1.1.example.json"));
		var root = mapper.readTree(json).asObject();
		root.get("identity").asObject().put("completedSessionDate", "2099-01-01");
		assertUpstreamContractInvalid(client, mapper.treeToValue(root, InternalDecision.class));
	}

	@Test
	void serviceProjectionPreservesTheCompleteDurableIdentityEnvelope() throws Exception {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		JsonMapper mapper = JsonMapper.builder().build();
		String json = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-valid-response-v1.1.example.json"));
		InternalDecision decision = mapper.readValue(json, InternalDecision.class);
		when(client.read(decision.assemblyId())).thenReturn(decision);

		var identity = new FundamentalValueService(client).read(decision.assemblyId()).identity();
		assertThat(identity.securityId()).hasToString(
				"10000000-0000-4000-8000-000000000010");
		assertThat(identity.companyId()).hasToString(
				"10000000-0000-4000-8000-000000000011");
		assertThat(identity.instrumentId()).hasToString(
				"10000000-0000-4000-8000-000000000012");
		assertThat(identity.shareClassId()).hasToString(
				"10000000-0000-4000-8000-000000000013");
		assertThat(identity.listingId()).hasToString(
				"10000000-0000-4000-8000-000000000014");
		assertThat(identity.tickerAssignmentId()).hasToString(
				"10000000-0000-4000-8000-000000000015");
		assertThat(identity.ticker()).isEqualTo("TEST");
		assertThat(identity.mic()).isEqualTo("XNYS");
		assertThat(identity.currency()).isEqualTo("USD");
		assertThat(identity.completedSessionDate()).isEqualTo(LocalDate.parse("2026-07-29"));
	}

	@ParameterizedTest(name = "malformed identity field {0} fails closed")
	@MethodSource("malformedIdentityMutations")
	void malformedIdentityFieldsFailClosed(String field, String invalidValue,
			boolean useNull) throws Exception {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		JsonMapper mapper = JsonMapper.builder().build();
		String json = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-valid-response-v1.1.example.json"));
		var root = mapper.readTree(json).asObject();
		var identity = root.get("identity").asObject();
		if (useNull) {
			identity.putNull(field);
		}
		else {
			identity.put(field, invalidValue);
		}
		assertUpstreamContractInvalid(client, mapper.treeToValue(root, InternalDecision.class));
	}

	private static Stream<Arguments> malformedIdentityMutations() {
		return Stream.of(
				Arguments.of("securityId", "", true),
				Arguments.of("companyId", "", true),
				Arguments.of("instrumentId", "", true),
				Arguments.of("shareClassId", "", true),
				Arguments.of("listingId", "", true),
				Arguments.of("tickerAssignmentId", "", true),
				Arguments.of("ticker", "test", false),
				Arguments.of("mic", "XNY", false),
				Arguments.of("currency", "US", false),
				Arguments.of("completedSessionDate", "", true));
	}

	@Test
	void specializedBankCannotMasqueradeAsUsableGenericAssessment() {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		UUID id = UUID.fromString("10000000-0000-4000-8000-000000000001");
		InternalDecision invalid = new InternalDecision(FundamentalValueContract.RESULT_VERSION,
				id, UUID.randomUUID(), identity(), "VALID", "SPECIALIZED_MODEL_REQUIRED", "BANK",
				List.of(), true, "sha256:" + "a".repeat(64), "sha256:" + "b".repeat(64),
				Instant.parse("2026-07-29T20:05:00Z"),
				Instant.parse("2026-07-29T20:07:00Z"), "NOT_VALIDATED",
				"FULL_CURRENT_DECISION", "0.02",
				JsonMapper.builder().build().createObjectNode(), false, false);
		when(client.read(id)).thenReturn(invalid);
		assertThatThrownBy(() -> new FundamentalValueService(client).read(id))
				.isInstanceOf(FundamentalValueGatewayException.class);
	}

	@Test
	void missingResponseCannotCarryNestedProviderOrAiPayload() {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		UUID id = UUID.fromString("10000000-0000-4000-8000-000000000001");
		InternalDecision base = missing(id, false);
		InternalDecision invalid = new InternalDecision(base.contractVersion(), base.assemblyId(),
				base.assessmentId(), base.identity(), base.state(), base.applicability(), base.companyType(),
				base.reasonCodes(), base.coreInvocationAuthorized(), base.manifestContentHash(),
				base.inputSealContentHash(), base.decisionCutoff(), base.sealedIngestionCutoff(),
				base.modelEvidenceLabel(), base.claimCeiling(), base.riskCapCeiling(),
				JsonMapper.builder().build().createObjectNode().put("providerPayload", "secret"),
				false, false);
		when(client.read(id)).thenReturn(invalid);
		assertThatThrownBy(() -> new FundamentalValueService(client).read(id))
				.isInstanceOf(FundamentalValueGatewayException.class);
	}

	@Test
	void canonicalPythonValidAssessmentPassesAndOneFieldTamperFails() throws Exception {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		String json = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-valid-response-v1.1.example.json"));
		JsonMapper mapper = JsonMapper.builder().build();
		InternalDecision valid = mapper.readValue(json, InternalDecision.class);
		assertThat(FundamentalValueService.deterministicAssessmentId(
				valid.assemblyId(), valid.deterministicAssessment().get("contentHash").asText()))
				.isEqualTo(valid.assessmentId());
		when(client.read(valid.assemblyId())).thenReturn(valid);
		var response = new FundamentalValueService(client).read(valid.assemblyId());
		assertThat(response.deterministicAssessment().get("fairValue").get("central").asText())
				.isEqualTo("160.50");

		var tamperedNode = mapper.readTree(json);
		tamperedNode.get("deterministicAssessment").get("fairValue")
				.asObject().put("central", "160.51");
		InternalDecision tampered = mapper.treeToValue(tamperedNode, InternalDecision.class);
		when(client.read(valid.assemblyId())).thenReturn(tampered);
		assertThatThrownBy(() -> new FundamentalValueService(client).read(valid.assemblyId()))
				.isInstanceOf(FundamentalValueGatewayException.class);
	}

	@Test
	void exactNonGenericRoutingStateAndReasonMatrixIsEnforced() {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		UUID id = UUID.fromString("10000000-0000-4000-8000-000000000001");
		for (String[] row : new String[][] {
				{"BANK", "SPECIALIZED_MODEL_REQUIRED", "NOT_APPLICABLE",
						"APPLICABILITY_SPECIALIZED_MODEL_REQUIRED"},
				{"INSURER", "SPECIALIZED_MODEL_REQUIRED", "NOT_APPLICABLE",
						"APPLICABILITY_SPECIALIZED_MODEL_REQUIRED"},
				{"REIT", "SPECIALIZED_MODEL_REQUIRED", "NOT_APPLICABLE",
						"APPLICABILITY_SPECIALIZED_MODEL_REQUIRED"},
				{"RESOURCE", "SPECIALIZED_MODEL_REQUIRED", "NOT_APPLICABLE",
						"APPLICABILITY_SPECIALIZED_MODEL_REQUIRED"},
				{"BIOTECHNOLOGY", "SPECIALIZED_MODEL_REQUIRED", "NOT_APPLICABLE",
						"APPLICABILITY_SPECIALIZED_MODEL_REQUIRED"},
				{"FINANCIAL", "SPECIALIZED_MODEL_REQUIRED", "NOT_APPLICABLE",
						"APPLICABILITY_SPECIALIZED_MODEL_REQUIRED"},
				{"INCOMPATIBLE_CONGLOMERATE", "SPECIALIZED_MODEL_REQUIRED", "NOT_APPLICABLE",
						"APPLICABILITY_SPECIALIZED_MODEL_REQUIRED"},
				{"BENCHMARK", "NOT_APPLICABLE", "NOT_APPLICABLE",
						"APPLICABILITY_NOT_APPLICABLE"},
				{"INSUFFICIENT_PUBLIC_HISTORY", "INSUFFICIENT_EVIDENCE", "MISSING",
						"APPLICABILITY_INSUFFICIENT_EVIDENCE"}
		}) {
			InternalDecision valid = routed(id, row[0], row[1], row[2], row[3]);
			when(client.read(id)).thenReturn(valid);
			assertThat(new FundamentalValueService(client).read(id).companyType()).isEqualTo(row[0]);
			when(client.read(id)).thenReturn(routed(id, row[0], row[1], "STALE", "WRONG"));
			assertThatThrownBy(() -> new FundamentalValueService(client).read(id))
					.isInstanceOf(FundamentalValueGatewayException.class);
		}
	}

	@Test
	void malformedNestedSuccessBodiesAlwaysBecomeSanitizedUpstream502() throws Exception {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		JsonMapper mapper = JsonMapper.builder().build();
		String json = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-valid-response-v1.1.example.json"));
		for (java.util.function.Consumer<tools.jackson.databind.node.ObjectNode> mutation
				: List.<java.util.function.Consumer<tools.jackson.databind.node.ObjectNode>>of(
					root -> root.get("deterministicAssessment").asObject()
							.get("companyQuality").asObject().putNull("state"),
					root -> root.get("deterministicAssessment").asObject()
							.put("projectionYears", new java.math.BigInteger("999999999999999999999")),
					root -> root.get("deterministicAssessment").asObject()
							.get("fairValue").asObject().putObject("low")
				)) {
			var root = mapper.readTree(json).asObject();
			mutation.accept(root);
			InternalDecision invalid = mapper.treeToValue(root, InternalDecision.class);
			when(client.read(invalid.assemblyId())).thenReturn(invalid);
			assertThatThrownBy(() -> new FundamentalValueService(client).read(invalid.assemblyId()))
					.isInstanceOfSatisfying(FundamentalValueGatewayException.class, error -> {
						assertThat(error.status()).isEqualTo(502);
						assertThat(error.code()).isEqualTo(
								"FUNDAMENTAL_VALUE_UPSTREAM_CONTRACT_INVALID");
						assertThat(error.getMessage()).doesNotContain("companyQuality", "provider");
					});
		}
	}

	@Test
	void validRootRejectsReasonsAndExponentFormAssessmentDecimal() throws Exception {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		JsonMapper mapper = JsonMapper.builder().build();
		String json = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-valid-response-v1.1.example.json"));
		for (java.util.function.Consumer<tools.jackson.databind.node.ObjectNode> mutation
				: List.<java.util.function.Consumer<tools.jackson.databind.node.ObjectNode>>of(
					root -> root.withArrayProperty("reasonCodes").add("ASSEMBLY_COMPLETE"),
					root -> root.get("deterministicAssessment").asObject()
							.get("referencePrice").asObject().put("value", "1E+2")
			)) {
			var root = mapper.readTree(json).asObject();
			mutation.accept(root);
			InternalDecision invalid = mapper.treeToValue(root, InternalDecision.class);
			when(client.read(invalid.assemblyId())).thenReturn(invalid);
			assertThatThrownBy(() -> new FundamentalValueService(client).read(invalid.assemblyId()))
					.isInstanceOf(FundamentalValueGatewayException.class);
		}
	}

	@Test
	void noncanonicalZeroWireDecimalsFailClosedAfterCanonicalReseal() throws Exception {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		JsonMapper mapper = JsonMapper.builder().build();
		String json = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-valid-response-v1.1.example.json"));
		for (String spelling : List.of("-0", "-0.0", "-0.00", "-0.000000", "0.0", "0.00")) {
			var root = mapper.readTree(json).asObject();
			var assessment = root.get("deterministicAssessment").asObject();
			assessment.get("marginOfSafety").asObject().put("low", spelling);
			reseal(root);
			assertUpstreamContractInvalid(client, mapper.treeToValue(root, InternalDecision.class));
		}

		for (java.util.function.Consumer<tools.jackson.databind.node.ObjectNode> mutation
				: List.<java.util.function.Consumer<tools.jackson.databind.node.ObjectNode>>of(
						assessment -> assessment.get("companyQuality").asObject()
								.put("score", "0.00"),
						assessment -> assessment.withArrayProperty("thesisEvidence").get(0)
								.asObject().put("observedValue", "0.00"),
						assessment -> assessment.withArrayProperty("valuations").get(0)
								.asObject().put("terminalValueShare", "0.00")
				)) {
			var root = mapper.readTree(json).asObject();
			var assessment = root.get("deterministicAssessment").asObject();
			mutation.accept(assessment);
			reseal(root);
			assertUpstreamContractInvalid(client, mapper.treeToValue(root, InternalDecision.class));
		}
	}

	@Test
	void fcffTerminalValueShareHonorsFrozenCoreCeilingBeforeHashAcceptance() throws Exception {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		JsonMapper mapper = JsonMapper.builder().build();
		String json = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-valid-response-v1.1.example.json"));
		for (String accepted : List.of("0", "0.80")) {
			var root = mapper.readTree(json).asObject();
			var assessment = root.get("deterministicAssessment").asObject();
			assessment.withArrayProperty("valuations").get(0).asObject()
					.put("terminalValueShare", accepted);
			reseal(root);
			InternalDecision decision = mapper.treeToValue(root, InternalDecision.class);
			when(client.read(decision.assemblyId())).thenReturn(decision);
			assertThat(new FundamentalValueService(client).read(decision.assemblyId())
					.deterministicAssessment().get("valuations").get(0)
					.get("terminalValueShare").asText()).isEqualTo(accepted);
		}

		for (String rejected : List.of("0.81", "1.00", "-0.01", "8E-1")) {
			var root = mapper.readTree(json).asObject();
			var assessment = root.get("deterministicAssessment").asObject();
			assessment.withArrayProperty("valuations").get(0).asObject()
					.put("terminalValueShare", rejected);
			reseal(root);
			InternalDecision decision = mapper.treeToValue(root, InternalDecision.class);
			when(client.read(decision.assemblyId())).thenReturn(decision);
			assertThatThrownBy(() -> new FundamentalValueService(client).read(decision.assemblyId()))
					.isInstanceOfSatisfying(FundamentalValueGatewayException.class, error -> {
						assertThat(error.status()).isEqualTo(502);
						assertThat(error.code()).isEqualTo(
								"FUNDAMENTAL_VALUE_UPSTREAM_CONTRACT_INVALID");
					});
		}
	}

	@Test
	void frozenConditionThresholdsAndSatisfiedComparisonsCannotDrift() throws Exception {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		JsonMapper mapper = JsonMapper.builder().build();
		String json = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-valid-response-v1.1.example.json"));

		for (String group : List.of("thesisEvidence", "counterThesisEvidence",
				"invalidationConditions")) {
			var baseline = mapper.readTree(json).asObject();
			int size = baseline.get("deterministicAssessment").get(group).size();
			for (int index = 0; index < size; index++) {
				var thresholdRoot = mapper.readTree(json).asObject();
				var thresholdAssessment = thresholdRoot.get("deterministicAssessment").asObject();
				thresholdAssessment.withArrayProperty(group).get(index).asObject()
						.put("threshold", "999");
				reseal(thresholdRoot);
				assertUpstreamContractInvalid(client,
						mapper.treeToValue(thresholdRoot, InternalDecision.class));

				var root = mapper.readTree(json).asObject();
				var assessment = root.get("deterministicAssessment").asObject();
				var condition = assessment.withArrayProperty(group).get(index).asObject();
				condition.put("satisfied", !condition.get("satisfied").asBoolean());
				reseal(root);
				assertUpstreamContractInvalid(client,
						mapper.treeToValue(root, InternalDecision.class));
			}
		}
	}

	@Test
	void frozenConditionObservationsRemainBoundToExposedSourceValues() throws Exception {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		JsonMapper mapper = JsonMapper.builder().build();
		String json = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-valid-response-v1.1.example.json"));
		for (java.util.function.Consumer<tools.jackson.databind.node.ObjectNode> mutation
				: List.<java.util.function.Consumer<tools.jackson.databind.node.ObjectNode>>of(
						assessment -> assessment.withArrayProperty("thesisEvidence").get(0)
								.asObject().put("observedValue", "70").put("satisfied", true),
						assessment -> assessment.withArrayProperty("thesisEvidence").get(1)
								.asObject().put("observedValue", "70").put("satisfied", true),
						assessment -> assessment.withArrayProperty("thesisEvidence").get(2)
								.asObject().put("observedValue", "0.20").put("satisfied", true),
						assessment -> assessment.withArrayProperty("counterThesisEvidence").get(0)
								.asObject().put("observedValue", "70").put("satisfied", true),
						assessment -> assessment.withArrayProperty("invalidationConditions").get(2)
								.asObject().put("observedValue", "-0.1").put("satisfied", true)
				)) {
			var root = mapper.readTree(json).asObject();
			mutation.accept(root.get("deterministicAssessment").asObject());
			reseal(root);
			assertUpstreamContractInvalid(client, mapper.treeToValue(root, InternalDecision.class));
		}
	}

	@Test
	void publicProjectionDefensivelyCopiesAssessmentAndReasons() throws Exception {
		FundamentalValueAnalyticsClient client = mock(FundamentalValueAnalyticsClient.class);
		JsonMapper mapper = JsonMapper.builder().build();
		String json = Files.readString(Path.of("..", "contracts", "fundamental-value-v1",
				"internal-valid-response-v1.1.example.json"));
		InternalDecision source = mapper.readValue(json, InternalDecision.class);
		when(client.read(source.assemblyId())).thenReturn(source);
		var first = new FundamentalValueService(client).read(source.assemblyId());

		source.deterministicAssessment().get("fairValue").asObject().put("central", "999");
		assertThat(first.deterministicAssessment().get("fairValue").get("central").asText())
				.isEqualTo("160.50");
		assertThatThrownBy(() -> first.reasonCodes().add("MUTATION"))
				.isInstanceOf(UnsupportedOperationException.class);

		first.deterministicAssessment().get("fairValue").asObject().put("central", "777");
		InternalDecision fresh = mapper.readValue(json, InternalDecision.class);
		when(client.read(source.assemblyId())).thenReturn(fresh);
		var second = new FundamentalValueService(client).read(source.assemblyId());
		assertThat(second.deterministicAssessment().get("fairValue").get("central").asText())
				.isEqualTo("160.50");
		assertThat(fresh.deterministicAssessment().get("fairValue").get("central").asText())
				.isEqualTo("160.50");
	}

	private static InternalDecision missing(UUID id, boolean finalWeight) {
		return new InternalDecision(FundamentalValueContract.RESULT_VERSION, id, null,
				identity(), "MISSING", "APPLICABLE", "MATURE_OPERATING_COMPANY",
				List.of("REQUIRED_OPERAND_MISSING"), false,
				"sha256:" + "a".repeat(64), "sha256:" + "b".repeat(64),
				Instant.parse("2026-07-29T20:05:00Z"),
				Instant.parse("2026-07-29T20:07:00Z"), null, null, null, null,
				finalWeight, false);
	}

	private static void assertUpstreamContractInvalid(FundamentalValueAnalyticsClient client,
			InternalDecision decision) {
		when(client.read(decision.assemblyId())).thenReturn(decision);
		assertThatThrownBy(() -> new FundamentalValueService(client).read(decision.assemblyId()))
				.isInstanceOfSatisfying(FundamentalValueGatewayException.class, error -> {
					assertThat(error.status()).isEqualTo(502);
					assertThat(error.code()).isEqualTo(
							"FUNDAMENTAL_VALUE_UPSTREAM_CONTRACT_INVALID");
				});
	}

	private static void reseal(tools.jackson.databind.node.ObjectNode root) throws Exception {
		var assessment = root.get("deterministicAssessment").asObject();
		assessment.put("contentHash", FundamentalValueService.canonicalContentHash(assessment));
		UUID assemblyId = UUID.fromString(root.get("assemblyId").asText());
		root.put("assessmentId", FundamentalValueService.deterministicAssessmentId(
				assemblyId, assessment.get("contentHash").asText()).toString());
	}

	private static InternalDecision routed(UUID id, String companyType, String applicability,
			String state, String reason) {
		return new InternalDecision(FundamentalValueContract.RESULT_VERSION, id, null,
				identity(), state, applicability, companyType, List.of(reason), false,
				"sha256:" + "a".repeat(64), "sha256:" + "b".repeat(64),
				Instant.parse("2026-07-29T20:05:00Z"),
				Instant.parse("2026-07-29T20:07:00Z"), null, null, null, null, false, false);
	}

	private static FundamentalValueContract.DecisionIdentity identity() {
		return new FundamentalValueContract.DecisionIdentity(
				UUID.fromString("10000000-0000-4000-8000-000000000010"),
				UUID.fromString("10000000-0000-4000-8000-000000000011"),
				UUID.fromString("10000000-0000-4000-8000-000000000012"),
				UUID.fromString("10000000-0000-4000-8000-000000000013"),
				UUID.fromString("10000000-0000-4000-8000-000000000014"),
				UUID.fromString("10000000-0000-4000-8000-000000000015"),
				"TEST", "XNYS", "USD", LocalDate.parse("2026-07-29"));
	}
}
