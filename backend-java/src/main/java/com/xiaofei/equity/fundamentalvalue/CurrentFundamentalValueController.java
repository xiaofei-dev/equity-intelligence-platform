package com.xiaofei.equity.fundamentalvalue;

import java.util.UUID;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.xiaofei.equity.fundamentalvalue.CurrentFundamentalValueContract.AssessmentResponse;
import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;

@RestController
@RequestMapping("/api/v1/fundamental-value/current-assessments")
public class CurrentFundamentalValueController {

	private final ClosedTestIdentityResolver identityResolver;
	private final CurrentFundamentalValueService service;

	public CurrentFundamentalValueController(
			ClosedTestIdentityResolver identityResolver, CurrentFundamentalValueService service) {
		this.identityResolver = identityResolver;
		this.service = service;
	}

	@GetMapping("/{assessmentId}")
	public AssessmentResponse read(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable String assessmentId) {
		identityResolver.resolve(identity);
		try {
			UUID parsed = UUID.fromString(assessmentId);
			if (!parsed.toString().equals(assessmentId)) throw new IllegalArgumentException();
			return service.read(parsed);
		}
		catch (IllegalArgumentException exception) {
			throw new FundamentalValueGatewayException(
					"INVALID_CURRENT_FUNDAMENTAL_VALUE_IDENTIFIER",
					"The current assessment identifier is invalid.", 400);
		}
	}

	@GetMapping("/latest/{symbol}")
	public AssessmentResponse readLatest(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable String symbol) {
		identityResolver.resolve(identity);
		return service.readLatest(symbol);
	}
}
