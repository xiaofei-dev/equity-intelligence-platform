package com.xiaofei.equity.architecture;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;

import tools.jackson.databind.node.ObjectNode;
import tools.jackson.databind.json.JsonMapper;

class DualSystemArchitectureContractTests {

	private final JsonMapper mapper = JsonMapper.builder().findAndAddModules().build();

	@Test
	void canonicalFixturePreservesEngineSleeveAndHumanControlBoundaries()
			throws Exception {
		var context = DualSystemArchitectureContract.decode(
				mapper, Files.readString(fixture()));

		assertThat(context.fundamentalValueOutput().sleeve())
			.isEqualTo(DualSystemArchitectureContract.Sleeve.LONG_TERM_CORE);
		assertThat(context.quantTradePlanOutput().sleeve())
			.isEqualTo(DualSystemArchitectureContract.Sleeve.QUANT_TRADING);
		assertThat(context.portfolioRiskView().sameSecurityAcrossSleevesAllowed())
			.isTrue();
		assertThat(context.humanControl().automaticBrokerageExecutionAllowed())
			.isFalse();
		assertThat(context.compatibility().successorMetric())
			.isEqualTo("VALUATION_OPPORTUNITY");
	}

	@Test
	void unknownStateAndVersionFailClosed() throws Exception {
		ObjectNode invalidVersion = (ObjectNode) mapper.readTree(
				Files.readString(fixture()));
		invalidVersion.put("contractVersion", "dual-system-architecture-v2");
		assertThatThrownBy(() -> DualSystemArchitectureContract.decode(
				mapper, invalidVersion.toString()))
			.hasRootCauseMessage("Unsupported dual-system contract version");

		ObjectNode invalidState = (ObjectNode) mapper.readTree(
				Files.readString(fixture()));
		((ObjectNode) invalidState.get("evidence")).put("state", "UNKNOWN");
		assertThatThrownBy(() -> DualSystemArchitectureContract.decode(
				mapper, invalidState.toString()))
			.hasMessageContaining("UNKNOWN");
	}

	@Test
	void scoreAveragingAiInfluenceAndBrokerageExecutionFailClosed()
			throws Exception {
		assertRejected("portfolioRiskView", "scoreAggregationPolicy", "AVERAGE");
		assertRejected("aiNarrative", "mayAffectDeterministicFields", true);
		assertRejected("humanControl", "automaticBrokerageExecutionAllowed", true);
		assertRejected("quantTradePlanOutput", "brokerageExecutionAllowed", true);
	}

	@Test
	void requiredEnumsSessionQuantAndHumanFieldsFailClosed() throws Exception {
		assertRejected("fundamentalValueOutput", "state", null);
		assertRejected("quantTradePlanOutput", "state", null);
		assertRejected("fundamentalValueOutput", "applicability", null);
		assertRejected("completedSession", "status", "SCHEDULED");
		assertRejected("completedSession", "calendarVersion", null);
		assertRejected("quantTradePlanOutput", "market", null);
		assertRejected("quantTradePlanOutput", "cadence", "INTRADAY");
		assertRejected("quantTradePlanOutput", "direction", "SHORT");
		assertRejected("quantTradePlanOutput", "leverageAllowed", null);
		assertRejected("humanControl", "decisionRequiredForCashTransfer", null);
		assertRejected("humanControl", "decisionRecordsAreImmutable", false);
		assertRejected("humanControl", "correctionsUseSupersession", false);
	}

	@Test
	void outputPortfolioVersionCutoffAndGovernanceStructuresFailClosed()
			throws Exception {
		assertRejected("fundamentalValueOutput", "marginOfSafety", null);
		assertRejected("quantTradePlanOutput", "stop", null);
		assertRejected("portfolioRiskView", "sameSecurityAcrossSleevesAllowed", null);
		assertRejected("portfolioRiskView", "cashTransferAuthority", null);
		assertRejected("validationGovernance", "mayUpgradeModelEvidenceLabel", true);
		assertRejected("versionSet", "costPolicyVersion", null);
		assertNestedRejected("decisionTiming", "decisionCutoff", "2026-07-29T20:04:59Z",
				"evidence", "availableAt", "2026-07-29T20:05:00Z");
		assertNestedRejected("evidence", "fieldTolerancePolicy", "policyVersion", "");
		assertNestedRejected("quantTradePlanOutput", "costAssumptions", "version", "");
	}

