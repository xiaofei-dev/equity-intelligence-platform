package com.xiaofei.equity.marketintelligence;

import java.time.Instant;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = MarketIntelligenceController.class)
public class MarketIntelligenceExceptionHandler {

	@ExceptionHandler(MarketIntelligenceGatewayException.class)
	ResponseEntity<ApiError> handleGatewayException(
			MarketIntelligenceGatewayException exception) {
		return ResponseEntity.status(exception.status())
			.body(new ApiError(exception.code(), exception.getMessage(), Instant.now()));
	}

	@ExceptionHandler(MissingRequestHeaderException.class)
	ResponseEntity<ApiError> handleMissingHeader(MissingRequestHeaderException exception) {
		String code = "Idempotency-Key".equalsIgnoreCase(exception.getHeaderName())
				? "IDEMPOTENCY_KEY_REQUIRED" : "USER_CONTEXT_MISSING";
		return ResponseEntity.badRequest().body(new ApiError(
				code, "A required request header is missing.", Instant.now()));
	}

	@ExceptionHandler(MissingServletRequestParameterException.class)
	ResponseEntity<ApiError> handleMissingParameter(
			MissingServletRequestParameterException exception) {
		return ResponseEntity.badRequest().body(new ApiError(
				"INVALID_MARKET_INTELLIGENCE_REQUEST",
				"A required request parameter is missing.",
				Instant.now()));
	}

	public record ApiError(String code, String message, Instant timestamp) {
	}
}
