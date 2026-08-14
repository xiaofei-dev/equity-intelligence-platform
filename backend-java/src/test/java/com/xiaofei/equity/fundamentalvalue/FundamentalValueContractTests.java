package com.xiaofei.equity.fundamentalvalue;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;

import com.xiaofei.equity.fundamentalvalue.FundamentalValueContract.InternalDecision;
import com.xiaofei.equity.fundamentalvalue.FundamentalValueContract.DecisionRequest;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

class FundamentalValueContractTests {

	private static final Path FIXTURE = Path.of("..", "contracts", "fundamental-value-v1",
            "internal-missing-response-v1.1.example.json");

	private static final JsonMapper STRICT_MAPPER = JsonMapper.builder()
			.enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES).build();

	@Test
	void canonicalCommandFixtureHasExactCrossLanguageParity() throws Exception {
		Path command = Path.of("..", "contracts", "fundamental-value-v1",
				"internal-command.example.json");
		String json = Files.readString(command);
		DecisionRequest request = STRICT_MAPPER.readValue(json, DecisionRequest.class);
		assertThat(request.contractVersion()).isEqualTo(FundamentalValueContract.COMMAND_VERSION);
		assertThat(STRICT_MAPPER.readTree(STRICT_MAPPER.writeValueAsString(request)))
				.isEqualTo(STRICT_MAPPER.readTree(json));
	}

	@Test
	void canonicalMissingFixtureIsStrictAndNonUsable() throws Exception {
		InternalDecision response = STRICT_MAPPER.readValue(Files.readString(FIXTURE),
				InternalDecision.class);
		assertThat(response.state()).isEqualTo("MISSING");
		assertThat(response.coreInvocationAuthorized()).isFalse();
		assertThat(response.assessmentId()).isNull();
		assertThat(response.deterministicAssessment().isNull()).isTrue();
		assertThat(response.finalPortfolioWeightAuthorized()).isFalse();
		assertThat(response.automaticBrokerageExecutionAuthorized()).isFalse();
	}

	@Test
	void unknownInternalFieldFailsClosed() throws Exception {
		String changed = Files.readString(FIXTURE).replaceFirst("\\{", "{\"providerValue\":1,");
		assertThatThrownBy(() -> STRICT_MAPPER.readValue(changed, InternalDecision.class))
				.isInstanceOf(RuntimeException.class);
	}
}
