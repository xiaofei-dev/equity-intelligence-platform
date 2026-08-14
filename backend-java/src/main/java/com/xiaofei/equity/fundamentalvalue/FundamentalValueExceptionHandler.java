package com.xiaofei.equity.fundamentalvalue;

import java.time.Instant;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = FundamentalValueController.class)
public class FundamentalValueExceptionHandler {

	@ExceptionHandler(FundamentalValueGatewayException.class)
	ResponseEntity<ApiError> handleGateway(FundamentalValueGatewayException exception) {
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

	@ExceptionHandler(HttpMessageNotReadableException.class)
	ResponseEntity<ApiError> handleMalformedBody(HttpMessageNotReadableException exception) {
		return ResponseEntity.badRequest().body(new ApiError(
				"INVALID_FUNDAMENTAL_VALUE_REQUEST",
				"The Fundamental Value request body is invalid.", Instant.now()));
	}

	public record ApiError(String code, String message, Instant timestamp) {
	}
}
