package com.xiaofei.equity.marketdata;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;

public record LatestMarketDataItem(
		String symbol,
		String name,
		String exchange,
		String instrumentType,
		LocalDate tradingDate,
		BigDecimal closePrice,
		Long volume,
		String provider,
		Instant ingestedAt) {
}
