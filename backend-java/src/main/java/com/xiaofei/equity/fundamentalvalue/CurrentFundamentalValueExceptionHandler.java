package com.xiaofei.equity.fundamentalvalue;

import java.time.Instant;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = CurrentFundamentalValueController.class)
public class CurrentFundamentalValueExceptionHandler {

	@ExceptionHandler(FundamentalValueGatewayException.class)
	ResponseEntity<ApiError> handleGateway(FundamentalValueGatewayException exception) {
		return ResponseEntity.status(exception.status())
				.body(new ApiError(exception.code(), exception.getMessage(), Instant.now()));
	}

	@ExceptionHandler(MissingRequestHeaderException.class)
	ResponseEntity<ApiError> handleMissingHeader(MissingRequestHeaderException exception) {
		return ResponseEntity.badRequest().body(new ApiError(
				"USER_CONTEXT_MISSING", "A required request header is missing.", Instant.now()));
	}

	public record ApiError(String code, String message, Instant timestamp) {
	}
}
