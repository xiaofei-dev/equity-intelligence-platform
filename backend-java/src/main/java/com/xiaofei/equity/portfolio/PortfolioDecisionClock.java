package com.xiaofei.equity.portfolio;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Arrays;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

/** Server-owned clock with a closed-test-only deterministic boundary. */
@Component
final class PortfolioDecisionClock {
	private final Instant controlled;

	PortfolioDecisionClock(@Value("${portfolio-decision.controlled-now:}") String value,
			Environment environment) {
		if (value == null || value.isBlank()) {
			controlled = null;
			return;
		}
		if (Arrays.stream(environment.getActiveProfiles()).noneMatch("task5-e2e"::equals)) {
			throw new IllegalStateException("Controlled portfolio decision time requires task5-e2e profile");
		}
		controlled = Instant.parse(value).truncatedTo(ChronoUnit.SECONDS);
	}

	PortfolioDecisionClock() {
		controlled = null;
	}

	Instant now() {
		return (controlled == null ? Instant.now() : controlled).truncatedTo(ChronoUnit.SECONDS);
	}
}
