package com.xiaofei.equity.fundamentalvalue;

import java.net.URI;
import java.util.Set;
import java.util.UUID;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.xiaofei.equity.fundamentalvalue.FundamentalValueContract.DecisionRequest;
import com.xiaofei.equity.fundamentalvalue.FundamentalValueContract.DecisionResponse;
import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@RestController
@RequestMapping("/api/v1/fundamental-value/decisions")
public class FundamentalValueController {
	private static final JsonMapper STRICT_MAPPER = JsonMapper.builder()
			.enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES).build();

	private final ClosedTestIdentityResolver identityResolver;
	private final FundamentalValueService service;

	public FundamentalValueController(
			ClosedTestIdentityResolver identityResolver, FundamentalValueService service) {
		this.identityResolver = identityResolver;
		this.service = service;
	}

	@PostMapping
	public ResponseEntity<DecisionResponse> create(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@RequestHeader("Idempotency-Key") String idempotencyKey,
			@RequestBody JsonNode requestBody) {
		identityResolver.resolve(identity);
		if (idempotencyKey.isBlank()) {
			throw new FundamentalValueGatewayException("IDEMPOTENCY_KEY_REQUIRED",
					"A non-blank idempotency key is required.", 400);
		}
		DecisionRequest request = parseRequest(requestBody);
		DecisionResponse response = service.create(request, idempotencyKey);
		return ResponseEntity.created(URI.create(
				"/api/v1/fundamental-value/decisions/" + response.assemblyId())).body(response);
	}

	static DecisionRequest parseRequest(JsonNode requestBody) {
		try {
			Set<String> fields = Set.of("contractVersion", "routingId",
					"classificationRequestId", "operandRequestIds", "projectionYears");
			JsonNode years = requestBody.get("projectionYears");
			if (!requestBody.isObject()
					|| !Set.copyOf(requestBody.propertyNames()).equals(fields)
					|| !requestBody.get("contractVersion").isTextual()
					|| !uuid(requestBody.get("routingId"))
					|| !uuid(requestBody.get("classificationRequestId"))
					|| !requestBody.get("operandRequestIds").isArray()
					|| years == null || !years.isIntegralNumber() || !years.canConvertToInt()
					|| years.asInt() < 3 || years.asInt() > 10) {
				throw new IllegalArgumentException("Invalid request wire shape");
			}
			for (JsonNode operand : requestBody.get("operandRequestIds")) {
				if (!operand.isObject()
						|| !Set.copyOf(operand.propertyNames()).equals(
								Set.of("operandCode", "requestId"))
						|| !operand.get("operandCode").isTextual()
						|| operand.get("operandCode").asText().isBlank()
						|| !uuid(operand.get("requestId"))) {
					throw new IllegalArgumentException("Invalid operand wire shape");
				}
			}
			return STRICT_MAPPER.treeToValue(requestBody, DecisionRequest.class);
		}
		catch (RuntimeException exception) {
			throw new FundamentalValueGatewayException("INVALID_FUNDAMENTAL_VALUE_REQUEST",
					"The Fundamental Value request is invalid.", 400);
		}
	}

	private static boolean uuid(JsonNode value) {
		if (value == null || !value.isTextual()) return false;
		try {
			UUID parsed = UUID.fromString(value.asText());
			return parsed.toString().equals(value.asText());
		}
		catch (IllegalArgumentException exception) {
			return false;
		}
	}

	@GetMapping("/{assemblyId}")
	public DecisionResponse read(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable String assemblyId) {
		identityResolver.resolve(identity);
		JsonNode rawId = STRICT_MAPPER.getNodeFactory().textNode(assemblyId);
		if (!uuid(rawId)) {
			throw new FundamentalValueGatewayException("INVALID_FUNDAMENTAL_VALUE_REQUEST",
					"The Fundamental Value request is invalid.", 400);
		}
		return service.read(UUID.fromString(assemblyId));
	}
}
