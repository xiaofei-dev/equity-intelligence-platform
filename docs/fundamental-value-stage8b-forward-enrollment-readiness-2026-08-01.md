# Fundamental Value Stage 8B Forward Enrollment Readiness

Stage 8B adds an append-only PostgreSQL and Python readiness contract for a
narrow `COMPANY_QUALITY` predictor. It does not enroll a complete Fundamental
Value assessment and does not change the model evidence label. The only allowed
label is `NOT_VALIDATED`; the evidence stratum is
`CURRENT_REVISION_APPROXIMATION` and the population limitation is
`CURRENT_SURVIVOR_DEVELOPMENT_POPULATION`.

## Audit and migration decision

V18-V20 encode an incompatible Forward DQV population, benchmark design, and
5/20/60/126/252-session schedule. V22 has reusable identity and calendar
foundations but no cohort, predictor, rank, or maturity enrollment. V23 requires
a complete Fundamental Value assessment. Reusing any of those tables would
change their meaning or require fabricated dimensions. V24 therefore owns a
separate company-quality-only enrollment header, complete terminal population,
reason rows, and empty 252/504/756-session maturity schedule.

V24 is append-only. Deferred validation requires the declared member, usable,
reason, and horizon counts; evidence chronology must be no later than the sealed
evidence cutoff. Valid ranks are contiguous and the Python boundary recomputes
rank 1 as highest score with durable security identity ascending as the tie
breaker. Non-usable rows remain non-numeric and carry explicit reasons. The
maturity table can contain only `AWAITING_NATURAL_MATURITY` with zero outcomes.
No outcome table or outcome insertion path is introduced.

The header has no singular calendar/session or entry fallback. Its sealed
decision-session set contains exactly one completed V22 session for each member
listing MIC (`XNYS` and `XNAS`), on one common session date, with exact calendar,
session, completion, recording, and hash lineage. Its separate planned-entry set
contains exactly one `SCHEDULED_NOT_COMPLETED` row per MIC from an authoritative
schedule contract; it never pretends that a future entry is completed. Members
bind their listing MIC to the corresponding decision-session child, and usable
V22 selection requests must bind the same MIC-specific completed session.

The enrollment header is required to bind the frozen C5 191-member population, hash
`B29306CE3B1A047C074B68FDA07149FFF72F7B2ECD2BC0D78AAD7B42692656C7`.
A real insert additionally requires a complete durable V22 identity projection;
the constant header hash alone does not prove that projection. A rankable cohort
requires at least 100 usable members. A one-to-one seal binds
the member, rank/group, reason, ordered source-parent evidence, and maturity
sets. The database independently recomputes the structural producer-output,
row, schedule,
enrollment, and seal hashes and rejects children added after sealing. Generic
analytics writers cannot insert V24 rows.

V24 does not extend or reinterpret V22 selector field codes. The frozen parent-role
table maps the producer equity role to legal V22 `TOTAL_EQUITY`; `INCOME_TAX` and
`PRETAX_INCOME` use a separate V24-owned provider-normalized parent route bound to
an immutable normalized-parent record plus the raw manifest, provider/schema/source
identity, revision, period, chronology, unit, currency, normalized hash, and numeric
value. A separate normalized-parent producer role has insert-only access, while the
enrollment writer remains read-only and neither role can mutate existing rows. The remaining roles require
legal V22 selected evidence. The single frozen role table totals 63 ordered parents
per usable member, and Python and PostgreSQL tests calculate and compare that total.
The provider-normalized parent does not duplicate a free-standing listing MIC:
its durable company/instrument/share-class/listing tuple determines listing
ownership, while the enrollment member separately binds that listing to the
validated MIC-specific decision session. PostgreSQL rejects attempts to write a
redundant normalized-parent MIC claim.
Because the deferred validator resolves provider-normalized lineage through the
V22 raw manifest, the semantic enrollment writer receives the narrow matching
`SELECT` privilege. A role-switched integration commits the complete 191-member
enrollment as that writer, while explicit ACL negatives prove it still cannot
insert, update, delete, or truncate raw manifests, normalized parents, or
parent-role metadata. Generic analytics writers remain denied.

The database replays the unchanged five-input company-quality producer and Stage 2
score from those ordered parents, including the tax, NOPAT, invested-capital,
margin, FCF, and stability formulas and half-even score rounding. A real usable
score nevertheless requires an accepted current provider-normalization envelope;
synthetic `TEST_ONLY` fixtures demonstrate runtime enforcement only and cannot
authorize enrollment.

