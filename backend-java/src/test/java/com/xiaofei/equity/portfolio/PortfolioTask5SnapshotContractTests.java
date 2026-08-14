package com.xiaofei.equity.portfolio;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.Test;

import com.xiaofei.equity.portfolio.PortfolioContracts.CashBalanceInput;
import com.xiaofei.equity.portfolio.PortfolioContracts.CreateSnapshotRequest;
import com.xiaofei.equity.portfolio.PortfolioContracts.PositionInput;
import com.xiaofei.equity.portfolio.PortfolioContracts.SnapshotCompleteness;
import com.xiaofei.equity.portfolio.PortfolioContracts.SnapshotSource;

class PortfolioTask5SnapshotContractTests {
	@Test
	void matchesTheV29GraphOnlyCanonicalAtoms() {
		var request=new CreateSnapshotRequest(Instant.parse("2026-07-29T20:10:00Z"),SnapshotSource.MANUAL,
				"TASK5:SYNTHETIC-USD100K",SnapshotCompleteness.COMPLETE,
				List.of(new CashBalanceInput("USD",new BigDecimal("20000.00"),BigDecimal.ZERO,BigDecimal.ZERO)),
				List.of(new PositionInput(UUID.fromString("86ab36e1-6a7e-4723-8571-6b5adb674df0"),
						new BigDecimal("800.0"),new BigDecimal("100.00"),"USD")));
		assertEquals("C:USD:20000.0000000000:0.0000000000:0.0000000000|P:86ab36e1-6a7e-4723-8571-6b5adb674df0:800.0000000000:100.0000000000:USD",
				PortfolioService.canonicalTask5Snapshot(request));
	}

	@Test
	void replacesCallerSourceReferenceWithTheServerGovernedCompanionPath() {
		var request=new CreateSnapshotRequest(Instant.parse("2026-07-29T20:10:00Z"),SnapshotSource.MANUAL,
				"caller-controlled",SnapshotCompleteness.COMPLETE,List.of(),List.of());
		var governed=PortfolioService.governedSnapshotRequest(request);
		assertEquals("TASK5:MANUAL",governed.sourceReference());
	}
}
