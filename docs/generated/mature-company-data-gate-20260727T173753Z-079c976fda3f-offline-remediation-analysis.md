# Focused Provider-Gate Offline Remediation Analysis

## Evidence scope

- Source run: `20260727T173753Z-079c976fda3f`
- Gate report SHA-256:
  `E2BA494C22EC480712221D8D948468E2E6A383CF2612D014052280FC41521EB7`
- Diagnostic sidecar SHA-256:
  `75F4A97458890E73F3614BB7A57E037A171F29D229606B5F2F87CCA7677223DF`
- No EODHD or SEC request was made during this analysis or remediation.

## Confirmed parser defect

NVDA and EXPO both reported `cash_and_equivalents` as missing even though
their balance-sheet records contained a non-null `cash` field. The same
records also contained a null `cashAndEquivalents` field. Both aliases mapped
to one normalized field, and iteration order allowed the null alias to
overwrite the non-null value.

Parser `eodhd-parser-v1.2.0` resolves aliases using a versioned priority table.
For `cash_and_equivalents`, the priority is `cash`, then
`cashAndEquivalents`. The first non-null value wins. If every observed alias
is null, the normalized value remains null.

## PIT evidence retained without rule changes

EXPO:

| Statement | Type | Provider end | Nearest SEC end | Difference | Form | Accession | Status |
|---|---|---:|---:|---:|---|---|---|
| Balance sheet | Annual | 2024-01-31 | 2023-12-29 | 33 days | 10-K | 0001193125-26-082508 | Outside tolerance |
| Income statement | Annual | 2024-01-31 | 2023-12-29 | 33 days | 10-K | 0001193125-26-082508 | Outside tolerance |

VZ:

| Statement | Type | Provider end | Nearest SEC end | Difference | Form | Accession | Status |
|---|---|---:|---:|---:|---|---|---|
| Balance sheet | Quarterly | 2026-06-30 | 2026-03-31 | 91 days | 10-Q | 0000732712-26-000023 | Not yet available as of evidence |
| Income statement | Quarterly | 2026-06-30 | 2026-03-31 | 91 days | 10-Q | 0000732712-26-000023 | Not yet available as of evidence |
| Cash flow | Quarterly | 2026-06-30 | 2026-03-31 | 91 days | 10-Q | 0000732712-26-000023 | Not yet available as of evidence |

The plus or minus seven-day rule is unchanged. EXPO and VZ remain `PARTIAL`
unless later evidence supplies an eligible matching period or a separately
approved methodology decision changes the rule.

## SEC identity and local PIT errors

LANC has no authoritative CIK retained in the repository evidence. The SEC
client now canonicalizes deterministic share-class punctuation, but this does
not establish a LANC CIK. LANC remains unresolved rather than receiving a
guessed override.

TXN completed ticker mapping, submissions, and company-facts HTTP requests.
Its failure occurred during local PIT processing. Local failures now
distinguish `SEC_NO_COMPLETE_TRADING_SESSION_AFTER_ACCEPTANCE` from
`SEC_COMPANY_FACTS_NORMALIZATION_FAILED`, retaining endpoint category
`local_pit`.

## Retest decision

A later bounded retest should include NVDA and EXPO to verify the alias fix,
and TXN to verify the local error category. VZ does not need another request
until a new eligible filing is expected. LANC must wait for authoritative CIK
evidence.
