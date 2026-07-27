package com.xiaofei.equity.marketdata;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(MarketDataController.class)
class MarketDataControllerTests {

	@Autowired
	private MockMvc mockMvc;

	@MockitoBean
	private LatestMarketDataService latestMarketDataService;

	@Test
	void returnsLatestMarketDataWithSourceTimestamps() throws Exception {
		when(latestMarketDataService.findLatest()).thenReturn(List.of(
				new LatestMarketDataItem(
						"AAPL",
						"Apple Inc.",
						"NASDAQ",
						"COMMON_STOCK",
						LocalDate.of(2026, 7, 23),
						new BigDecimal("214.150000"),
						46404100L,
						"twelve_data",
						Instant.parse("2026-07-26T06:14:28Z"))));

		mockMvc.perform(get("/api/v1/market-data/latest"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.items[0].symbol").value("AAPL"))
				.andExpect(jsonPath("$.items[0].tradingDate").value("2026-07-23"))
				.andExpect(jsonPath("$.items[0].closePrice").value(214.15))
				.andExpect(jsonPath("$.items[0].provider").value("twelve_data"))
				.andExpect(jsonPath("$.items[0].ingestedAt").value("2026-07-26T06:14:28Z"));
	}

	@Test
	void representsAConfiguredSecurityWithoutPriceData() throws Exception {
		when(latestMarketDataService.findLatest()).thenReturn(List.of(
				new LatestMarketDataItem(
						"AAPL",
						"Apple Inc.",
						"NASDAQ",
						"COMMON_STOCK",
						null,
						null,
						null,
						null,
						null)));

		mockMvc.perform(get("/api/v1/market-data/latest"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.items[0].symbol").value("AAPL"))
				.andExpect(jsonPath("$.items[0].tradingDate").doesNotExist());
	}
}
