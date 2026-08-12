# 9. Freshness is a declared property of each layer, not a global promise

Date: 2026-08-12

## Status

Accepted. Completes the pair started by ADR-0007 (what the data does) and
ADR-0008 (where it lives) by fixing what the reader is promised.

## Context

The batch product makes one guarantee, and it is the reason the dashboard is
worth trusting: **every number on screen came from one immutable artifact, and
that artifact is hashed.** The footer carries `dataset_fingerprint` and
`payload_hash`; the UI computes nothing. If a number looks wrong, it is a
question for the pipeline, never for the browser.

That guarantee rests on something that stops being true under a stream: the input
was frozen. Reproducibility was a property of the *file*, not of the method.

Three questions have to be answered together, because answering any one alone
produces a wrong answer to the others.

### Which metrics can be continuous at all

The pipeline's metrics do not share a single latency floor. They fall into three
classes, and the boundaries are dictated by the data rather than by cost:

**Class 1 — complete at placement.** Turnover, betslip and leg counts, every
dimensional breakdown of stake, region and market mix. Their inputs are known the
moment the bet is placed and never revised (ADR-0007 measured `TURNOVER`
differing on 0 of 42 rows). These are additive and can be as fresh as the
ingest path allows.

**Class 2 — complete at settlement.** GGR, net revenue, margin, and everything
derived from them. Their inputs do not exist at placement, and once they exist
they can still change — measured: 14 of 42 rows had GGR rewritten inside a
95-second window. A running sum of GGR is wrong from the first reversal onward
and never self-corrects.

**Class 3 — complete only over a window, or never in realtime.** Two distinct
reasons, worth separating because only one is about cost:

- *Structurally window-relative.* Gini and the Lorenz curve are statistics of a
  whole population whose members are still changing. This is not an
  associativity problem — a rolling Gini over a fixed window is perfectly
  computable. The problem is semantic: "Gini since the stream began" is a
  quantity that only ever stabilises and is never comparable with itself. Gini
  needs a **declared window** to mean anything.
- *Causally unavailable.* The price reference is, by construction, the last
  pre-kick-off observation on a (fixture, market, selection). Price value and
  therefore every sharp-behaviour output cannot be computed for a leg until its
  fixture kicks off. This is not expensive — it is **unknowable**. No
  architecture removes it: you cannot know whether a customer beat the closing
  line before the line closes. The existing implementation already encodes this
  as a leakage guard; streaming does not relax it.

The sharp test adds a second, independent reason: Benjamini–Hochberg controls
false discovery across a *family* of hypotheses. The family must be fixed before
the correction means anything, so the test is defined over a closed window by
necessity, not by preference.

### What replaces the hash

A hash over continuously changing state is worthless — it changes every tick and
proves nothing about what a reader saw. But dropping it altogether abandons the
property that made the batch product defensible.

### Cache versus freshness

100 concurrent readers want cached responses; 8,333 events/s suggests they want
fresh ones. This tension is largely false, and naming why is the load-bearing
insight: **all 100 readers are looking at the same numbers.** The correct design
computes each artifact once per tick and serves every reader from that result.
The database sees one analytical sweep per tick, not one per reader.

What remains of the tension is real but small, and it resolves against
freshness: since settlements reverse inside 95 seconds, a GGR figure refreshed
every 100 ms would show numbers that contradict themselves on screen. Sub-second
freshness for Class 2 is not a feature, it is a misrepresentation.

## Decision

**Each layer declares its own freshness, and the UI states it. No number is
presented without the reader being able to learn how old it is and over what
window it was computed.**

Refresh cadence per class, chosen from the data's own behaviour:

| Class | Refresh | Justification |
|---|---|---|
| 1 — placement-complete | every tick (~1–5 s) | Inputs immutable; only ingest lag limits it |
| 2 — settlement-complete | ~30–60 s | Faster than settlement churn (measured 95 s) reports noise |
| 3 — windowed | on window close (Gini/anomalies), on kick-off + window close (sharp) | The statistic is undefined without a closed window |

**The guarantee becomes hash-per-tick plus watermark.** Each refresh emits an
artifact carrying, as the batch product already does, a `payload_hash` — and, new
under streaming, a **watermark**: the exact position in the stream the artifact
saw (highest ingested version, per ADR-0007).

This preserves the original property in continuous form. The batch claim was
"this artifact is reproducible from this dataset". The streaming claim is **"this
artifact is reproducible by replaying the stream to this watermark"** — same
promise, with the input identified by position instead of by file. Because
supersedence is resolved by version and not by arrival order (ADR-0007), replay
to a given watermark is deterministic, so the hash is a real check and not
decoration.

The `dataset_fingerprint` of the batch product becomes the **source lineage**:
which partners, which offsets, which schema version contributed.

**The footer carries the per-layer status.** The existing footer already carries
fingerprint and hash and is the established home of the guarantee, so it gains a
per-layer block: for each class, its age, its window where applicable, and the
watermark. Individual figures are not tagged inline — the cockpit is dense by
design, and per-number annotations would cost more legibility than they buy. The
footer is the one place a reader looks to learn what they are looking at.

**Cache policy follows the class, not a global TTL.** Class 1 gets a short TTL
with stale-while-revalidate; Class 2 a longer TTL; Class 3 is cached until its
window closes and invalidated by event rather than by clock. A single TTL across
all three would either serve stale turnover or waste work re-serving an unchanged
Gini.

## Consequences

**Positive**

- The reader is never misled about what is live. The hardest failure mode of a
  streaming dashboard — a windowed statistic silently read as realtime — is
  addressed by construction rather than by documentation.
- Reproducibility survives the transition. "Replay to watermark W and you get
  hash H" is testable, and it is the same test the batch pipeline already runs in
  its invariant suite.
- Refresh cadences are defensible from measurement (95-second settlement churn,
  immutable turnover) instead of chosen for feel.
- Cache invalidation stops being guesswork: what can change and how fast is a
  property already established per class.
- The 100-reader requirement is met by computing once per tick, not by scaling
  the database — which is also why it stays met as readers grow.

**Negative**

- Three cadences mean three code paths and three cache policies. A single TTL
  would be simpler, and simplicity has real value; this trades it for not lying
  about freshness.
- The footer becomes denser. A reader who does not look at it can still
  misread a windowed number as live — the design mitigates this and does not
  eliminate it. Per-number labelling would eliminate it at a cost to the
  cockpit's density that was judged not worth paying, and that judgment is
  reversible.
- Class 3 latency is bounded below by the domain, not by engineering. Sharp
  behaviour for a fixture cannot appear until that fixture kicks off, and no
  amount of hardware changes it. This will read as a limitation to anyone who
  has not followed the argument, and it must be explained rather than hidden.
- Watermark-based reproducibility requires the transport to retain enough
  history to replay from. That is a retention cost, and it bounds how far back
  the guarantee reaches — beyond the retention window, the claim weakens from
  "reproducible" to "audited".
- A hash per tick is not comparable across ticks. Readers accustomed to a stable
  hash identifying "the" artifact must adjust to a hash identifying *a moment*.
