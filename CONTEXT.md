# Context

Ubiquitous language for this repository. Glossary only — no implementation
detail, no decisions. Decisions live in `docs/adr/`; measured facts live in
`docs/DATA-FINDINGS.md`.

---

## Leg

A single row in a betslip export: one selection, on one market, on one fixture.
A leg is **not** a bet — a combined bet emits one leg per selection, and every
leg of that bet repeats the same stake and result figures.

Market, selection, player and competition analysis aggregates at leg level.

## Betslip

One placed bet, as staked by a customer. Identified by `Uid` + betslip
timestamp. Carries one stake regardless of how many legs it holds.

**Stake and turnover always aggregate at betslip level.** Summing turnover
across legs double-counts (measured inflation: 1.12x).

Avoid "bet" as a standalone term — it is ambiguous between leg and betslip. Say
which one.

## Uid

The identifier shipped in the export's `Uid` column. **Not** a betslip id and
**not** a customer id — it is reused across fixtures and dates. It only becomes
a betslip identity when paired with the betslip timestamp.

Two formats coexist (numeric, string), evidencing two source systems.

## Turnover

Total stake. Always qualified by its aggregation grain — *turnover per betslip*
(the real figure) or *turnover per leg* (inflated; only valid inside a single
market/selection breakdown).

Never state a turnover figure without its grain.

## GGR

Gross Gaming Revenue — operator win. Negative GGR means the customer won.

## Bet builder

A same-game combination staked as one selection, shipped by the feed under the
market names `{COMPETITOR1}` (home side) and `{COMPETITOR2}` (away side). The
`Option` column carries the real combination ("France win y Over 2.5 goals").

Distinct from a plain 1X2 market: different margin and risk profile.

## Region

The canonical geography of a `Management unit`, after stripping the brand
prefix/suffix and accents. `RETABET EUSKADI` and `EUSKADI` are the same region
on two source systems.

## Pre-match / In-play

A leg is **in-play** when its betslip timestamp falls after the fixture's
declared kick-off, and **pre-match** otherwise.

Because `Event date` is the *declared* kick-off, the in-play share is an **upper
bound**, not a measurement: a late pre-match bet with delayed registration is
indistinguishable from a genuine in-play bet on timestamps alone.

## Taken price

The price a customer actually got on a leg, as recorded in `Price`.

## Reference price

The proxy for a closing price: the last price observed on the same (fixture,
market, selection) before kick-off. It is a **proxy**, not a true closing line —
it exists only where late volume exists, and is therefore biased toward markets
that attracted attention.

## Price value

The gap between the taken price and the reference price on the same
(fixture, market, selection). Positive value means the customer took a better
price than the market's later reading — the signal for sharp behaviour.

---

# Task 2 terms

## Feed

One provider's view of a match. This exercise has two: `alpha` (stats-style,
numeric ids, decimal prices) and `beta` (bookmaker-style, string ids, fractional
odds).

## Canonical record

The reconciled entity — team, player, or market — carrying the source ids from
every feed it was matched from.

## Mapping confidence

How strongly a canonical record's cross-feed match is believed. Low confidence
does not silently downgrade a match; it routes the record to review.

## Review item

Anything the reconciler declines to decide: unmatched, ambiguous, or junk
records, and value conflicts it surfaced rather than resolved silently.

An honest review item is preferred over a wrong automatic match.

## Orphan

An entity present in one feed with no counterpart in the other. Orphans occur in
**both** directions (Kovačić exists only in alpha; Foden and Rice only in beta)
and apply to markets as well as players (BTTS is alpha-only; asian_handicap is
beta-only).
