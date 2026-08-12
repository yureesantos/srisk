# 7. Betslip facts are mutable, so ingestion is a merge and never an append

Date: 2026-08-12

## Status

Accepted. Extends ADR-0003, which established betslip identity for a static
export; this record establishes what that identity has to survive once the
export becomes a stream.

## Context

The exports are consolidated billing reports. Both files carry `GGR` and
`Net Revenue` already filled on every row, which reads as settled, final data —
the kind of input a batch pipeline can hash and be done with.

They are not final. They are consolidated *as of the moment the report ran*.

The two files in `data/raw/` were generated **95 seconds apart** (`05:17:29` and
`05:19:04`). They are near-disjoint in scope — 192 shared keys out of 78,937 and
34,081 unique rows — but they overlap in time, and where they overlap they
disagree.

Restricting the comparison to keys that are **unique inside each file** removes
the ADR-0003 collision ambiguity, leaving 42 unambiguous shared rows:

| Column | Rows differing across the two exports |
|---|---|
| `TURNOVER` | **0 of 42** |
| `GGR` | **14 of 42** |
| `Net Revenue` | **14 of 42** |

The direction of the change is uniform. In the earlier export those 14 rows
carry a negative `GGR` — the customer had won. In the later export, **14 of 14**
carry `GGR` exactly equal to `TURNOVER`: the house kept the whole stake.

A worked example — Uid `1426344`, fixture `36966473`, 1-X-2 / 2 goals Up, price
1.52, stake 0.35:

| Export | TURNOVER | GGR |
|---|---|---|
| `051729` | 0.35 | **-1.58** |
| `051904` | 0.35 | **0.35** |

That is a settlement being reversed — a void, a resettlement, or a correction —
landing inside a 95-second gap between two routine report runs.

This splits the export's columns into two categories with different physics:

- **`TURNOVER` is immutable.** It is known when the bet is placed and nothing
  later changes it. Measured: zero disagreements.
- **`GGR` and `Net Revenue` are retroactively mutable.** They are not known at
  placement, and once known they can still change.

The batch pipeline never had to care. It read a frozen file, computed once, and
hashed the result; the immutability it depended on was a property of the *file*,
not of the data. At 20M rows that file stops existing — the consolidation the
partner performed before sending is precisely the step that no longer fits in an
export, and it becomes ours. The guarantee has to be rebuilt rather than
inherited.

Three ingestion contracts were considered.

**Append-only event log, aggregate by summing.** Correct for `TURNOVER`, wrong
for `GGR` — the reversal above would be added to the earlier value instead of
replacing it, and the error is silent and permanent. Sums that can never be
corrected are not a defensible base for a revenue figure.

**Append-only with corrections as compensating entries.** The reversal arrives as
its own row negating the previous one, and sums stay valid. This is how ledgers
work and it preserves associativity. It requires the source to emit corrections
as deltas — and our source does not. It emits a *new consolidated value*, with
no statement of what it replaces. We would have to reconstruct the delta by
diffing against the current state, which means we need that state keyed and
addressable anyway, which is the third option with extra steps.

**Merge on identity (upsert), last-writer-wins per fact.** Every arriving row is
matched against the stored fact and replaces it when it is newer. Requires
addressable identity and a version to order by; gives idempotency for free,
since re-delivering the same row is a no-op rather than a double-count.

## Decision

**Ingestion is a merge on betslip-leg identity, not an append.**

The identity is ADR-0003's key extended to leg grain — the coarsest key that is
unique per priced selection:

    (Uid, betslip timestamp, BetType, MatchId, Market, Player, Option, Price)

Ordering is by **source snapshot time**, taken from the producer's emission
timestamp (in the exports, the filename's `HHMMSS`). Last writer wins per row,
compared by version and never by arrival order: an out-of-order redelivery of an
older snapshot must not overwrite a newer fact.

**Facts are classified by mutability, and the classification is enforced in the
schema rather than left to convention:**

- `TURNOVER`, price, and every dimension (fixture, market, selection, region,
  currency) are **immutable**. Written once at first sight. A merge that would
  change one is a data-quality event: it is recorded and surfaced, never applied
  silently.
- `GGR` and `Net Revenue` are **mutable**. Overwritten by any newer snapshot,
  with the previous value retained for audit.

Consequently **every aggregate over `TURNOVER` is incrementally maintainable and
every aggregate over `GGR` is not** — a GGR total is only correct if it can be
revised when a settlement is reversed. This is the seam between the speed layer
and the batch layer, and it is derived from measured behaviour of the data
rather than chosen for architectural taste.

Reprocessing the same input twice must produce byte-identical state. This is the
property that makes zero-downtime deploys and replay possible at all, and it is
tested by replaying an export twice and asserting equality — the streaming
equivalent of the invariant checks the batch pipeline already runs.

## Consequences

**Positive**

- Duplicate delivery is a no-op by construction. The exports already contain
  36,832 and 17,253 exact duplicate rows, so at-least-once delivery is the
  regime this data is already in — the merge handles it without a dedup pass.
- The correction case is handled rather than discovered in production. A
  reversal like Uid `1426344`'s lands as a normal merge.
- Immutable-fact violations become a reportable population, in the same spirit as
  ADR-0003's `had_key_collision`: if a partner ever restates a stake, we surface
  it instead of absorbing it.
- The mutability split gives the speed/batch seam an empirical basis. "GGR is
  batch" is now a measured claim with a row-level example, not a preference.
- Replay-to-identical-state gives back, in continuous form, the reproducibility
  the artifact hash gave in batch form.

**Negative**

- A merge costs more than an append: it needs an index lookup per row and takes
  a row lock. At the 8,333 events/s target this is affordable, and it is measured
  rather than assumed — but it is the first thing to break at 10x, and the exit
  is stated in the scaling record rather than pretended away.
- Last-writer-wins silently loses a genuine concurrent conflict. With a single
  consolidating source this is not reachable; with several partners restating the
  same betslip it would be, and the version field is what a future record would
  build a real resolution on.
- Snapshot time comes from the producer, so a partner with a wrong clock can
  pin a stale value. Detectable (version moving backwards) but not correctable
  without a trusted clock.
- Retaining previous values for audit grows storage beyond the fact table. Bounded
  by a retention window, which is a policy choice this record does not fix.
- The identity key still inherits ADR-0003's residual risk: it trusts `BetType`,
  and two genuinely distinct `COMBINED` bets colliding on Uid and second remain
  indistinguishable. The stream does not make this worse, and does not fix it.
