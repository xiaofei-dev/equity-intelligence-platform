package com.xiaofei.equity.quanttrading;

public final class QuantResearchGatewayException extends RuntimeException {
	private final String code;
	private final int status;

	public QuantResearchGatewayException(String code, String message, int status) {
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
