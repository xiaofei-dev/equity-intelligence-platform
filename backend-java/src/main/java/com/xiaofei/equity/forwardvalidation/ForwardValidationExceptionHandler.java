package com.xiaofei.equity.forwardvalidation;

import java.time.Instant;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = ForwardValidationController.class)
public class ForwardValidationExceptionHandler {

	@ExceptionHandler(ForwardValidationGatewayException.class)
	ResponseEntity<ApiError> handleGatewayException(
			ForwardValidationGatewayException exception) {
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

	public record ApiError(String code, String message, Instant timestamp) {
	}
}
