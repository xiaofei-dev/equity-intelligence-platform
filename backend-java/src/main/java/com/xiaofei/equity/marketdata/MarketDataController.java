package com.xiaofei.equity.marketdata;

import java.time.Instant;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/market-data")
public class MarketDataController {

	private final LatestMarketDataService latestMarketDataService;

	public MarketDataController(LatestMarketDataService latestMarketDataService) {
		this.latestMarketDataService = latestMarketDataService;
	}

	@GetMapping("/latest")
	public ResponseEntity<LatestMarketDataResponse> latest() {
		return ResponseEntity.ok(new LatestMarketDataResponse(
				Instant.now(),
				latestMarketDataService.findLatest()));
	}
}