The replay uses an internal Decimal context with precision 28 and half-even rounding,
canonicalizes ordinary finite decimals without exponent, trailing-zero, or signed-zero
drift, and hashes whole-second UTC timestamps independently of the database session
time zone. Every economic/calendar date derived from a timestamp uses its explicit UTC
date, so equivalent offset representations and opposite-calendar-date database sessions
admit identically. SQL and Python enforce the same capex, ROIC, operating-margin, and FCF-margin
domains. PostgreSQL uses precision-preserving division and square-root helpers before
the producer context is applied; the unchanged Stage 2 factor scorer then consumes the
produced operands under its own precision-50 context. Exact boundary vectors prove the
same half-even score in both runtimes. Every CAPEX parent must be nonnegative, so a
negative quarter cannot be hidden by a positive four-quarter sum.

The producer replay also requires one exact common latest-four period-end set across
revenue, operating income, operating cash flow, CAPEX, income tax, and pretax income.
The aligned flow chain determines the inferred start and final end boundaries. Equity,
debt, and cash are selected independently as the latest observation at or before each
boundary within 120 days; post-boundary points and missing boundary candidates fail
closed. All hash-bound dates and timestamps must be finite, period starts cannot follow
period ends, and variable hash atoms use a delimiter-free admitted grammar so distinct
source identities cannot serialize to the same hash input. Every referenced digest
also uses the exact lowercase `sha256:<64 hexadecimal characters>` grammar before
serialization; prefix-only or colon-bearing digest strings are rejected. Python
normalizes aware timestamps to UTC before enforcing whole-second precision, preventing
fractional-offset timezone values from being truncated into another instant.
PostgreSQL renders every hash-bound date through a finite ISO `YYYY-MM-DD`
canonicalizer, independent of the connection `DateStyle`.
The typed wire range is explicitly limited to AD years 0001 through 9999.
PostgreSQL rejects BC and year-10000 dates or UTC instants before hashing, so
distinct BC/AD values cannot collide and every admitted value remains readable
by Python/psycopg. The header also makes the existing chronology algebra
explicit: revision is exactly 1 without supersession, and evidence cutoff equals
decision cutoff. Planned entry dates must equal both scheduled-open and
scheduled-close UTC dates. Hash atoms are trimmed, nonblank, and delimiter-free,
using the exact shared ASCII whitespace set space, tab, LF, CR, form feed, and
vertical tab; Unicode-default trimming is not used. Every Python string mapped
to a bounded V24 `VARCHAR` or `CHAR` is checked against the matching PostgreSQL
character limit before hashing. NUL is explicitly outside the admitted Python
atom domain because PostgreSQL text cannot represent it; no broader arbitrary
Unicode restriction is imposed. `sourceRevision` is likewise constrained before
hashing to the positive PostgreSQL signed-integer range 1 through 2,147,483,647.
Terminal reason codes are unique per member.
All exposed integer fields require exact Python `int` values, never booleans or
floats, and remain within signed PostgreSQL `INTEGER`; `earlyClose` requires an
exact boolean. Every persisted or hashed Decimal is finite and constrained to
PostgreSQL unconstrained-`NUMERIC` representability: at most 131,072 integer
digits and 16,383 fractional digits after canonical plain normalization.
This includes predictor scores and every source parent, even older inputs not
used by the latest-four score window.
Every source-parent value is additionally bounded to an absolute value of
`1e100`. This economically generous envelope leaves substantial headroom for
equity fundamentals while ensuring that all eight-row sums, differences, and
squared stability intermediates remain representable under both the sealed
Python Decimal context and PostgreSQL `NUMERIC`; it does not change a formula.
The canonical fractional scale of every source parent is at most 100 digits.
Zero and magnitudes down to `1e-100` are admitted; smaller nonzero canonical
values are rejected before replay. Together with the `1e100` upper bound, this
keeps precision-28 rounding quantums and every producer intermediate within the
shared Python/PostgreSQL numeric domain, including near-cancellation cases.
Both magnitude admission and best-first ranking use context-free Decimal
operations, so hostile caller precision cannot round an out-of-range value into
the envelope or turn distinct scores into an identity tie.
Every UUID-bearing Python wire field requires an exact `UUID` instance before
serialization, preventing PostgreSQL lowercase canonicalization from changing
the bytes that were hashed.
Every one of the eight bound CAPEX parents must be nonnegative, including the
four older stability/source-history rows outside the latest-four score window.
Completed-session evidence must also satisfy `completedAt <= recordedAt`.
Within one enrollment, members have distinct ordinal, security, listing, and
ticker-assignment identities. Decision sessions have distinct MIC, completed
session, calendar-contract tuple, and session-content hash. V22-selected parent
links have distinct request, result, and canonical-evidence identities across
the enrollment. Provider-normalized parents separately have distinct normalized
parent IDs, normalized-record hashes, and raw-manifest/field/period tuples.
Company, instrument, and share-class reuse remains legal, as do the explicitly
permitted raw-manifest and lineage/hash reuse cases and all reuse across separate
enrollments.

