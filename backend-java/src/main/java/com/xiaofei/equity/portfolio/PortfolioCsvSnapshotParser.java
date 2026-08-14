package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.PortfolioContracts.*;

import java.math.BigDecimal;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

import com.xiaofei.equity.usercontext.UserContextException;

import org.springframework.stereotype.Component;

@Component
public final class PortfolioCsvSnapshotParser {

	public static final String VERSION = "PORTFOLIO-SNAPSHOT-CSV-v1.0.0";
	public static final int MAX_BYTES = 1_048_576;
	public static final int MAX_DATA_ROWS = 5_000;
	private static final String HEADER = "record_type,security_public_id,quantity,average_cost,currency,settled_amount,unsettled_amount,restricted_amount";
	private static final Pattern UUID_TEXT = Pattern.compile("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");
	private static final Pattern CURRENCY = Pattern.compile("[A-Z]{3}");
	private static final Pattern DECIMAL = Pattern.compile("-?(0|[1-9][0-9]*)(\\.[0-9]{1,10})?");

	public ParsedCsv parse(byte[] bytes) {
		if (bytes == null || bytes.length == 0) throw invalid("CSV_FILE_EMPTY", "The CSV file must not be empty.");
		if (bytes.length > MAX_BYTES) throw invalid("CSV_FILE_TOO_LARGE", "The CSV file exceeds the 1 MiB limit.");
		String text = decode(bytes);
		if (text.startsWith("\ufeff")) throw invalid("CSV_BOM_NOT_ALLOWED", "The CSV file must be UTF-8 without a byte-order mark.");
		String normalized = text.replace("\r\n", "\n");
		if (normalized.indexOf('\r') >= 0) throw invalid("CSV_LINE_ENDING_INVALID", "CSV lines must use LF or CRLF endings.");
		String[] lines = normalized.split("\n", -1);
		int last = lines.length;
		if (last > 0 && lines[last - 1].isEmpty()) last--;
		if (last == 0 || !HEADER.equals(lines[0])) throw invalid("CSV_HEADER_INVALID", "The CSV header does not match the portfolio snapshot v1 schema.");
		if (last - 1 > MAX_DATA_ROWS) throw invalid("CSV_ROW_LIMIT_EXCEEDED", "The CSV file exceeds the 5,000-row limit.");

		List<CashBalanceInput> cash = new ArrayList<>();
		List<PositionInput> positions = new ArrayList<>();
		List<CsvDiagnostic> diagnostics = new ArrayList<>();
		Set<String> currencies = new HashSet<>();
		Set<UUID> securities = new HashSet<>();
		for (int index = 1; index < last; index++) {
			int row = index + 1;
			List<String> fields;
			try { fields = fields(lines[index]); }
			catch (IllegalArgumentException error) {
				diagnostics.add(diagnostic(row, "row", "CSV_ROW_SYNTAX_INVALID", "The row has invalid CSV quoting."));
				continue;
			}
			if (fields.size() != 8) {
				diagnostics.add(diagnostic(row, "row", "CSV_COLUMN_COUNT_INVALID", "The row must contain exactly eight columns."));
				continue;
			}
			if (fields.stream().anyMatch(value -> !value.equals(value.strip()))) {
				diagnostics.add(diagnostic(row, "row", "CSV_WHITESPACE_NOT_CANONICAL", "CSV values must not contain surrounding whitespace."));
				continue;
			}
			if ("POSITION".equals(fields.get(0))) parsePosition(row, fields, positions, securities, diagnostics);
			else if ("CASH".equals(fields.get(0))) parseCash(row, fields, cash, currencies, diagnostics);
			else diagnostics.add(diagnostic(row, "record_type", "CSV_RECORD_TYPE_INVALID", "record_type must be POSITION or CASH."));
		}
		return new ParsedCsv(
				sha256(bytes), bytes.length, Math.max(0, last - 1),
				List.copyOf(cash), List.copyOf(positions), List.copyOf(diagnostics));
	}

	private static void parsePosition(int row, List<String> fields, List<PositionInput> positions,
			Set<UUID> securities, List<CsvDiagnostic> diagnostics) {
		if (!fields.subList(5, 8).stream().allMatch(String::isEmpty)) {
			diagnostics.add(diagnostic(row, "cash", "CSV_POSITION_CASH_FIELDS_PRESENT", "POSITION rows must leave all cash columns empty.")); return;
		}
		UUID security = uuid(fields.get(1));
		BigDecimal quantity = decimal(fields.get(2));
		BigDecimal averageCost = decimal(fields.get(3));
		String currency = fields.get(4);
		if (security == null) diagnostics.add(diagnostic(row, "security_public_id", "CSV_SECURITY_ID_INVALID", "security_public_id must be a canonical lowercase UUID."));
		if (quantity == null || quantity.signum() == 0) diagnostics.add(diagnostic(row, "quantity", "CSV_QUANTITY_INVALID", "quantity must be a non-zero canonical decimal."));
		if (averageCost == null || averageCost.signum() < 0) diagnostics.add(diagnostic(row, "average_cost", "CSV_AVERAGE_COST_INVALID", "average_cost must be a non-negative canonical decimal."));
		if (!CURRENCY.matcher(currency).matches()) diagnostics.add(diagnostic(row, "currency", "CSV_CURRENCY_INVALID", "currency must contain exactly three uppercase letters."));
		if (security != null && !securities.add(security)) diagnostics.add(diagnostic(row, "security_public_id", "CSV_DUPLICATE_SECURITY", "Each security may appear only once."));
		if (security != null && quantity != null && quantity.signum() != 0 && averageCost != null
				&& averageCost.signum() >= 0 && CURRENCY.matcher(currency).matches() && securities.contains(security)
				&& diagnostics.stream().noneMatch(item -> item.row() == row)) {
			positions.add(new PositionInput(security, quantity, averageCost, currency));
		}
	}

