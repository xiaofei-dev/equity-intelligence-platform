package com.xiaofei.equity.forwardvalidation;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;

import com.xiaofei.equity.forwardvalidation.ForwardValidationContract.ForwardReport;

import tools.jackson.databind.json.JsonMapper;

class ForwardValidationContractTests {

	@Test
	void sharedFixturePreservesPrecisionAndStatisticalBoundary() throws Exception {
		var mapper = JsonMapper.builder().findAndAddModules().build();
		var path = Path.of("..", "contracts", "forward-validation-v1.example.json");
		var report = mapper.readValue(Files.readString(path), ForwardReport.class);

		assertThat(report.operationalCompleteness())
				.isEqualByComparingTo(new BigDecimal("0.97500000"));
		assertThat(report.statisticalEdgeProven()).isEqualTo("NOT_ESTABLISHED");
		assertThat(report.preliminaryConclusion().name()).isEqualTo("INSUFFICIENT_SAMPLE");
	}
}
