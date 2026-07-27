package com.xiaofei.equity.portfolio;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

class PortfolioCalculationContractTests {

	@Test
	void parsesSharedV1RequestFixture() throws IOException {
		Path fixture = fixturePath("portfolio-calculation-request-v1.example.json");
		var mapper = JsonMapper.builder().findAndAddModules().build();

		PortfolioCalculationContract.CalculationRequest request = mapper.readValue(
				Files.readString(fixture),
				PortfolioCalculationContract.CalculationRequest.class);

		assertThat(request.contractVersion())
			.isEqualTo(PortfolioCalculationContract.VERSION);
		assertThat(request.baseCurrency()).isEqualTo("USD");
		assertThat(request.accounts()).hasSize(1);
		assertThat(request.rebalancingPermissions()).hasSize(1);
		assertThat(request.constraints().maximumLeverageRatio()).isZero();
	}

	private static Path fixturePath(String fileName) {
		Path fromModule = Path.of("..", "contracts", fileName);
		if (Files.exists(fromModule)) {
			return fromModule;
		}
		return Path.of("contracts", fileName);
	}
}
