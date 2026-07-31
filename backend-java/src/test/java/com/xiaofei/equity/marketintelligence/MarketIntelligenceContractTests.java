package com.xiaofei.equity.marketintelligence;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;

import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.AiNarrativeStatus;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.EligibilityRecoveryStatus;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.EligibilityRecoveryStatusResponse;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.FactState;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ProfileResponse;
import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.ScreeningRunMetadata;

import tools.jackson.databind.json.JsonMapper;

class MarketIntelligenceContractTests {

	@Test
	void profileFixtureMatchesCanonicalPythonEnvelopeAndPreservesMissingStates()
			throws Exception {
		var mapper = JsonMapper.builder().findAndAddModules().build();
		var localPath = Path.of(
				"src", "test", "resources",
				"market-intelligence-v1", "profile-response.json");
		var sharedPath = Path.of(
				"..", "contracts", "market-intelligence-v1",
				"profile-envelope.example.json");

		assertThat(Files.readAllBytes(localPath))
			.containsExactly(Files.readAllBytes(sharedPath));

		ProfileResponse response = mapper.readValue(
				Files.readString(localPath), ProfileResponse.class);

		assertThat(response.currentMarketData().state()).isEqualTo(FactState.MISSING);
		assertThat(response.currentMarketData().price()).isNull();
		assertThat(response.currentMarketData().reason())
			.isEqualTo("PRICE_OBSERVATION_MISSING");
		assertThat(response.freshness()).singleElement()
			.satisfies(item -> {
				assertThat(item.state()).isEqualTo("MISSING");
				assertThat(item.reasonCode()).isEqualTo("NO_SUCCESSFUL_REFRESH");
			});
		assertThat(response.profile().horizons()).hasSize(4);
		assertThat(response.profile().facts())
			.anySatisfy(fact -> {
				assertThat(fact.name()).isEqualTo("latest_price");
				assertThat(fact.state()).isEqualTo(FactState.MISSING);
				assertThat(fact.value().isNull()).isTrue();
				assertThat(fact.reason())
					.isEqualTo("PRICE_OBSERVATION_MISSING");
			});
		assertThat(response.profile().aiNarrative().status())
			.isEqualTo(AiNarrativeStatus.NOT_EXECUTED);
		assertThat(response.profile().aiNarrative().mayAffectDeterministicFields())
			.isFalse();
	}

	@Test
	void screeningMetadataFixtureMapsWithoutAJavaOnlyWrapper() throws Exception {
		var mapper = JsonMapper.builder().findAndAddModules().build();
		var path = Path.of(
				"..", "contracts", "market-intelligence-v1",
				"screening-run-metadata.example.json");

		ScreeningRunMetadata metadata = mapper.readValue(
				Files.readString(path), ScreeningRunMetadata.class);

		assertThat(metadata.state()).isEqualTo(
				MarketIntelligenceContract.RunState.SEALED);
		assertThat(metadata.eligibleCount()).isZero();
		assertThat(metadata.excludedCount()).isEqualTo(66);
		assertThat(metadata.gateStatus()).isEqualTo("NO_ELIGIBLE_RESULTS");
	}

