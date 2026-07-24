# 6. Flag sharp behaviour with a statistical test, not a percentile cut

Date: 2026-07-23

## Status

Accepted. Supersedes the scoring design sketched while planning ADR-0002.

## Context

The planned scoring was: percentile-rank three components (beat rate, mean price
value, stake-weighted price value), average the ranks into a 0–100 composite,
and flag `composite >= 90`.

Three defects surfaced when the design was challenged.

### A percentile cut flags 10% of anything

`composite >= 90` flags exactly the top decile of *any* population — including
one containing no sharp behaviour at all. A percentile is a relative statement.
Run on pure noise it still flags ~200 of 2,085 windows, every single time. The
rule cannot distinguish "this book has sharps" from "this book has a top
decile", which is precisely the claim the section exists to make.

### The composite measured one thing three times

Beat rate and mean price value are strongly coupled — a window beating the line
65% of the time can hardly show a negative mean value. Mean value and
stake-weighted value are the same numbers under two weightings. The composite
measured roughly one and a half dimensions while presenting as three, and each
extra step (why equal weights? why ranks? why winsorise before ranking?) was
something to defend without buying anything.

### Legs are not independent observations

Several legs by one Uid on the same pricing group share **one** reference price,
so a single favourable move turns all of them into "beats". Feeding raw legs to
a binomial test invites the fatal rebuttal: *"your 30 independent wins are six
bets on six prices."* Measured: **13.7%** of scoring units hold more than one
leg.

## Decision

**Scoring unit** is one distinct priced selection per window —
`(Uid, MatchId, market, Player, Option)` — not one leg. Legs whose reference
came from the same Uid are excluded entirely.

**Ranking** is the percentile rank of the **Wilson 95% lower bound** of the
window's beat rate: the rate defensible given how few bets were seen. 14 beats
from 20 reads as 70% but bounds at 0.481 — barely above baseline. Sample size is
folded into the number rather than bolted on beside it.

**Flagging** is an absolute test, requiring all three of:

1. at least 20 priced units (below that the test cannot resolve anything);
2. an exact one-sided binomial test against the book's own beat rate, with
   **Benjamini–Hochberg** control at `q = 0.10`;
3. stake-weighted price value > 0 in the window's dominant currency — money must
   agree with frequency.

The baseline is the book's **measured** rate (44.4% at unit grain, 43.5% at leg
grain), never 50%: the reference-price proxy biases the null downward
(ADR-0005).

Magnitude figures and behavioural context (late share, in-play share, SIMPLE
share, market focus, terminal signature) are **displayed, never scored**.

Empirical-Bayes shrinkage toward a fitted Beta prior was considered and
rejected: near-identical ranking at these sample sizes, but it adds a prior to
justify and still needs a separate test for flagging.

## Consequences

**Positive**

- **Validated against a null.** Simulating 20 exports of 701 purely random
  windows, the procedure flags **0 windows in 20 of 20 runs**. A raw 5%
  threshold averages 28 false flags per export. The 13 real flags are therefore
  not an artefact of the method.
- The honest arithmetic is reportable: 13 flagged, versus 94 under raw α=0.05
  and 208 under a top-decile cut — the last of which would appear whether or not
  any signal existed.
- Expected false discoveries are bounded and stated: at most ~1.3 of 13.
- Every flagged window is verifiable from its own row: `beats`, `priced_units`,
  `beat_rate`, `wilson_lb`, `p_value`. A reviewer can recompute the test.
- One scored quantity with a textbook name replaces a bespoke composite. In a
  technical call it is one sentence.

**Negative**

- 701 of 2,085 scored windows are flag-eligible; the rest carry too few priced
  selections to test. Genuine sharp behaviour in a short window is invisible.
- BH at q=0.10 is conservative. Real sharps with modest edges over few bets will
  be missed — the deliberate trade for a defensible false-positive rate.
- A retail terminal (string-format Uid) aggregates many walk-in customers and
  can clear the test on volume alone. Flagged rows carry `uid_format` and
  `has_same_second_clusters` so an operational read precedes a risk read; they
  are **not** auto-excluded, which would be a silent judgment call.
- A sharp actor spreading activity across several Uids is invisible by
  construction — the standing gap from ADR-0002.
