package com.xiaofei.equity.quanttrading;

import java.util.UUID;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.xiaofei.equity.quanttrading.QuantResearchContract.ResearchDecisionResponse;
import com.xiaofei.equity.usercontext.ClosedTestIdentityResolver;

@RestController
@RequestMapping("/api/v1/quant-trading/research-decisions")
public class QuantResearchController {
	private final ClosedTestIdentityResolver identityResolver;
	private final QuantResearchService service;

	public QuantResearchController(
			ClosedTestIdentityResolver identityResolver, QuantResearchService service) {
		this.identityResolver = identityResolver;
		this.service = service;
	}

	@GetMapping("/{decisionId}")
	public ResearchDecisionResponse read(
			@RequestHeader(ClosedTestIdentityResolver.IDENTITY_HEADER) String identity,
			@PathVariable String decisionId) {
		identityResolver.resolve(identity);
		try {
			UUID parsed = UUID.fromString(decisionId);
			if (!parsed.toString().equals(decisionId)) throw new IllegalArgumentException();
			return service.read(parsed);
		}
		catch (IllegalArgumentException exception) {
			throw new QuantResearchGatewayException("INVALID_QUANT_RESEARCH_REQUEST",
					"The Quant research request is invalid.", 400);
		}
	}
}
