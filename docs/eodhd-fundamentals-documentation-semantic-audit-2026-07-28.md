# EODHD Fundamentals Documentation Semantic Audit

Date: 2026-07-28
Scope: official public documentation only
Financial data API requests: zero

## Conclusion

The public documentation does not authorize the provider semantic contract
required by frozen Objective Rating v1.

EODHD documents `shortLongTermDebtTotal` as a total-debt field, and documents
financial-statement `ebitda` as `ebit + depreciationAndAmortization`. Those
facts are useful but not sufficient:

- `shortLongTermDebtTotal` composition may vary by company, and the public
  material does not give exhaustive inclusion/exclusion, consolidation,
  instant-period, or immutable-revision semantics.
- `ebitda` is documented as provider-calculated, but quarterly records are not
  defined as discrete quarter, YTD, or TTM. Therefore the frozen TTM EBITDA
  input cannot be constructed safely.
- The official OpenAPI specification documents the Fundamentals endpoint and
  broad Financials collections, but not field-level financial-statement
  schemas.
- EODHD has publicly described recalculating historical fundamentals and
  recommending a full redownload. No immutable field-revision stream is
  documented.

Current QC remains blocked by total-debt equivalence and EBITDA duration
semantics. Current UQ remains additionally blocked by monthly PIT FCF-yield
history. Observed 223/223 field presence is not semantic proof.

## Decisions

| Question | Decision |
|---|---|
| Field is named/described as total debt | `PROVEN` |
| Exact debt inclusions and exclusions | `NOT_DOCUMENTED` |
| Consolidated debt scope | `NOT_DOCUMENTED` |
| Balance-sheet instant semantics | `NOT_DOCUMENTED` |
| Immutable debt revision policy | `CONTRADICTED` |
| Equivalence to frozen normalized total debt | `NOT_DOCUMENTED` |
| EBITDA formula | `PROVEN` |
| EBITDA is provider-calculated | `PROVEN` |
| Quarterly EBITDA duration semantics | `NOT_DOCUMENTED` |
| Annual EBITDA complete-fiscal-year semantics | `NOT_DOCUMENTED` |
| Immutable EBITDA revision policy | `CONTRADICTED` |
| Frozen TTM EBITDA construction | `NOT_DOCUMENTED` |
| Official glossary/OpenAPI availability | `PROVEN`, with field-level limitations |

No provider semantic contract was promoted. The remaining action is for the
user to send the separately prepared support inquiry or choose a different
authoritative source.

## Official sources

- [Fundamentals glossary: common stock](https://eodhd.com/financial-academy/financial-faq/fundamentals-glossary-common-stock)
- [Debt fields explained](https://eodhd.com/financial-academy/financial-faq/debt-fields-explained)
- [Fundamentals API documentation](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds)
- [Official Fundamentals OpenAPI path](https://raw.githubusercontent.com/EodHistoricalData/EODHD-openapi/main/paths/fundamentals_ticker.yaml)
- [US fundamentals recalculation notice](https://eodhd.com/financial-apis-blog/big-update-for-usa-fundamentals-new-fields)

The machine-readable audit records access timestamps and SHA-256 hashes for
these public documents.
