# AI Analysis

## Role of AI

AI accelerates qualitative research and challenges quantitative conclusions. It does not independently predict stock prices, make final trade decisions, or control portfolio allocation.

## Supported Research Areas

AI may assist with:

- Management and governance review
- Earnings-call guidance changes
- Competitive landscape analysis
- Regulatory and litigation risks
- Customer or supplier concentration
- Business-model and margin risks
- One-time events
- Market narrative and sentiment risks
- Counterarguments to an investment thesis

## Evidence Pipeline

```text
Primary and trusted source documents
              |
              v
Document metadata and extraction
              |
              v
Structured factual evidence
              |
              v
LLM analysis
              |
              v
Schema validation and citation checks
              |
              v
Stored research report
```

Preferred sources include regulatory filings, company investor-relations materials, earnings transcripts from licensed providers, and reputable news sources.

## Output Requirements

Every AI report should include:

- Company and analysis date
- Source list
- Evidence citations
- Observed facts
- Inferences
- Positive factors
- Risk factors
- Contradictory evidence
- Missing information
- Confidence or uncertainty indicators
- Model identifier
- Prompt version
- Input data timestamp

## Structured Output

AI results must follow a validated schema. A conceptual result includes:

```json
{
  "symbol": "AAPL",
  "asOfDate": "2026-07-25",
  "positiveFactors": [],
  "riskFactors": [],
  "contradictions": [],
  "openQuestions": [],
  "citations": [],
  "confidence": "medium",
  "modelVersion": "model-id",
  "promptVersion": "research-v1"
}
```

The final implementation may evolve, but schema validation is mandatory.

## Failure Policy

The AI analysis must fail safely when:

- Required sources are unavailable
- Sources are stale
- Citations cannot be verified
- The response does not match the schema
- Material claims conflict
- The model returns unsupported assertions

A failed AI review must not silently become a neutral or positive score.

## Cost Control

AI analysis should run only after deterministic screening has reduced the universe. Reports should be cached by:

- Company
- Source snapshot
- Analysis date
- Prompt version
- Model version

The system should avoid repeating identical analyses.

## Security

- Treat retrieved documents as untrusted input.
- Protect against prompt injection in external content.
- Do not place API keys or private account data in prompts.
- Log metadata without unnecessarily retaining sensitive prompt content.
- Apply access controls to proprietary source documents.

## Evaluation

AI quality should be evaluated independently from investment performance:

- Citation accuracy
- Factual accuracy
- Schema validity
- Coverage of material risks
- Consistency
- Unsupported-claim rate
- Cost and latency