	@Test
	void benchmarkRangeTargetSleeveAndNonvalidScoreRulesFailClosed()
			throws Exception {
		ObjectNode root = fixtureTree();
		((ObjectNode) root.get("fundamentalValueOutput").get("fairValue"))
			.putNull("rangeHigh");
		assertTreeRejected(root);

		root = fixtureTree();
		((ObjectNode) root.get("quantTradePlanOutput")).putArray("targets");
		assertTreeRejected(root);

		root = fixtureTree();
		((ObjectNode) root.get("fundamentalValueOutput"))
			.putArray("benchmarkCodes").add("DATED_SECTOR_BENCHMARK").add("SPY");
		assertTreeRejected(root);

		root = fixtureTree();
		var sleeves = root.get("portfolioRiskView").get("sleeves");
		((ObjectNode) sleeves.get(1)).put("sleeve", "LONG_TERM_CORE");
		assertTreeRejected(root);

		root = fixtureTree();
		((ObjectNode) root.get("quantTradePlanOutput"))
			.put("state", "MISSING")
			.put("reasonCode", "REQUIRED_INPUT_MISSING");
		assertTreeRejected(root);
	}

	@Test
	void missingAndNullSafetyBooleanDeclarationsFailClosed() throws Exception {
		for (String field : new String[] {
				"sameSecurityAcrossSleevesAllowed",
				"automaticCashTransfersAllowed"
		}) {
			assertMissingAndNullRejected("portfolioRiskView", field);
		}
		for (String field : new String[] {
				"mayAffectDeterministicFields",
				"maySetWeightsOrTrades"
		}) {
			assertMissingAndNullRejected("aiNarrative", field);
		}
		for (String field : new String[] {
				"decisionRequiredForFinalAllocation",
				"decisionRequiredForCashTransfer",
				"automaticBrokerageExecutionAllowed",
				"decisionRecordsAreImmutable",
				"correctionsUseSupersession"
		}) {
			assertMissingAndNullRejected("humanControl", field);
		}
		assertMissingAndNullRejected(
				"validationGovernance", "mayUpgradeModelEvidenceLabel");
	}

	@Test
	void evidenceEnumsReasonsAndProviderLineageFailClosed() throws Exception {
		assertMissingAndNullRejected("evidence", "strictnessClass");
		assertMissingAndNullRejected("evidence", "claimClass");
		for (String field : new String[] {
				"providerCode", "providerSchemaVersion", "adapterVersion",
				"normalizationVersion", "sourceRecordId", "sourceContentHash",
				"normalizedRecordHash", "effectiveAt", "availableAt",
				"ingestedAt", "freshnessPolicyVersion", "sourceRevision",
				"conflict"
		}) {
			assertMissingAndNullRejected("evidence", field);
		}
		ObjectNode root = fixtureTree();
		((ObjectNode) root.get("evidence")).put("state", "MISSING").putNull("reasonCode");
		assertTreeRejected(root);
		for (String field : new String[] {"status", "criticality"}) {
			root = fixtureTree();
			((ObjectNode) root.get("evidence").get("conflict")).putNull(field);
			assertTreeRejected(root);
		}
	}

