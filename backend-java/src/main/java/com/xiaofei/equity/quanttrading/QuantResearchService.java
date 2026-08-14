package com.xiaofei.equity.quanttrading;

import java.math.BigDecimal;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.TreeMap;
import java.util.UUID;
import java.util.regex.Pattern;

import org.springframework.stereotype.Service;

import com.xiaofei.equity.quanttrading.QuantResearchContract.EntryPlan;
import com.xiaofei.equity.quanttrading.QuantResearchContract.Features;
import com.xiaofei.equity.quanttrading.QuantResearchContract.Ranking;
import com.xiaofei.equity.quanttrading.QuantResearchContract.RawSignal;
import com.xiaofei.equity.quanttrading.QuantResearchContract.ResearchDecisionResponse;
import com.xiaofei.equity.quanttrading.QuantResearchContract.ResearchSignal;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

@Service
public class QuantResearchService {

	private static final Pattern HASH = Pattern.compile("sha256:[0-9a-f]{64}");
	private static final Pattern DECIMAL = Pattern.compile("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?");
	private static final Set<String> ASSEMBLY_STATES = Set.of(
			"VALID", "MISSING", "STALE", "INVALID", "NOT_APPLICABLE", "EXCLUDED");
	private static final Set<String> RAW_STATES = Set.of(
			"ELIGIBLE", "INELIGIBLE", "MISSING", "INVALID");
	private static final Set<String> RANK_STATES = Set.of(
			"ENTRY_ELIGIBLE", "HOLD_ELIGIBLE", "EXIT_ELIGIBLE", "NOT_RANKED");
	private static final JsonMapper MAPPER = JsonMapper.builder().build();
	private static final UUID URL_NAMESPACE = UUID.fromString(
			"6ba7b811-9dad-11d1-80b4-00c04fd430c8");
	private static final String PERSISTENCE_VERSION =
			"quant-trading-research-persistence-v1.1.0";

	private final QuantResearchAnalyticsClient client;

	public QuantResearchService(QuantResearchAnalyticsClient client) {
		this.client = client;
	}

	public ResearchDecisionResponse read(UUID decisionId) {
		ResearchDecisionResponse response = validate(client.read(decisionId));
		if (!decisionId.equals(response.decisionId())) throw upstreamInvalid();
		return response;
	}

	private static ResearchDecisionResponse validate(ResearchDecisionResponse value) {
		try {
			if (value == null || value.decisionId() == null
					|| !QuantResearchContract.CONTRACT_VERSION.equals(value.contractVersion())
					|| !QuantResearchContract.PROJECTION_VERSION.equals(value.projectionVersion())
					|| !QuantResearchContract.ASSEMBLY_VERSION.equals(value.assemblyVersion())
					|| !QuantResearchContract.MODEL_VERSION.equals(value.modelVersion())
					|| !QuantResearchContract.STRATEGY_VERSION.equals(value.strategyVersion())
					|| !QuantResearchContract.FORMULA_VERSION.equals(value.formulaVersion())
					|| !QuantResearchContract.ENTRY_EXIT_POLICY_VERSION.equals(
							value.entryExitPolicyVersion())
					|| !"NOT_VALIDATED".equals(value.modelEvidenceLabel())
					|| value.decisionDate() == null || value.rebalanceOrdinal() < 0
					|| value.rebalanceOrdinal() % 5 != 0
					|| value.expectedSecurityCount() < 20
					|| !hash(value.assemblyManifestHash()) || !hash(value.contentHash())
					|| value.signals() == null
					|| value.signals().size() != value.expectedSecurityCount()
					|| value.authority() == null
					|| !value.authority().deterministicResearchSignal()
					|| value.authority().deterministicFinalPortfolioWeight()
					|| value.authority().automaticBrokerageExecution()
					|| value.authority().llmSignalOrWeightAuthority()
					|| value.authority().futureReturnGuaranteed()) {
				throw upstreamInvalid();
			}
			List<ResearchSignal> signals = new ArrayList<>();
			Set<UUID> ids = new HashSet<>();
			UUID previous = null;
			for (ResearchSignal signal : value.signals()) {
				validateSignal(signal);
				if (!ids.add(signal.securityId())
						|| previous != null && previous.toString().compareTo(
								signal.securityId().toString()) >= 0) throw upstreamInvalid();
				previous = signal.securityId();
				signals.add(copy(signal));
			}
			JsonNode root = MAPPER.valueToTree(value);
			if (containsForbiddenKey(root)) throw upstreamInvalid();
			ObjectNode body = (ObjectNode) root.deepCopy();
			body.remove("decisionId");
			body.remove("contentHash");
			if (!value.contentHash().equals("sha256:" + sha256(canonical(body)))) {
				throw upstreamInvalid();
			}
			if (!value.decisionId().equals(deterministicDecisionId(value.contentHash()))) {
				throw upstreamInvalid();
			}
			return new ResearchDecisionResponse(
					value.decisionId(), value.contractVersion(), value.projectionVersion(),
					value.assemblyVersion(), value.modelVersion(), value.strategyVersion(),
					value.formulaVersion(), value.entryExitPolicyVersion(),
					value.modelEvidenceLabel(), value.decisionDate(), value.rebalanceOrdinal(),
					value.expectedSecurityCount(), value.assemblyManifestHash(),
					List.copyOf(signals), value.authority(), value.contentHash());
		}
		catch (QuantResearchGatewayException exception) {
			throw exception;
		}
		catch (RuntimeException exception) {
			throw upstreamInvalid();
		}
	}

