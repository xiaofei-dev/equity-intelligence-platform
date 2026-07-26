package com.xiaofei.equity.screening;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;

import com.xiaofei.equity.screening.ScreeningRatingContract.AssessmentStatus;
import com.xiaofei.equity.screening.ScreeningRatingContract.Horizon;
import com.xiaofei.equity.screening.ScreeningRatingContract.RatingPage;

import tools.jackson.databind.json.JsonMapper;

class ScreeningRatingContractTests {

	@Test
	void deserializesSharedPythonJavaContractFixtureWithoutPrecisionLoss() throws Exception {
		Path fixture = findFixture();
		JsonMapper objectMapper = JsonMapper.builder().findAndAddModules().build();

		RatingPage page = objectMapper.readValue(Files.readString(fixture), RatingPage.class);

		assertThat(page.runId()).isEqualTo("screening-run-2026-07-26-001");
		assertThat(page.items()).hasSize(1);
		assertThat(page.items().getFirst().symbol()).isEqualTo("AAPL");
		assertThat(page.items().getFirst().qualityScore())
				.isEqualByComparingTo(new BigDecimal("82.5000"));
		assertThat(page.items().getFirst().factorResults().getFirst().rawValue())
				.isEqualByComparingTo(new BigDecimal("0.3750"));
		assertThat(page.items().getFirst().horizonAssessments())
				.anySatisfy(assessment -> {
					assertThat(assessment.horizon()).isEqualTo(Horizon.MEDIUM_TERM);
					assertThat(assessment.status()).isEqualTo(AssessmentStatus.NOT_DEFINED);
					assertThat(assessment.score()).isNull();
				});
	}

	private Path findFixture() {
		Path fromRepositoryRoot = Path.of("contracts", "screening-rating-v1.example.json");
		if (Files.exists(fromRepositoryRoot)) {
			return fromRepositoryRoot;
		}
		Path fromModuleRoot = Path.of("..", "contracts", "screening-rating-v1.example.json");
		if (Files.exists(fromModuleRoot)) {
			return fromModuleRoot;
		}
		throw new IllegalStateException("Shared screening contract fixture was not found");
	}
}
