package com.xiaofei.equity.portfolio;

import java.time.Instant;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = {
		UnifiedPortfolioContextController.class,
		PortfolioDecisionController.class
})
public class UnifiedPortfolioContextExceptionHandler {
	public record ApiError(String code, String message, Instant timestamp) {}

	@ExceptionHandler(PortfolioContextException.class)
	ResponseEntity<ApiError> handle(PortfolioContextException error) {
		return ResponseEntity.status(error.status())
				.body(new ApiError(error.code(), error.getMessage(), Instant.now()));
	}
}
