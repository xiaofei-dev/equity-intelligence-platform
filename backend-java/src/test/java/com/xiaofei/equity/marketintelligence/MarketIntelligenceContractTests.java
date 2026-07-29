package com.xiaofei.equity.marketintelligence;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;

import com.xiaofei.equity.marketintelligence.MarketIntelligenceContract.AiNarrativeStatus;
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
}
