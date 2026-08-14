package com.xiaofei.equity.fundamentalvalue;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;

class FundamentalValueArchitectureTests {

	@Test
	void springBoundaryContainsNoFormulaDatabaseQuantOrBrokerageDependency() throws IOException {
		Path root = Path.of("src", "main", "java", "com", "xiaofei", "equity",
				"fundamentalvalue");
		String source;
		try (var files = Files.list(root)) {
			source = files.filter(path -> path.toString().endsWith(".java"))
					.map(FundamentalValueArchitectureTests::read)
					.reduce("", String::concat);
		}
		assertThat(source).doesNotContain(
				"java.sql", "javax.sql", "JdbcClient", "JpaRepository",
				"portfolio", "screening", "tactical", "brokerage", "tradeOrder",
				"discountRate", "terminalGrowth", "presentValue", "weightedMedian");
	}

	private static String read(Path path) {
		try {
			return Files.readString(path);
		}
		catch (IOException exception) {
			throw new IllegalStateException(exception);
		}
	}
}
