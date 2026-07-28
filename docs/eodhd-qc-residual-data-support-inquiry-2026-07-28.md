# EODHD Support Inquiry: Historical Fundamental Period Semantics

## Email Draft

**Subject:** Machine-verifiable period semantics and historical fundamentals for
Objective Rating validation

Hello EODHD Support,

I subscribe to the All-in-One plan and am validating a deterministic US-equity
quality model. I do not need investment advice or calculated scores. I need to
confirm the exact data contract for historical fundamental records.

Could you please answer each question with:

- the endpoint URL template without an API token;
- the exact JSON path and data type;
- the documentation/version effective date;
- whether it is included in All-in-One or requires Extended Fundamentals or
  another add-on; and
- a small JSON example with values redacted if necessary.

1. For records under
   `Financials.Income_Statement.{quarterly,yearly}.*` and
   `Financials.Cash_Flow.{quarterly,yearly}.*`, what do `quarterly` and
   `yearly` mean for duration fields? Is each quarterly value an independent
   three-month period, cumulative year-to-date, or provider TTM? Is yearly
   always an independent twelve-month fiscal year? Does `date` mean period end?
   Is period start, fiscal-quarter identity, or duration type available from
   another field or endpoint?

2. Please apply that answer specifically to `totalRevenue`, `grossProfit`,
   `operatingIncome`, `ebit`, `netIncome`, `incomeTaxExpense`,
   `incomeBeforeTax`, `interestExpense`,
   `totalCashFromOperatingActivities`, `capitalExpenditures`, and the diluted
   weighted-average-share aliases `weightedAverageShsOutDil`,
   `dilutedWeightedAverageShares`, and `weightedAverageSharesDiluted`.

3. Is there an explicit current TTM `interestExpense` field? If not, may the
   most recent four `quarterly.*.interestExpense` records always be summed as
   four non-overlapping 3M gross-interest periods? Please define whether the
   field is gross interest expense and whether financing fees, capitalized
   interest, net interest, or operating interest are included or excluded.

4. Which endpoint and JSON path provide historical TTM diluted EPS—not only
   current `Highlights.DilutedEpsTTM`—and comparable historical TTM values for
   gross profit, revenue, operating income, CFO, capex, and diluted
   weighted-average shares? Are EPS and share histories split-adjusted, and is
   the adjustment method stable across revisions?

5. What exactly does each record's `filing_date` mean: issuer filing time,
   EODHD publication time, or another date? Is a timestamp/time zone available?
   Can historical values be restated or recalculated in place? If yes, is
   `updated_at`, revision ID, vintage ID, or an as-reported history available
   per record?

Please test or illustrate the response for these five US symbols and periods:

- `TTC.US`: current TTM ending `2026-05-01`; historical diluted-EPS TTM
  endpoint between `2023-01-17` and `2023-08-05`; current interest TTM.
- `AVGO.US`: current TTM ending `2026-05-03`; historical diluted-EPS TTM
  endpoint between `2023-01-19` and `2023-08-07`; current net-income and
  interest TTM.
- `HRL.US`: eight explicit 3M operating-income, revenue, CFO, and capex records
  ending `2026-04-30`; comparable margin inputs ending between `2023-01-16`
  and `2023-08-04`; current interest TTM.
- `GPC.US`: the equivalent eight-quarter records ending `2026-06-30`;
  historical TTM endpoint between `2023-03-18` and `2023-10-04`; current
  operating-income/EBIT and interest TTM.
- `ADSK.US`: current raw TTM income-statement, CFO, capex, and diluted-share
  inputs ending `2026-04-30`; historical margin endpoint between `2023-01-16`
  and `2023-08-04`.

Please do not include an API key in the response.

Thank you.

## Internal Decision

The v1.7 reassembly is accepted as method-conformant. Its six QC-ready
securities remain below the frozen minimum of 20. The residual evidence plan
correctly stops the proposed Yahoo TTC request because its best case is only
seven ready securities.

EODHD already exposes most required value fields. The primary blocker is not
the arithmetic; it is the missing or undocumented duration, historical TTM,
availability, and revision contract. Historical diluted EPS TTM appears to be
a coverage gap in the reviewed payload, while period-start and revision
metadata may be either undocumented or available only through another product.

If support cannot provide machine-verifiable answers, the next evaluation must
target capabilities rather than a brand: explicit period start/end and
3M/YTD/12M/TTM type, eight-quarter raw histories, comparable historical TTM
EPS and weighted diluted shares, split/unit/currency metadata, per-record
availability and revision lineage, durable identifiers, and licensed local
snapshot retention.

No network request, score, supplement, or Forward Decision-Quality Validation
run was performed.