	private static void parseCash(int row, List<String> fields, List<CashBalanceInput> cash,
			Set<String> currencies, List<CsvDiagnostic> diagnostics) {
		if (!fields.subList(1, 4).stream().allMatch(String::isEmpty)) {
			diagnostics.add(diagnostic(row, "position", "CSV_CASH_POSITION_FIELDS_PRESENT", "CASH rows must leave all position columns empty.")); return;
		}
		String currency = fields.get(4);
		BigDecimal settled = decimal(fields.get(5));
		BigDecimal unsettled = decimal(fields.get(6));
		BigDecimal restricted = decimal(fields.get(7));
		if (!CURRENCY.matcher(currency).matches()) diagnostics.add(diagnostic(row, "currency", "CSV_CURRENCY_INVALID", "currency must contain exactly three uppercase letters."));
		if (settled == null) diagnostics.add(diagnostic(row, "settled_amount", "CSV_SETTLED_AMOUNT_INVALID", "settled_amount must be a canonical decimal."));
		if (unsettled == null) diagnostics.add(diagnostic(row, "unsettled_amount", "CSV_UNSETTLED_AMOUNT_INVALID", "unsettled_amount must be a canonical decimal."));
		if (restricted == null || restricted.signum() < 0) diagnostics.add(diagnostic(row, "restricted_amount", "CSV_RESTRICTED_AMOUNT_INVALID", "restricted_amount must be a non-negative canonical decimal."));
		if (CURRENCY.matcher(currency).matches() && !currencies.add(currency)) diagnostics.add(diagnostic(row, "currency", "CSV_DUPLICATE_CURRENCY", "Each cash currency may appear only once."));
		if (settled != null && unsettled != null && restricted != null && restricted.signum() >= 0
				&& CURRENCY.matcher(currency).matches() && diagnostics.stream().noneMatch(item -> item.row() == row)) {
			cash.add(new CashBalanceInput(currency, settled, unsettled, restricted));
		}
	}

	private static List<String> fields(String line) {
		List<String> result = new ArrayList<>(); StringBuilder field = new StringBuilder();
		boolean quoted = false; boolean afterQuote = false;
		for (int index = 0; index < line.length(); index++) {
			char current = line.charAt(index);
			if (quoted) {
				if (current == '"' && index + 1 < line.length() && line.charAt(index + 1) == '"') { field.append('"'); index++; }
				else if (current == '"') { quoted = false; afterQuote = true; }
				else field.append(current);
			} else if (afterQuote) {
				if (current != ',') throw new IllegalArgumentException();
				result.add(field.toString()); field.setLength(0); afterQuote = false;
			} else if (current == ',' ) { result.add(field.toString()); field.setLength(0); }
			else if (current == '"' && field.isEmpty()) quoted = true;
			else if (current == '"') throw new IllegalArgumentException();
			else field.append(current);
		}
		if (quoted) throw new IllegalArgumentException(); result.add(field.toString()); return result;
	}

	private static String decode(byte[] bytes) {
		try { return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
				.onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString(); }
		catch (CharacterCodingException error) { throw invalid("CSV_UTF8_INVALID", "The CSV file must contain valid UTF-8."); }
	}

	private static BigDecimal decimal(String value) {
		if (!DECIMAL.matcher(value).matches()) return null;
		BigDecimal parsed = new BigDecimal(value); int integerDigits = parsed.precision() - parsed.scale();
		return parsed.precision() <= 24 && integerDigits <= 14 ? parsed : null;
	}
	private static UUID uuid(String value) {
		if (!UUID_TEXT.matcher(value).matches()) return null;
		try { UUID parsed = UUID.fromString(value); return parsed.toString().equals(value) ? parsed : null; }
		catch (IllegalArgumentException error) { return null; }
	}
	private static CsvDiagnostic diagnostic(int row, String field, String code, String message) { return new CsvDiagnostic(row, field, code, message); }
	private static String sha256(byte[] bytes) {
		try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
		catch (NoSuchAlgorithmException error) { throw new IllegalStateException("SHA-256 is unavailable.", error); }
	}
	private static UserContextException invalid(String code, String message) { return new UserContextException(code, message, 422); }

	public record ParsedCsv(String fileSha256, long byteCount, int dataRowCount,
			List<CashBalanceInput> cashBalances, List<PositionInput> positions,
			List<CsvDiagnostic> diagnostics) {
		public boolean valid() { return diagnostics.isEmpty(); }
		public CsvSnapshotPreview preview() { return new CsvSnapshotPreview(VERSION, fileSha256, byteCount,
				dataRowCount, cashBalances.size(), positions.size(), valid(), diagnostics); }
		public String sourceReference() { return "parser=" + VERSION + ";sha256=" + fileSha256; }
	}
}