	private static void validateSignal(ResearchSignal value) {
		if (value == null || value.securityId() == null
				|| !ASSEMBLY_STATES.contains(value.assemblyState())
				|| !Set.of("APPLICABLE", "NOT_APPLICABLE", "INSUFFICIENT_EVIDENCE")
						.contains(value.applicability())
				|| !strings(value.assemblyReasonCodes()) || value.rawSignal() == null
				|| value.ranking() == null) throw upstreamInvalid();
		if (("VALID".equals(value.assemblyState())) != value.assemblyReasonCodes().isEmpty()) {
			throw upstreamInvalid();
		}
		RawSignal raw = value.rawSignal();
		Ranking ranking = value.ranking();
		if (!RAW_STATES.contains(raw.state()) || !strings(raw.reasonCodes())
				|| !hash(raw.inputHash()) || !hash(raw.contentHash())
				|| !RANK_STATES.contains(ranking.state())
				|| !hash(ranking.crossSectionHash()) || !hash(ranking.contentHash())
				|| ranking.crossSectionCount() < 0) throw upstreamInvalid();
		if ("ELIGIBLE".equals(raw.state())) {
			if (!decimal(raw.signalClose()) || raw.features() == null) throw upstreamInvalid();
			validateFeatures(raw.features());
		}
		else if (raw.signalClose() != null || raw.features() != null || raw.reasonCodes().isEmpty()) {
			throw upstreamInvalid();
		}
		if ("NOT_RANKED".equals(ranking.state())) {
			if (ranking.rank() != null || ranking.momentum252Percentile() != null
					|| ranking.momentum126Percentile() != null
					|| ranking.compositeScore() != null) throw upstreamInvalid();
		}
		else if (ranking.rank() == null || ranking.rank() < 1
				|| ranking.rank() > ranking.crossSectionCount()
				|| !percent(ranking.momentum252Percentile())
				|| !percent(ranking.momentum126Percentile())
				|| !percent(ranking.compositeScore())) throw upstreamInvalid();
		String expectedClassification = classification(
				value.assemblyState(), raw.state(), ranking.state());
		if (!expectedClassification.equals(value.researchClassification())) {
			throw upstreamInvalid();
		}
		if ("ENTRY_ELIGIBLE".equals(ranking.state())) validateEntry(value.entryPlan());
		else if (value.entryPlan() != null) throw upstreamInvalid();
	}

	private static void validateFeatures(Features value) {
		for (String item : List.of(value.atr14(), value.sma100(), value.sma200(),
				value.marketSma200(), value.momentum252Skip20(), value.momentum126Skip20(),
				value.marketMomentum252Skip20(), value.marketMomentum126Skip20(),
				value.relative252Skip20(), value.relative126Skip20(), value.medianAdtv20(),
				value.atrPercent())) if (!decimal(item)) throw upstreamInvalid();
	}

	private static void validateEntry(EntryPlan value) {
		if (value == null || !positive(value.signalClose()) || !positive(value.initialStop())
				|| !positive(value.maximumEntryPrice()) || !positive(value.atr14())
				|| value.maximumHoldingSessions() != 126
				|| new BigDecimal(value.initialStop()).compareTo(
						new BigDecimal(value.signalClose())) >= 0
				|| new BigDecimal(value.signalClose()).compareTo(
						new BigDecimal(value.maximumEntryPrice())) >= 0) throw upstreamInvalid();
	}

	private static ResearchSignal copy(ResearchSignal value) {
		return new ResearchSignal(value.securityId(), value.assemblyState(), value.applicability(),
				List.copyOf(value.assemblyReasonCodes()),
				new RawSignal(value.rawSignal().state(), List.copyOf(value.rawSignal().reasonCodes()),
						value.rawSignal().inputHash(), value.rawSignal().contentHash(),
						value.rawSignal().signalClose(), value.rawSignal().features()),
				value.ranking(), value.entryPlan(), value.researchClassification());
	}

