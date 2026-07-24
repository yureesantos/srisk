# 3. Betslip identity is Uid + timestamp, split by BetType

Date: 2026-07-23

## Status

Accepted

## Context

Turnover must aggregate at betslip grain — a combined bet emits one row per leg
and repeats the same stake on each, so summing legs double-counts.

The export ships no betslip id. Candidate keys were tested against two
invariants: stake should be constant inside a betslip, and `BetType` should be
constant.

| Key | Groups | Constant turnover | Constant BetType |
|---|---|---|---|
| `Uid` | 8,909 | 38.5% | — |
| `Uid` + timestamp | 51,801 | 98.0% | 100% |
| `+ Management unit` | 51,801 | 98.0% | 100% |

`Uid` alone is far too coarse. Adding `Management unit` changes nothing, so the
unit is an attribute rather than part of identity.

`Uid` + second-resolution timestamp looked correct, but left **2,213 groups
typed `SIMPLE` holding multiple legs** — impossible by definition, since a
simple bet is one selection.

Investigating those groups distinguished the two competing hypotheses:

- **87%** (1,921) have all legs on the **same fixture**.
- **100%** sit within a **single region** — no collision crosses geography.
- **854** carry **different turnover values** across their legs.

A worked example: same fixture (Ceara–Avai), same market (Total passes), two
different selections (70+ and 65+), stakes of EUR 117 and EUR 183, same second.

That is not one bet mislabelled. It is **two separate single bets placed by one
customer within the same second** — the timestamp simply is not fine-grained
enough to separate them.

## Decision

Betslip identity is `Uid` + betslip timestamp, **split further by `BetType`**:

- `COMBINED` legs sharing the key stay grouped — they are one bet with one stake.
- `SIMPLE` legs sharing the key are given distinct identities — each is its own
  bet with its own stake.

Every leg involved in such a collision is flagged (`had_key_collision`) so the
data-quality section can report the population rather than hide it.

## Consequences

**Positive**

- Zero `SIMPLE` betslips with multiple legs remain — the invariant now holds.
- Stake for those 6,706 legs is counted correctly instead of being collapsed
  into one. Betslip-level turnover corrects upward to EUR 1,524,288.
- The residual leg-vs-betslip inflation drops to **1.07x**, and what remains is
  genuine combined-bet structure rather than a keying artefact.
- The anomaly is retained as a reportable finding instead of being deleted as
  noise.

**Negative**

- The key now trusts `BetType`, a field whose reliability was itself in question.
  If `BetType` were wrong on a genuinely combined bet, that bet would be split
  into inflated separate stakes. The 100%-constant-BetType result within the
  base key is the evidence for trusting it, and this residual risk is stated in
  the report.
- Two truly distinct customers colliding on the same Uid and second would still
  be merged when their bets are `COMBINED`. Undetectable with the columns
  available.
- Betslip counts are not comparable to any figure the client produces with their
  own internal betslip id.
