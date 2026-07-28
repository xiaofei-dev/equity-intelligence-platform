# Draft: EODHD Fundamentals Field-Semantics Inquiry

Status: draft only. Do not send without user approval.

Subject: Clarification requested for `shortLongTermDebtTotal` and financial-statement `ebitda`

Hello EODHD Support,

I use the Fundamentals API for personal, point-in-time equity research. Could
you please confirm the following for the current Fundamentals API, ideally
identifying the API/schema version and the effective date of each definition?

## `Financials.Balance_Sheet.{quarterly,yearly}.*.shortLongTermDebtTotal`

1. Is this field the complete consolidated interest-bearing debt balance as of
   the record's `date`?
2. Does it include, separately or collectively:
   - short-term borrowings;
   - current maturities of long-term debt;
   - non-current long-term debt;
   - finance/capital lease liabilities;
   - operating lease liabilities;
   - convertible debt;
   - notes payable, commercial paper, bank overdrafts, and other borrowings?
3. Which liabilities are explicitly excluded?
4. Can components overlap, or is the total guaranteed to be non-overlapping?
5. Is the unit always the statement's `currency_symbol`, without scaling?
6. Is the value consolidated, parent-only, or dependent on the issuer filing?
7. Can a previously published historical value be revised? If yes, are the
   original value, revision timestamp, effective date, and reason available?

## `Financials.Income_Statement.{quarterly,yearly}.*.ebitda`

1. Is the field reported by the issuer or calculated by EODHD?
2. If calculated, is the exact formula always `ebit +
   depreciationAndAmortization`? How is `ebit` derived when it is not reported?
3. Is each `quarterly` value a discrete three-month quarter, year-to-date
   duration, trailing twelve months, or dependent on the issuer?
4. Is each `yearly` value the complete fiscal-year duration?
5. Is the unit always the statement's `currency_symbol`, without scaling?
6. Does `filing_date` represent the first public filing date, the latest
   restatement date, or another date?
7. Can a previously published historical EBITDA value be revised? If yes, are
   immutable revision identifiers and publication timestamps available?

## `Financials.Income_Statement.{quarterly,yearly}.*.interestExpense`

1. Is this field the complete gross cost of borrowed funds for the reporting
   entity, before any netting against interest income?
2. Does it include or exclude:
   - interest capitalized into inventory, property, or another asset;
   - amortization of debt discounts, premiums, and issuance costs;
   - commitment, facility, guarantee, and other financing fees;
   - lease interest;
   - operating-interest components;
   - related-party interest; and
   - interest reported outside non-operating expense?
3. Can the field ever contain net interest expense, or be reduced by interest
   income?
4. Is every `quarterly` record a discrete fiscal quarter, a fiscal-year-to-date
   duration, trailing twelve months, or dependent on the issuer?
5. Is every `yearly` record a complete fiscal-year duration? If so, what is the
   authoritative period start?
6. Is there a separate documented TTM interest-expense field in Highlights,
   Valuation, Technicals, or another Fundamentals section?
7. Is `currency_symbol` always the unscaled currency and unit for
   `interestExpense`?
8. Does `filing_date` represent the first public filing date, the most recent
   restatement date, or another provider date? Is the SEC acceptance timestamp
   available?
9. Can a historical `interestExpense` value be revised or recalculated? If yes,
   are the prior value, revision identifier, first-publication timestamp,
   effective date, and revision reason available?
10. Which Fundamentals API/schema version and effective date govern these
    answers?

## Documentation and versioning

1. Is there a versioned field-level data dictionary or JSON Schema that defines
   these semantics beyond the public glossary and endpoint OpenAPI schema?
2. Which Fundamentals API version do these answers apply to?
3. What is the effective date of the definitions?
4. How are backward-incompatible semantic changes announced?

A yes/no answer followed by the exact definition for each item would be very
helpful. Please do not include account credentials or API keys in the reply.

Thank you.