	@Test
	void tolerancePolicyIsConditionalAndOptionalTimestampsAreValidated()
			throws Exception {
		ObjectNode root = fixtureTree();
		((ObjectNode) root.get("evidence")).remove("fieldTolerancePolicy");
		assertTreeRejected(root);

		for (String[] pair : new String[][] {
				{"STRICT_IDENTITY_AND_CHRONOLOGY", "CURRENT_ONLY"},
				{"APPROXIMATE_HISTORICAL_RESEARCH", "APPROXIMATE_HISTORICAL"}
		}) {
			root = fixtureTree();
			ObjectNode evidence = (ObjectNode) root.get("evidence");
			evidence.put("strictnessClass", pair[0]);
			evidence.put("claimClass", pair[1]);
			evidence.remove("fieldTolerancePolicy");
			DualSystemArchitectureContract.decode(mapper, root.toString());
		}
		for (String field : new String[] {"retrievedAt", "staleAfter"}) {
			root = fixtureTree();
			((ObjectNode) root.get("evidence")).putNull(field);
			DualSystemArchitectureContract.decode(mapper, root.toString());
			root = fixtureTree();
			((ObjectNode) root.get("evidence")).put(field, "not-a-timestamp");
			assertTreeRejected(root);
		}
	}

	@Test
	void durableIdentityAndOutputReferencesRejectMissingAndNull() throws Exception {
		for (String field : new String[] {
				"securityId", "companyId", "instrumentId", "shareClassId",
				"listingId", "tickerAssignmentId", "ticker", "mic", "currency"
		}) {
			assertMissingAndNullRejected("security", field);
		}
		for (String output : new String[] {
				"fundamentalValueOutput", "quantTradePlanOutput"
		}) {
			for (String field : new String[] {
					"outputId", "decisionContractVersion", "modelId",
					"modelVersion", "strategyVersion", "evidenceHash"
			}) {
				assertMissingAndNullRejected(output, field);
			}
		}
		assertMissingAndNullRejected("fundamentalValueOutput", "referencePrice");
		assertMissingAndNullRejected("quantTradePlanOutput", "setup");
		assertMissingAndNullRejected("portfolioRiskView", "contractVersion");
	}

	@Test
	void bindingsCompatibilityGovernanceAndChronologyFailClosed()
			throws Exception {
		for (int index : new int[] {0, 1}) {
			ObjectNode root = fixtureTree();
			((ObjectNode) root.get("portfolioRiskView").get("sleeves").get(index))
				.put("engineOutputId", "00000000-0000-4000-8000-000000000000");
			assertTreeRejected(root);
		}
		for (String field : new String[] {
				"legacyBuyingOpportunityMeaning", "successorMetric",
				"legacyPublicMarketDataApiStatus"
		}) {
			assertRejected("compatibility", field, "UNKNOWN");
		}
		assertRejected("validationGovernance", "modelEvidenceLabel", "UNKNOWN");
		for (String[] mutation : new String[][] {
				{"completedSession", "scheduledOpen", "2026-07-29T20:00:00Z"},
				{"completedSession", "scheduledClose", "2026-07-29T20:00:02Z"},
				{"completedSession", "completedAt", "2026-07-29T20:05:01Z"},
				{"decisionTiming", "decisionCutoff", "2026-07-29T20:07:01Z"},
				{"evidence", "effectiveAt", "2026-07-29T20:05:01Z"},
				{"evidence", "availableAt", "2026-07-29T20:07:01Z"},
				{"evidence", "retrievedAt", "2026-07-29T20:04:59Z"},
				{"evidence", "retrievedAt", "2026-07-29T20:07:01Z"}
		}) {
			assertRejected(mutation[0], mutation[1], mutation[2]);
		}
	}

	@Test
	void canonicalDecimalsRejectSpecialExponentAndWrongJsonTypes()
			throws Exception {
		for (Object badValue : new Object[] {
				"NaN", "Infinity", "-Infinity", "1e3", "0x10", 12.5, true
		}) {
			for (String[] path : new String[][] {
				{"fundamentalValueOutput", "fairValue", "central"},
				{"fundamentalValueOutput", "fairValue", "rangeLow"},
				{"fundamentalValueOutput", "fairValue", "rangeHigh"},
				{"fundamentalValueOutput", null, "referencePrice"},
				{"fundamentalValueOutput", null, "marginOfSafety"},
				{"fundamentalValueOutput", null, "maximumAllocationCap"},
				{"quantTradePlanOutput", null, "entryRangeLow"},
				{"quantTradePlanOutput", null, "entryRangeHigh"},
				{"quantTradePlanOutput", null, "stop"},
				{"quantTradePlanOutput", null, "maximumPositionRisk"},
				{"quantTradePlanOutput", "liquidityAssumptions",
					"averageDailyDollarVolume"},
				{"quantTradePlanOutput", "liquidityAssumptions",
					"maximumParticipationRate"},
				{"quantTradePlanOutput", "costAssumptions", "transactionCostBps"},
				{"quantTradePlanOutput", "costAssumptions", "slippageBps"}
			}) {
				ObjectNode root = fixtureTree();
				ObjectNode parent = (ObjectNode) root.get(path[0]);
				if (path[1] != null) {
					parent = (ObjectNode) parent.get(path[1]);
				}
				putValue(parent, path[2], badValue);
				assertTreeRejected(root);
			}
			ObjectNode root = fixtureTree();
			var targets = (tools.jackson.databind.node.ArrayNode)
					root.get("quantTradePlanOutput").get("targets");
			targets.remove(0);
			addValue(targets, badValue);
			assertTreeRejected(root);
		}
	}

