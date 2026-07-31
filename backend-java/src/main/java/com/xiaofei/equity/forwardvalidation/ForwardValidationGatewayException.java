package com.xiaofei.equity.forwardvalidation;

public class ForwardValidationGatewayException extends RuntimeException {

	private final String code;

	private final int status;

	public ForwardValidationGatewayException(String code, String message, int status) {
		super(message);
		this.code = code;
		this.status = status;
	}

	public String code() {
		return code;
	}

	public int status() {
		return status;
	}
}
