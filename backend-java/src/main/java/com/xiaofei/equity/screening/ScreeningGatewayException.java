package com.xiaofei.equity.screening;

public class ScreeningGatewayException extends RuntimeException {

	public ScreeningGatewayException(String message) {
		super(message);
	}

	public ScreeningGatewayException(String message, Throwable cause) {
		super(message, cause);
	}
}
