package com.xiaofei.equity.marketdata;

import java.util.List;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

@Service
public class LatestMarketDataService {

	private static final String LATEST_MARKET_DATA_SQL = """
			WITH ranked_prices AS (
			    SELECT
			        security_id,
			        trading_date,
			        close_price,
			        volume,
			        provider,
			        ingested_at,
			        ROW_NUMBER() OVER (
			            PARTITION BY security_id
			            ORDER BY trading_date DESC, ingested_at DESC
			        ) AS row_number
			    FROM analytics.daily_price
			)
			SELECT
			    security.symbol,
			    security.name,
			    security.exchange,
			    security.instrument_type,
			    price.trading_date,
			    price.close_price,
			    price.volume,
			    price.provider,
			    price.ingested_at
			FROM analytics.security security
			LEFT JOIN ranked_prices price
			    ON price.security_id = security.id
			    AND price.row_number = 1
			WHERE security.active = TRUE
			ORDER BY security.symbol
			""";

	private final JdbcClient jdbcClient;

	public LatestMarketDataService(JdbcClient jdbcClient) {
		this.jdbcClient = jdbcClient;
	}

	public List<LatestMarketDataItem> findLatest() {
		return jdbcClient.sql(LATEST_MARKET_DATA_SQL)
				.query((resultSet, rowNumber) -> {
					var ingestedAt = resultSet.getObject(
							"ingested_at",
							java.time.OffsetDateTime.class);
					return new LatestMarketDataItem(
							resultSet.getString("symbol"),
							resultSet.getString("name"),
							resultSet.getString("exchange"),
							resultSet.getString("instrument_type"),
							resultSet.getObject("trading_date", java.time.LocalDate.class),
							resultSet.getBigDecimal("close_price"),
							resultSet.getObject("volume", Long.class),
							resultSet.getString("provider"),
							ingestedAt == null ? null : ingestedAt.toInstant());
				})
				.list();
	}
}
