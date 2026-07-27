package com.xiaofei.equity.usercontext;

import java.time.Instant;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class UserContextExceptionHandler {

	@ExceptionHandler(UserContextException.class)
	ResponseEntity<ApiError> handleUserContextException(UserContextException exception) {
		return ResponseEntity.status(exception.status())
			.body(new ApiError(exception.code(), exception.getMessage(), Instant.now()));
	}

	public record ApiError(String code, String message, Instant timestamp) {
	}
}