	@Test
	void datesAndTimestampsUseStrictCalendarAndRfc3339Grammar()
			throws Exception {
		for (String badDate : new String[] {
				"2026-99-99", "2026-02-30", "2026-04-31"
		}) {
			assertRejected("completedSession", "sessionDate", badDate);
		}
		for (Object badTimestamp : new Object[] {
				"", "2026-07-29", "July 29 2026",
				"2026-07-29T20:00:00", 123, true
		}) {
			for (String[] path : new String[][] {
				{"decisionTiming", "decisionCutoff"},
				{"completedSession", "scheduledOpen"},
				{"evidence", "availableAt"},
				{"evidence", "retrievedAt"},
				{"evidence", "staleAfter"}
			}) {
				ObjectNode root = fixtureTree();
				putValue((ObjectNode) root.get(path[0]), path[1], badTimestamp);
				assertTreeRejected(root);
			}
		}
	}

	@Test
	void structuredEvidenceAndBooleanFieldsRejectJsonCoercion()
			throws Exception {
		for (String field : new String[] {"conflict", "fieldTolerancePolicy"}) {
			for (Object badValue : new Object[] {"text", 1, true}) {
				ObjectNode root = fixtureTree();
				putValue((ObjectNode) root.get("evidence"), field, badValue);
				assertTreeRejected(root);
			}
			ObjectNode root = fixtureTree();
			((ObjectNode) root.get("evidence")).putArray(field);
			assertTreeRejected(root);
		}
		for (Object badValue : new Object[] {"true", 1, null}) {
			ObjectNode root = fixtureTree();
			putValue(
					(ObjectNode) root.get("evidence").get("fieldTolerancePolicy"),
					"alignmentSatisfied", badValue);
			assertTreeRejected(root);
			root = fixtureTree();
			putValue(
					(ObjectNode) root.get("completedSession"),
					"earlyClose", badValue);
			assertTreeRejected(root);
		}
	}

	@Test
	void wireDecoderRejectsNonStringCanonicalIdentityAndReferenceFields()
			throws Exception {
		for (String[] path : new String[][] {
				{"security", "securityId"},
				{"completedSession", "calendarId"},
				{"fundamentalValueOutput", "modelVersion"},
				{"versionSet", "calendarVersion"}
		}) {
			ObjectNode root = fixtureTree();
			((ObjectNode) root.get(path[0])).put(path[1], 123);
			assertTreeRejected(root);
		}
		ObjectNode root = fixtureTree();
		((ObjectNode) root.get("portfolioRiskView").get("sleeves").get(0))
			.put("engineOutputId", true);
		assertTreeRejected(root);

		for (String location : new String[] {
				"fundamentalValueOutput", "quantTradePlanOutput"
		}) {
			root = fixtureTree();
			var benchmarks = (tools.jackson.databind.node.ArrayNode)
					root.get(location).get("benchmarkCodes");
			benchmarks.remove(0);
			benchmarks.add(123);
			assertTreeRejected(root);
		}
	}