	private static String classification(String assembly, String raw, String ranking) {
		if ("NOT_APPLICABLE".equals(assembly)) return "NOT_APPLICABLE";
		if (!"VALID".equals(assembly) || Set.of("MISSING", "INVALID").contains(raw)) {
			return "INSUFFICIENT_EVIDENCE";
		}
		if ("INELIGIBLE".equals(raw)) return "NO_SIGNAL";
		return switch (ranking) {
			case "ENTRY_ELIGIBLE" -> "ENTRY_CANDIDATE";
			case "HOLD_ELIGIBLE" -> "HOLD_REVIEW";
			case "EXIT_ELIGIBLE" -> "EXIT_REVIEW";
			default -> "NO_SIGNAL";
		};
	}

	private static boolean strings(List<String> values) {
		return values != null && values.stream().allMatch(
				item -> item != null && !item.isBlank());
	}

	private static boolean hash(String value) {
		return value != null && HASH.matcher(value).matches();
	}

	private static boolean decimal(String value) {
		if (value == null || !DECIMAL.matcher(value).matches()) return false;
		BigDecimal numeric = new BigDecimal(value);
		String canonical = numeric.signum() == 0 ? "0" : numeric.stripTrailingZeros().toPlainString();
		return value.equals(canonical);
	}

	private static boolean positive(String value) {
		return decimal(value) && new BigDecimal(value).signum() > 0;
	}

	private static boolean percent(String value) {
		return decimal(value) && new BigDecimal(value).compareTo(BigDecimal.ZERO) >= 0
				&& new BigDecimal(value).compareTo(new BigDecimal("100")) <= 0;
	}

	private static boolean containsForbiddenKey(JsonNode value) {
		if (value.isObject()) {
			for (String name : List.of("finalWeight", "orderQuantity", "brokerageInstruction")) {
				if (value.has(name)) return true;
			}
			for (JsonNode child : value) if (containsForbiddenKey(child)) return true;
		}
		else if (value.isArray()) for (JsonNode child : value) {
			if (containsForbiddenKey(child)) return true;
		}
		return false;
	}

	private static byte[] canonical(JsonNode value) {
		try {
			Object plain = toSortedValue(value);
			return MAPPER.writeValueAsString(plain).getBytes(StandardCharsets.UTF_8);
		}
		catch (RuntimeException exception) {
			throw upstreamInvalid();
		}
	}

	private static Object toSortedValue(JsonNode node) {
		if (node.isObject()) {
			var result = new TreeMap<String, Object>();
			node.properties().forEach(entry -> result.put(entry.getKey(), toSortedValue(entry.getValue())));
			return result;
		}
		if (node.isArray()) {
			var result = new ArrayList<>();
			for (JsonNode child : node) result.add(toSortedValue(child));
			return result;
		}
		if (node.isTextual()) return node.asText();
		if (node.isBoolean()) return node.booleanValue();
		if (node.isIntegralNumber()) return node.bigIntegerValue();
		if (node.isNull()) return null;
		throw upstreamInvalid();
	}

	private static String sha256(byte[] value) {
		try {
			return java.util.HexFormat.of().formatHex(
					MessageDigest.getInstance("SHA-256").digest(value));
		}
		catch (NoSuchAlgorithmException exception) {
			throw new IllegalStateException(exception);
		}
	}

	static UUID deterministicDecisionId(String contentHash) {
		try {
			MessageDigest digest = MessageDigest.getInstance("SHA-1");
			ByteBuffer namespace = ByteBuffer.allocate(16);
			namespace.putLong(URL_NAMESPACE.getMostSignificantBits());
			namespace.putLong(URL_NAMESPACE.getLeastSignificantBits());
			digest.update(namespace.array());
			digest.update((PERSISTENCE_VERSION + ":" + contentHash)
					.getBytes(StandardCharsets.UTF_8));
			byte[] bytes = digest.digest();
			bytes[6] = (byte) ((bytes[6] & 0x0f) | 0x50);
			bytes[8] = (byte) ((bytes[8] & 0x3f) | 0x80);
			ByteBuffer result = ByteBuffer.wrap(bytes);
			return new UUID(result.getLong(), result.getLong());
		}
		catch (NoSuchAlgorithmException exception) {
			throw new IllegalStateException(exception);
		}
	}

	private static QuantResearchGatewayException upstreamInvalid() {
		return new QuantResearchGatewayException("INVALID_QUANT_RESEARCH_UPSTREAM_RESPONSE",
				"The analytics service returned an invalid Quant research decision.", 502);
	}
}