	@Test
	void eligibilityRecoveryContractPreservesBlockersFreshnessAndSafetyState()
			throws Exception {
		var mapper = JsonMapper.builder().findAndAddModules().build();

		EligibilityRecoveryStatusResponse response = mapper.readValue(
				eligibilityResponseJson(), EligibilityRecoveryStatusResponse.class);

		assertThat(response.status())
			.isEqualTo(EligibilityRecoveryStatus.READY_FOR_CONFIRMATION);
		assertThat(response.currentEligibleCount()).isEqualTo(6);
		assertThat(response.frozenMinimumEligibleCount()).isEqualTo(20);
		assertThat(response.blockerSummary()).singleElement()
			.satisfies(blocker -> {
				assertThat(blocker.category())
					.isEqualTo("MISSING_REQUIRED_EVIDENCE");
				assertThat(blocker.affectedSecurityCount()).isEqualTo(49);
			});
		assertThat(response.freshness()).singleElement()
			.satisfies(freshness -> {
				assertThat(freshness.datasetCode()).isEqualTo("FUNDAMENTALS");
				assertThat(freshness.staleAfter()).isNull();
			});
		assertThat(response.securityDiagnostics()).singleElement()
			.satisfies(diagnostic -> {
				assertThat(diagnostic.state().name()).isEqualTo("RECOVERABLE");
				assertThat(diagnostic.missingOperands()).singleElement()
					.satisfies(operand -> assertThat(operand.operandCode())
						.isEqualTo("interest_expense_ttm"));
			});
		assertThat(response.confirmationRequired()).isTrue();
		assertThat(response.networkRequestsExecuted()).isFalse();
		assertThat(response.scoresOrRanksGenerated()).isFalse();
	}

	static String eligibilityResponseJson() {
		return """
				{
				  "schemaVersion":"market-intelligence-eligibility-recovery-status-v1.0.0",
				  "preflightId":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				  "generatedAt":"2026-07-29T03:00:00Z",
				  "dataSnapshotId":"00000000-0000-0000-0000-000000000010",
				  "universeVersion":"market-intelligence-closed-test-us-v1.0.0",
				  "snapshotAsOf":"2026-07-29T02:57:08.988871Z",
				  "objectiveRatingVersion":"Objective-Rating-v1",
				  "recoveryPolicyVersion":
				    "MARKET-INTELLIGENCE-ELIGIBILITY-RECOVERY-v1.0.0",
				  "status":"READY_FOR_CONFIRMATION",
				  "currentEligibleCount":6,
				  "frozenMinimumEligibleCount":20,
				  "maximumEligibleAfterPlan":20,
				  "dueSecurityCount":14,
				  "dueSymbols":["TTC"],
				  "persistedEvidenceReuseCount":1,
				  "profileCount":66,
				  "resultCount":66,
				  "requestPlan":[{
				    "provider":"YAHOO",
				    "endpointCode":"FUNDAMENTALS_TIMESERIES",
				    "dataset":"FUNDAMENTALS",
				    "symbols":["TTC"],
				    "physicalRequestHardCeiling":1,
				    "weightedCallHardCeiling":0,
				    "runnerMaximumAttempts":1
				  }],
				  "blockerSummary":[{
				    "category":"MISSING_REQUIRED_EVIDENCE",
				    "reasonCode":"OBJECTIVE_RATING_V1_NOT_AVAILABLE_FOR_SNAPSHOT",
				    "actionability":"ACTIONABLE_EVIDENCE_ACQUISITION",
				    "affectedSecurityCount":49
				  }],
				  "freshness":[{
				    "datasetCode":"FUNDAMENTALS",
				    "state":"CURRENT",
				    "evaluatedAt":"2026-07-29T03:00:00Z",
				    "staleAfter":null,
				    "reasonCode":null,
				    "affectedSecurityCount":55
				  }],
				  "securityDiagnostics":[{
				    "securityId":"00000000-0000-0000-0000-000000000011",
				    "symbol":"TTC",
				    "state":"RECOVERABLE",
				    "missingOperands":[{
				      "factorCode":"interest_coverage",
				      "operandCode":"interest_expense_ttm",
				      "reasonCode":"MISSING_REQUIRED_EVIDENCE",
				      "providerRoute":"YAHOO",
				      "actionability":"ACTIONABLE_EVIDENCE_ACQUISITION"
				    }],
				    "freshness":[{
				      "datasetCode":"FUNDAMENTALS",
				      "state":"CURRENT",
				      "evaluatedAt":"2026-07-29T03:00:00Z",
				      "staleAfter":null,
				      "reasonCode":null
				    }]
				  }],
				  "confirmationRequired":true,
				  "networkRequestsExecuted":false,
				  "scoresOrRanksGenerated":false,
				  "artifactContentHash":
				    "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
				}
				""";
	}
}
