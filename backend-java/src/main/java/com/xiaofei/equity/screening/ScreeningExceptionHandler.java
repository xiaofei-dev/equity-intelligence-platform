package com.xiaofei.equity.screening;

import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = ScreeningController.class)
public class ScreeningExceptionHandler {

	@ExceptionHandler(ScreeningGatewayException.class)
	ResponseEntity<Map<String, String>> gatewayFailure(ScreeningGatewayException exception) {
		return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(Map.of(
				"code", "ANALYTICS_SERVICE_UNAVAILABLE",
				"message", exception.getMessage()));
	}

	@ExceptionHandler(MissingRequestHeaderException.class)
	ResponseEntity<Map<String, String>> missingHeader(MissingRequestHeaderException exception) {
		return ResponseEntity.badRequest().body(Map.of(
				"code", "IDEMPOTENCY_KEY_REQUIRED",
				"message", exception.getMessage()));
	}
}
