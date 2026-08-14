package com.xiaofei.equity.quanttrading;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.TreeMap;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import com.xiaofei.equity.quanttrading.QuantResearchContract.Authority;
import com.xiaofei.equity.quanttrading.QuantResearchContract.Ranking;
import com.xiaofei.equity.quanttrading.QuantResearchContract.RawSignal;
import com.xiaofei.equity.quanttrading.QuantResearchContract.ResearchDecisionResponse;
import com.xiaofei.equity.quanttrading.QuantResearchContract.ResearchSignal;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

class QuantResearchServiceTests {
	private static final JsonMapper MAPPER = JsonMapper.builder().build();

	@Test
	void acceptsAnImmutableMissingDecisionAndReturnsDefensiveSignals() throws Exception {
		ResearchDecisionResponse decision = decision(new Authority(true, false, false, false, false));
		QuantResearchAnalyticsClient client = Mockito.mock(QuantResearchAnalyticsClient.class);
		when(client.read(decision.decisionId())).thenReturn(decision);

		ResearchDecisionResponse loaded = new QuantResearchService(client).read(decision.decisionId());

		assertThat(loaded).isEqualTo(decision);
		assertThat(loaded.signals()).hasSize(20);
		assertThat(loaded.signals()).allMatch(
				signal -> "INSUFFICIENT_EVIDENCE".equals(signal.researchClassification()));
		assertThatThrownBy(() -> loaded.signals().add(loaded.signals().getFirst()))
				.isInstanceOf(UnsupportedOperationException.class);
		assertThat(loaded.authority().automaticBrokerageExecution()).isFalse();
	}

	@Test
	void rejectsAnyBrokerageOrFinalWeightAuthority() throws Exception {
		ResearchDecisionResponse decision = decision(new Authority(true, false, true, false, false));
		QuantResearchAnalyticsClient client = Mockito.mock(QuantResearchAnalyticsClient.class);
		when(client.read(decision.decisionId())).thenReturn(decision);

		assertThatThrownBy(() -> new QuantResearchService(client).read(decision.decisionId()))
				.isInstanceOf(QuantResearchGatewayException.class)
				.extracting("code").isEqualTo("INVALID_QUANT_RESEARCH_UPSTREAM_RESPONSE");
	}

	private static ResearchDecisionResponse decision(Authority authority) throws Exception {
		List<ResearchSignal> signals = new ArrayList<>();
		for (int ordinal = 1; ordinal <= 20; ordinal++) {
			UUID securityId = UUID.fromString(String.format(
					"27000000-0000-4000-8000-%012d", ordinal));
			signals.add(new ResearchSignal(
					securityId, "MISSING", "INSUFFICIENT_EVIDENCE",
					List.of("TEST_EVIDENCE_MISSING"),
					new RawSignal("MISSING", List.of("TEST_EVIDENCE_MISSING"),
							"sha256:" + "b".repeat(64), "sha256:" + "c".repeat(64),
							null, null),
					new Ranking("NOT_RANKED", null, 0, null, null, null,
							"sha256:" + "d".repeat(64), "sha256:" + "e".repeat(64)),
					null, "INSUFFICIENT_EVIDENCE"));
		}
		ResearchDecisionResponse draft = new ResearchDecisionResponse(
				UUID.fromString("27000000-0000-4000-8000-999999999999"),
				QuantResearchContract.CONTRACT_VERSION,
				QuantResearchContract.PROJECTION_VERSION,
				QuantResearchContract.ASSEMBLY_VERSION,
				QuantResearchContract.MODEL_VERSION,
				QuantResearchContract.STRATEGY_VERSION,
				QuantResearchContract.FORMULA_VERSION,
				QuantResearchContract.ENTRY_EXIT_POLICY_VERSION,
				"NOT_VALIDATED", LocalDate.of(2026, 8, 13), 0, 20,
				"sha256:" + "a".repeat(64), List.copyOf(signals), authority,
				"sha256:" + "f".repeat(64));
		String contentHash = contentHash(draft);
		return new ResearchDecisionResponse(
				QuantResearchService.deterministicDecisionId(contentHash), draft.contractVersion(),
				draft.projectionVersion(), draft.assemblyVersion(), draft.modelVersion(),
				draft.strategyVersion(), draft.formulaVersion(), draft.entryExitPolicyVersion(),
				draft.modelEvidenceLabel(), draft.decisionDate(), draft.rebalanceOrdinal(),
				draft.expectedSecurityCount(), draft.assemblyManifestHash(), draft.signals(),
				draft.authority(), contentHash);
	}

	private static String contentHash(ResearchDecisionResponse value) throws Exception {
		ObjectNode body = (ObjectNode) MAPPER.valueToTree(value);
		body.remove("decisionId");
		body.remove("contentHash");
		byte[] canonical = MAPPER.writeValueAsString(sorted(body))
				.getBytes(StandardCharsets.UTF_8);
		return "sha256:" + HexFormat.of().formatHex(
				MessageDigest.getInstance("SHA-256").digest(canonical));
	}

	private static Object sorted(JsonNode node) {
		if (node.isObject()) {
			var result = new TreeMap<String, Object>();
			node.properties().forEach(entry -> result.put(entry.getKey(), sorted(entry.getValue())));
			return result;
		}
		if (node.isArray()) {
			var result = new ArrayList<>();
			for (JsonNode child : node) result.add(sorted(child));
			return result;
		}
		if (node.isTextual()) return node.asText();
		if (node.isBoolean()) return node.booleanValue();
		if (node.isIntegralNumber()) return node.bigIntegerValue();
		if (node.isNull()) return null;
		throw new IllegalArgumentException("Unsupported canonical scalar");
	}
}
