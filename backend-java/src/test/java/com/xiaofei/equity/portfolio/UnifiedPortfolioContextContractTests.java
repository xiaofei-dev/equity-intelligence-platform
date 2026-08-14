package com.xiaofei.equity.portfolio;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;

import tools.jackson.databind.node.ObjectNode;
import tools.jackson.databind.json.JsonMapper;

class UnifiedPortfolioContextContractTests {
	private static final JsonMapper MAPPER = JsonMapper.builder().build();
	private static final Path FIXTURE = Path.of("..", "contracts", "unified-portfolio-risk-v1",
			"context.example.json");

	@Test
	void acceptsThePythonGeneratedCrossLanguageFixture() throws Exception {
		ObjectNode root = (ObjectNode) MAPPER.readTree(Files.readString(FIXTURE));
		var request = MAPPER.treeToValue(root.path("createRequest"),
				UnifiedPortfolioContracts.CreateContextRequest.class);
		var service = new UnifiedPortfolioContextService(null, null);
		assertDoesNotThrow(() -> service.validateResult(
				root.path("contextResponse").path("riskContext"), request.riskInput()));
	}

	@Test
	void rejectsIdentityConstraintAndAuthorityDrift() throws Exception {
		ObjectNode root = (ObjectNode) MAPPER.readTree(Files.readString(FIXTURE));
		var request = MAPPER.treeToValue(root.path("createRequest"),
				UnifiedPortfolioContracts.CreateContextRequest.class);
		var service = new UnifiedPortfolioContextService(null, null);
		ObjectNode identityDrift = (ObjectNode) root.path("contextResponse").path("riskContext").deepCopy();
		((ObjectNode) identityDrift.path("positions").get(0)).put("securityId",
				"00000000-0000-4000-8000-000000000999");
		assertThrows(PortfolioContextException.class,
				() -> service.validateResult(identityDrift, request.riskInput()));

		ObjectNode constraintDrift = (ObjectNode) root.path("contextResponse").path("riskContext").deepCopy();
		((ObjectNode) constraintDrift.path("constraints")).put("maximumPositionWeight", "0.9");
		assertThrows(PortfolioContextException.class,
				() -> service.validateResult(constraintDrift, request.riskInput()));

		ObjectNode authorityDrift = (ObjectNode) root.path("contextResponse").path("riskContext").deepCopy();
		((ObjectNode) authorityDrift.path("authority")).remove("finalWeightAuthority");
		assertThrows(PortfolioContextException.class,
				() -> service.validateResult(authorityDrift, request.riskInput()));
	}

	@Test
	void mapsTheExactPythonRiskResponseKeysAndCanonicalUtcInstant() throws Exception {
		ObjectNode root = (ObjectNode) MAPPER.readTree(Files.readString(FIXTURE));
		ObjectNode risk = (ObjectNode) root.path("contextResponse").path("riskContext").deepCopy();
		risk.put("asOfTime", "2026-07-29T20:10:00+00:00");
		var sleeve = (ObjectNode) risk.path("sleeves").get(0);
		sleeve.put("modelEvidenceLabel", "NOT_VALIDATED");
		sleeve.put("evidenceReferenceId", "e0bb4151-611d-5cdf-ba73-f239b9390497");
		sleeve.put("evidenceReferenceHash",
				"sha256:307bfe6cf8e7eb84ff4b436b72f0bdfc767331ebd3696d518ce242d17667845a");
		var command = UnifiedPortfolioContextService.currentRiskInput(risk);
		assertEquals("2026-07-29T20:10:00Z", command.path("asOfTime").asText());
		assertEquals("NOT_VALIDATED", command.path("sleeveEvidence").get(0).path("evidenceLabel").asText());
		assertEquals("e0bb4151-611d-5cdf-ba73-f239b9390497",
				command.path("sleeveEvidence").get(0).path("referenceId").asText());
	}
}
