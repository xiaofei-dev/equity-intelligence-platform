package com.xiaofei.equity.fundamentalvalue;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;

class CurrentFundamentalValueArchitectureTests {

	@Test
	void currentAssessmentSurfaceIsGetOnlyAndHasNoDatabaseOrProviderPath() throws Exception {
		Path root = Path.of("src", "main", "java", "com", "xiaofei", "equity",
				"fundamentalvalue");
		String controller = Files.readString(root.resolve(
				"CurrentFundamentalValueController.java"));
		String client = Files.readString(root.resolve(
				"CurrentFundamentalValueAnalyticsClient.java"));
		String combined = controller + client + Files.readString(root.resolve(
				"CurrentFundamentalValueService.java"));

		assertThat(controller).contains("@GetMapping").doesNotContain(
				"@PostMapping", "@PutMapping", "@PatchMapping", "@DeleteMapping");
		assertThat(client).contains("/internal/v1/fundamental-value/current-assessments")
				.doesNotContain(".post()", ".put()", ".delete()");
		assertThat(combined.toLowerCase()).doesNotContain(
				"jdbc", "datasource", "eodhd_api_key", "yfinance");
	}
}
