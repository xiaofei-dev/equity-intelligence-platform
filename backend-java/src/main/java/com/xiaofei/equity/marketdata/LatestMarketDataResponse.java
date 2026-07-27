package com.xiaofei.equity.marketdata;

import java.time.Instant;
import java.util.List;

public record LatestMarketDataResponse(
		Instant generatedAt,
		List<LatestMarketDataItem> items) {
}
