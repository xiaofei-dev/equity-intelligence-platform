# Product Vision

## Vision

Create an explainable equity intelligence platform that helps an experienced individual investor make more consistent, evidence-based, and risk-aware decisions.

The product combines three complementary capabilities:

1. Quantitative methods process large datasets consistently.
2. AI accelerates research into qualitative and unstructured information.
3. Explicit portfolio rules enforce investment discipline and risk limits.

AI is a supporting research component, not the investment authority.

## User Context

The initial user has approximately ten years of stock-market experience and an existing discretionary process. The platform should first capture, measure, and improve that process rather than replace it with an unvalidated black-box strategy.

The user has three goals:

1. Improve investment outcomes without ignoring risk.
2. Build a production-quality project that supports a software-engineering job search.
3. Preserve a path toward a commercial product if real user demand is validated.

These goals must be evaluated independently. Failure to reach an aspirational return target does not make the engineering project a failure, and a successful backtest does not prove commercial viability.

## Problem Statement

Individual investment research is often:

- Inconsistent across companies and market conditions
- Time-consuming
- Difficult to reproduce
- Vulnerable to emotional decisions
- Based on disconnected quantitative and qualitative information
- Hard to evaluate after the fact because decision inputs are not preserved

The platform addresses these problems by creating a repeatable research and evaluation workflow.

## Value Proposition

The platform will:

- Reduce a broad stock universe to a manageable candidate set
- Explain why each candidate passed or failed
- Collect and summarize source-backed qualitative evidence
- Separate near-term market condition from long-term investment assessment
- Apply explicit portfolio and risk constraints
- Compare new-money-only, constrained-rebalancing, and target-portfolio
  scenarios
- Preserve every decision snapshot for later evaluation
- Compare results with appropriate benchmarks

## Product Principles

### Explainability

Every score and recommendation must be traceable to data, a rule, or a cited source.

### Reproducibility

Given the same data snapshot and strategy version, the system should reproduce the same deterministic result.

### Evidence Before Narrative

AI analysis must begin with retrieved source material. The model must not rely on memory as the primary evidence for current company facts.

### Risk-Aware Evaluation

Return is not sufficient. The system must also evaluate drawdown, volatility, benchmark-relative performance, turnover, and recovery time.

### Human Control

The user reviews decisions and controls execution. Automatic brokerage trading is outside the MVP.

### Honest Claims

The project must not promise a specific annual return or imply that historical simulation guarantees future performance.

## Success Definition

Initial product success means:

- The system runs reliably on a daily schedule.
- Candidate selection and scoring are explainable.
- Data and source timestamps are preserved.
- Quantitative screening and AI evidence review remain separately observable.
- Candidate quality and user portfolio fit remain separate conclusions.
- Simulated results are compared with an appropriate benchmark.
- The user finds the workflow faster and more consistent than the existing manual process.

Achieving a 20% to 30% compound annual return may be an experimental objective, but it is not an assumed product outcome or an MVP acceptance criterion.

## Initial Differentiation Hypothesis

The platform should not compete as another opaque AI stock score. Its proposed
value is a traceable decision workflow that:

1. Discovers candidates through reproducible, cohort-aware screening.
2. Requires supporting and contradictory source evidence.
3. Evaluates each idea against the user's complete portfolio.
4. Compares use of new cash with constrained rebalancing.
5. Preserves the thesis, invalidation conditions, and later outcome.

These are hypotheses until validated through working software and repeated user
use.
