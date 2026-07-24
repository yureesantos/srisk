# 5. Reference price is a guarded proxy, grouped down to the player

Date: 2026-07-23

## Status

Accepted

## Context

The brief asks whether customers "got value" — did the price they took beat the
market's later reading? The export has no odds history and no closing line, only
the price each customer took. A proxy is required or the question goes
unanswered.

Exploration showed a proxy is viable: 86.8% of legs sit in
(fixture, market, selection) groups that show price variation, and among groups
with ≥5 bets, 96.7% vary.

Three design problems had to be settled.

### Leakage

If a leg's reference is simply "the group's last price", a customer who bets late
sets their own benchmark and scores as neutral — exactly masking the sharp
behaviour the analysis exists to find.

### Group identity

The obvious key `(MatchId, market_normalised, Option)` is **wrong** on
player-centric markets. Market normalisation strips the `{PLAYER}` placeholder,
and `Option` carries only the line ("1 or more"), so the key pools different
players into one group.

A worked example from Spain–Cape Verde, market "Shots on target each half":

| Player | Price |
|---|---|
| Laporte | 15.00 |
| Ferran | 2.09 |
| Ferran | 2.23 |
| Oyarzabal | 2.22 |
| Oyarzabal | 2.28 |

Under the naive key this reports a **5.6x price move**. There is no move at all —
it is Laporte's quote compared against Oyarzabal's.

### Single-actor "movement"

A large swing produced by one customer's repeated bets is that customer's
activity, not a market signal.

## Decision

**Group key:** `(MatchId, market_normalised, Player, Option)`. `Player` holds the
Spanish market label including the player name (ADR-0004), which is exactly the
discriminator needed.

**Reference price:** the last pre-kick-off price in the group that is *strictly
later* than the leg itself. Legs sharing a timestamp are simultaneous and do not
reference each other. A leg that is the group's final observation gets no
reference — that is coverage loss, reported, never imputed.

**Price value:** `taken / reference - 1`. Winsorised at ±50% for aggregates; raw
values retained for the histogram.

**In-play excluded:** after kick-off the price reflects match state, so the
comparison would measure the scoreline rather than the customer's judgement.

**Movement:** measured in implied-probability space so a 1.30→1.20 shift and a
6.00→4.00 shift are comparable. Requires ≥5 legs **and ≥2 distinct Uids** to
qualify as a steamer/drifter.

## Consequences

**Positive**

- Coverage stays high: **74.9%** of all legs are eligible, and **83,419 of
  84,457** eligible legs take their reference from a *different* Uid.
- Correcting the group key cut flagged sharp moves from **502 to 262** — roughly
  half the original signal was an artefact of pooling players.
- Surviving movements are credible: England 7+ shots on target moving 4.29 → 1.64
  across **9 distinct customers** is a real market signal.
- The population beat rate is **43.5%, not 50%**. The proxy's construction biases
  the null downward, because a group's last observation is often an
  already-moved price. Sharp behaviour is judged against this empirical
  baseline — using 50% would manufacture false positives.

**Negative**

- **The sample is biased and cannot be de-biased with this data.** A reference
  exists only where later volume exists, so quiet markets are invisible and
  volatile markets are over-represented. Every price-value figure describes the
  *measurable* book, not the whole book. Stated wherever the figure appears.
- 20,513 legs (the last observation in their group) have no reference at all.
- 3,738 eligible legs take their reference from the same Uid; those readings are
  weaker and are flagged rather than dropped.
- Finer grouping thins the groups, so movement analysis covers 4,254 groups
  rather than the 4,666 the coarser key suggested.
