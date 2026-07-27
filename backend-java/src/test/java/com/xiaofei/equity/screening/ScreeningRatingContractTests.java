package com.xiaofei.equity.screening;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;

import com.xiaofei.equity.screening.ScreeningRatingContract.AssessmentStatus;
import com.xiaofei.equity.screening.ScreeningRatingContract.Horizon;
import com.xiaofei.equity.screening.ScreeningRatingContract.RatingPage;
import com.xiaofei.equity.screening.ScreeningRatingContract.ScreeningRunAccepted;
import com.xiaofei.equity.screening.ScreeningRatingContract.ScreeningRunRequest;
import com.xiaofei.equity.screening.ScreeningRatingContract.ScreeningRunStatus;

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

	@Test
	void deserializesSharedRunLifecycleFixtures() throws Exception {
		JsonMapper objectMapper = JsonMapper.builder().findAndAddModules().build();

		ScreeningRunRequest request = objectMapper.readValue(
				Files.readString(findFixture("screening-run-request-v1.example.json")),
				ScreeningRunRequest.class);
		ScreeningRunAccepted accepted = objectMapper.readValue(
				Files.readString(findFixture("screening-run-accepted-v1.example.json")),
				ScreeningRunAccepted.class);
		ScreeningRunStatus status = objectMapper.readValue(
				Files.readString(findFixture("screening-run-status-v1.example.json")),
				ScreeningRunStatus.class);

		assertThat(request.strategyVersions()).containsExactly("QC-v1.0.0", "UQ-v1.0.0");
		assertThat(accepted.status()).isEqualTo(ScreeningRatingContract.RunStatus.PENDING);
		assertThat(status.coverage().universeCount()).isEqualTo(20);
	}

	private Path findFixture() {
		return findFixture("screening-rating-v1.example.json");
	}

	private Path findFixture(String fileName) {
		Path fromRepositoryRoot = Path.of("contracts", fileName);
		if (Files.exists(fromRepositoryRoot)) {
			return fromRepositoryRoot;
		}
		Path fromModuleRoot = Path.of("..", "contracts", fileName);
		if (Files.exists(fromModuleRoot)) {
			return fromModuleRoot;
		}
		throw new IllegalStateException("Shared screening contract fixture was not found");
	}
}