	@Test
	void oversizedDistinctReversedFairValueRangeFailsExactly() throws Exception {
		ObjectNode root = fixtureTree();
		ObjectNode fairValue = (ObjectNode)
				root.get("fundamentalValueOutput").get("fairValue");
		fairValue.put("rangeLow", "7".repeat(401));
		fairValue.put("central", "8".repeat(401));
		fairValue.put("rangeHigh", "9".repeat(401));
		DualSystemArchitectureContract.decode(mapper, root.toString());
		fairValue.put("rangeLow", "9".repeat(401));
		fairValue.put("central", "8".repeat(401));
		fairValue.put("rangeHigh", "7".repeat(401));
		assertTreeRejected(root);
	}

	private void assertRejected(String objectName, String fieldName, Object value)
			throws Exception {
		ObjectNode root = (ObjectNode) mapper.readTree(Files.readString(fixture()));
		ObjectNode object = (ObjectNode) root.get(objectName);
		if (value == null) {
			object.putNull(fieldName);
		} else if (value instanceof Boolean booleanValue) {
			object.put(fieldName, booleanValue);
		} else {
			object.put(fieldName, value.toString());
		}
		assertThatThrownBy(() -> DualSystemArchitectureContract.decode(
				mapper, root.toString()))
			.isInstanceOf(Exception.class);
	}

	private void assertNestedRejected(
			String objectName, String nestedName, String fieldName, Object value)
			throws Exception {
		ObjectNode root = (ObjectNode) mapper.readTree(Files.readString(fixture()));
		ObjectNode nested = (ObjectNode) root.get(objectName).get(nestedName);
		if (value == null) {
			nested.putNull(fieldName);
		} else {
			nested.put(fieldName, value.toString());
		}
		assertThatThrownBy(() -> DualSystemArchitectureContract.decode(
				mapper, root.toString()))
			.isInstanceOf(Exception.class);
	}

	private void assertNestedRejected(
			String firstObject, String firstField, Object firstValue,
			String secondObject, String secondField, Object secondValue)
			throws Exception {
		ObjectNode root = (ObjectNode) mapper.readTree(Files.readString(fixture()));
		((ObjectNode) root.get(firstObject)).put(firstField, firstValue.toString());
		((ObjectNode) root.get(secondObject)).put(secondField, secondValue.toString());
		assertThatThrownBy(() -> DualSystemArchitectureContract.decode(
				mapper, root.toString()))
			.isInstanceOf(Exception.class);
	}

	private Path fixture() {
		return Path.of(
				"..", "contracts", "dual-system-architecture-v1",
				"decision-context.example.json");
	}

	private ObjectNode fixtureTree() throws Exception {
		return (ObjectNode) mapper.readTree(Files.readString(fixture()));
	}

	private void assertTreeRejected(ObjectNode root) {
		assertThatThrownBy(() -> DualSystemArchitectureContract.decode(
				mapper, root.toString()))
			.isInstanceOf(Exception.class);
	}

	private void assertMissingAndNullRejected(String objectName, String fieldName)
			throws Exception {
		ObjectNode missing = fixtureTree();
		((ObjectNode) missing.get(objectName)).remove(fieldName);
		assertTreeRejected(missing);
		ObjectNode explicitNull = fixtureTree();
		((ObjectNode) explicitNull.get(objectName)).putNull(fieldName);
		assertTreeRejected(explicitNull);
	}

	private void putValue(ObjectNode object, String field, Object value) {
		if (value == null) {
			object.putNull(field);
		} else if (value instanceof Boolean booleanValue) {
			object.put(field, booleanValue);
		} else if (value instanceof Integer integerValue) {
			object.put(field, integerValue);
		} else if (value instanceof Double doubleValue) {
			object.put(field, doubleValue);
		} else {
			object.put(field, value.toString());
		}
	}

	private void addValue(
			tools.jackson.databind.node.ArrayNode array, Object value) {
		if (value instanceof Boolean booleanValue) {
			array.add(booleanValue);
		} else if (value instanceof Integer integerValue) {
			array.add(integerValue);
		} else if (value instanceof Double doubleValue) {
			array.add(doubleValue);
		} else {
			array.add(value.toString());
		}
	}
}
