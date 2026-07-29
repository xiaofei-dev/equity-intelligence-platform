package com.xiaofei.equity.marketintelligence;

public class MarketIntelligenceGatewayException extends RuntimeException {

	private final String code;

	private final int status;

	public MarketIntelligenceGatewayException(String code, String message, int status) {
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