Every insert into the seven enrollment child tables that contributes to a
cardinality or seal hash queues deferred aggregate validation. The initial graph
remains efficient because its child rows share a server-stamped, non-wrapping
`creator_xid8` with the seal transaction and the enrollment-header trigger runs
the complete replay once. A child inserted by any later transaction has a
different full transaction identity and must recompute the exact aggregate at
commit. The semantic writer cannot set or update this concurrency provenance;
an unconditional `BEFORE INSERT` trigger overwrites caller input. Two-connection
tests pause an extra reason and extra evidence after their production late-child
check, commit T1, and prove T2's deferred commit fails without changing sealed
readback, hashes, or cardinalities. A caller-supplied custom GUC cannot bypass
the validator.

The disposable PostgreSQL 17 typed integration seeds 191 durable test identities
with the frozen 122 `XNYS` / 69 `XNAS` distribution, exactly two MIC-specific
completed decision sessions, and exactly two `SCHEDULED_NOT_COMPLETED` planned
entries. It uses 110 usable members with 6,930 ordered source parents and 81
explicit `MISSING` members,
legal V22 policies/selections for supported roles, and the separate V24 provider
parent route. It persists through `CompanyQualityForwardRepositoryV1`, commits the
deferred seal, reads back the exact aggregate, proves three zero-outcome maturities,
and exercises idempotency, racing replay, conflicts, graph drift, identity/session/
cutoff rejection, append-only controls, and generic/semantic writer boundaries.

The stable engineering snapshot passed 33 focused Python contract tests, 23 typed
PostgreSQL 17 integration tests on a freshly recreated V1-to-V24 database, and
the 400-test Fundamental Value regression selection. The full migration matrix passed,
including V23-to-V24 preservation and the unchanged V18-to-V19 refusal case.
Ruff and `git diff --check` also passed. These results establish V24 engineering
readiness only; they do not cure the real-enrollment evidence and chronology
blockers below.

## Enrollment result

The separate outcome-blind real-enrollment audit concluded
`BLOCKED_BY_CURRENT_EVIDENCE_AND_CHRONOLOGY`. The sealed offline SPY calendar
ends on 2026-07-28 and cannot prove the required latest completed XNYS session
of 2026-07-31. The 216 current-decision input artifacts share the older cutoff,
but none provides a contractual top-level ingestion timestamp or durable
security identity. Filesystem modification times and ticker-only identifiers
are not accepted evidence. Historical C9 predictors are not relabelled as a
present decision, and the enrollment is not backdated.

The C5 identity-set hash is available. A final outcome-blind audit found that
191/191 identities are structurally projectable from unique checksum-valid ISIN
and CUSIP candidates, but 54 US ISIN national components conflict with the
provider CUSIP. Those identities are terminal `INVALID` and quarantined pending
a second authority, leaving at most 137 clean candidates. `GOOG`/`GOOGL` and
`FOX`/`FOXA` share company/instrument ownership but require distinct share-class
and listing identities; the legacy `MSFT` public identifier must be adopted and
explicitly marked. This is not yet the accepted V22 UUID tuple manifest required
for enrollment. Existing receipts are July 27/28 captures; assigning a new
ingestion timestamp would not make their evidence current.

Local calendar code and tzdata prove only the scheduled July 31 open/close and
August 3 next open. They are not completed-session authority, so V24 must not
insert a July 31 `COMPLETED` session from wall-clock or schedule inference. The
same offline snapshot cannot prove the immediate next eligible entry session
from hash-preserved completion evidence, and it contains no accepted current
producer envelope that can replay the provider-native score from the selected
parents. These remain explicit real-enrollment blockers rather than fields filled
with assertions.

The Git-safe readiness artifact records the exact blockers and a
`networkAuthorized=false` future preflight. It deliberately contains zero
executable requests. A later request matrix requires a newly sealed current
calendar range, durable population and transport aliases, exact endpoint paths,
weights, leases, journals, checkpoints, and preserved quota reserve before
separate approval.

No provider call, outcome access, database enrollment write, migration of a
shared database, portfolio decision, or brokerage action occurred.
