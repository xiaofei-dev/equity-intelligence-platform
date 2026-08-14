package com.xiaofei.equity.portfolio;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;

import com.xiaofei.equity.usercontext.UserContextException;
import org.junit.jupiter.api.Test;

class PortfolioCsvSnapshotParserTests {

	private static final String HEADER = "record_type,security_public_id,quantity,average_cost,currency,settled_amount,unsettled_amount,restricted_amount\n";
	private final PortfolioCsvSnapshotParser parser = new PortfolioCsvSnapshotParser();

	@Test
	void parsesCanonicalPositionsAndCashWithoutRetainingRawBytes() {
		var value = parser.parse((HEADER
				+ "POSITION,00000000-0000-4000-8000-000000000101,10.5,125.25,USD,,,\n"
				+ "CASH,,,,USD,5000,10,0\n").getBytes(StandardCharsets.UTF_8));

		assertThat(value.valid()).isTrue();
		assertThat(value.positions()).hasSize(1);
		assertThat(value.cashBalances()).hasSize(1);
		assertThat(value.preview().parserVersion()).isEqualTo(PortfolioCsvSnapshotParser.VERSION);
		assertThat(value.preview().fileSha256()).matches("[0-9a-f]{64}");
		assertThat(value.sourceReference()).doesNotContain("POSITION").contains("sha256=");
	}

	@Test
	void reportsDuplicateAndNoncanonicalRowsWithoutPartialAcceptance() {
		var value = parser.parse((HEADER
				+ "POSITION,00000000-0000-4000-8000-000000000101,1,1,USD,,,\n"
				+ "POSITION,00000000-0000-4000-8000-000000000101,2,1,USD,,,\n"
				+ "POSITION,00000000-0000-4000-8000-00000000010A,3,1,USD,,,\n"
				+ "CASH,,,,USD,1,0,0\n"
				+ "CASH,,,,USD,2,0,0\n").getBytes(StandardCharsets.UTF_8));

		assertThat(value.valid()).isFalse();
		assertThat(value.diagnostics()).extracting(PortfolioContracts.CsvDiagnostic::code)
			.contains("CSV_DUPLICATE_SECURITY", "CSV_SECURITY_ID_INVALID", "CSV_DUPLICATE_CURRENCY");
		assertThat(value.positions()).hasSize(1);
		assertThat(value.cashBalances()).hasSize(1);
	}

	@Test
	void rejectsUnsafeEncodingSizeHeaderAndDecimalDomain() {
		assertThatThrownBy(() -> parser.parse(new byte[] {(byte) 0xc3, (byte) 0x28}))
			.isInstanceOf(UserContextException.class).hasMessageContaining("valid UTF-8");
		assertThatThrownBy(() -> parser.parse(new byte[PortfolioCsvSnapshotParser.MAX_BYTES + 1]))
			.isInstanceOf(UserContextException.class).hasMessageContaining("1 MiB");
		assertThatThrownBy(() -> parser.parse("wrong\n".getBytes(StandardCharsets.UTF_8)))
			.isInstanceOf(UserContextException.class).hasMessageContaining("header");

		var value = parser.parse((HEADER
				+ "POSITION,00000000-0000-4000-8000-000000000101,1e2,1,USD,,,\n"
				+ "CASH,,,,USD,100000000000000,0,0\n").getBytes(StandardCharsets.UTF_8));
		assertThat(value.diagnostics()).extracting(PortfolioContracts.CsvDiagnostic::code)
			.contains("CSV_QUANTITY_INVALID", "CSV_SETTLED_AMOUNT_INVALID");

		var brokenQuote = parser.parse((HEADER
				+ "POSITION,00000000-0000-4000-8000-000000000101,\"1\"2,1,USD,,,\n")
				.getBytes(StandardCharsets.UTF_8));
		assertThat(brokenQuote.diagnostics()).extracting(PortfolioContracts.CsvDiagnostic::code)
			.contains("CSV_ROW_SYNTAX_INVALID");
	}
}
