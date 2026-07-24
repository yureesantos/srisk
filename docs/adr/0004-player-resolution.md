# 4. Resolve player names from `Option`, not from the `Player` column

Date: 2026-07-23

## Status

Accepted — **amended 2026-07-23** (see "Amendment: template markets are
recoverable" below). The original coverage claim of 62.3% was too pessimistic.

## Context

The brief asks for betting flow analysed "by fixture, market, team, **player**,
selection, bet type and time phase". The export ships a column literally named
`Player`, so the obvious implementation is `groupby("Player")`.

That implementation would be wrong. Inspecting the column shows it holds the
**Spanish translation of the market name**, not a person:

| `Player` value | Legs | What it actually is |
|---|---|---|
| `1-X-2 / Ventaja 2 goles` | 15,019 | market name |
| `Corners equipo` | 8,935 | market name |
| `Marcar gol o asistir (Suplente Estrella)` | 7,932 | market name |
| `Goleador durante el partido (Suplente Estrella)` | 7,050 | market name |
| `Partido` | 6,091 | market name |

None of the twelve most frequent values is a person. **52.7% of legs** carry a
recognisably Spanish market label in this column.

The real player names live in **`Option`**. On player-centric markets
(`{PLAYER}` templates, goalscorer, to-score, assist, hat-trick, saves — 43,183
legs, 38.3% of all legs), `Option` holds names: Mbappe (2,513), Cristiano
Ronaldo (2,229), Lionel Messi (1,927), Harry Kane (1,874), Haaland (1,400).

`Option` is itself overloaded: on the same markets it also carries line values
("2 or more", "1 or more"), and on non-player markets it carries selections
("Over 2.5", "Jordan 2 or more").

A naive `groupby("Player")` would therefore produce a table of translated market
names presented as players — an error invisible to a non-Spanish-speaking author
and immediately obvious to a Spanish-speaking reviewer.

## Decision

Player identity is resolved by a **market-family-scoped resolver**, not a
groupby:

1. Restrict to player-centric market families (identified from the raw `Market`
   template, before placeholder stripping).
2. Within those, extract the player name from **`Option`**, rejecting values that
   are line expressions (digits, "or more", "Over"/"Under", "Yes"/"No").
3. Report **coverage** alongside every player-level output: the share of
   player-centric legs where a name was resolvable.

Measured coverage: **62.3%** of player-centric legs yield a name (691 distinct
players). The remaining 37.7% are markets like `Shots on target {PLAYER}` where
the player lived in the unresolved template placeholder and is **unrecoverable
from this export**.

The `Player` column is retained as a *Spanish market label*, useful for
cross-checking market normalisation, and is never used as a person.

## Consequences

**Positive**

- Player analysis reports real players. The top of the table (Mbappé, Messi,
  Kane, Haaland) is face-valid to anyone who follows football — itself a check
  that the resolver works.
- Coverage is stated rather than implied, so a reader knows the denominator.
- Catches an error class that would have survived review by a reader who does
  not read Spanish.

**Negative**

- Player analysis covers 62.3% of player-centric legs, not 100%. Any "top player
  by turnover" ranking is a ranking *within resolvable legs* and must be labelled
  as such.
- Name forms are inconsistent across the feed ("Mbappe" vs "Kylian Mbappé",
  "Haaland" vs "Erling Haaland"). No entity resolution is attempted here — that
  is the reconciliation service's problem, not Betflow's — so a player may appear under two spellings.
  Stated as a limitation.
- The resolver depends on the raw `Market` template, so it must run before
  placeholder stripping.

---

## Amendment: template markets are recoverable after all

Date: 2026-07-23

Re-testing this decision while planning `betflow.py` showed the "unrecoverable"
claim above is **wrong**. On `{PLAYER}`-template markets the `Player` column does
not merely hold a market label — it holds the label **with the player's name
embedded**:

```
Remates a puerta Arda Güler (Suplente Estrella)
Asistencias Anthony Elanga
Faltas recibidas Bruno Fernandes
2º tiempo: Remates a puerta Viktor Gyokeres
```

The name is extractable without a hand-maintained Spanish dictionary. Within one
raw `Market`, the Spanish prefix is constant, so it can be derived from the data
as the **longest common prefix** of that market's labels; whatever follows is the
name.

Measured on the export: **1,910 of 1,910 distinct template labels yield a name —
100%.** This recovers **13,016 legs** the original decision wrote off.

### Revised decision

The resolver runs three stages:

1. **`{PLAYER}` template markets** — derive the market's Spanish prefix as the
   longest common prefix of its labels; the remainder of `Player` is the name.
   Reject any remainder containing a digit.
2. **Name-in-`Option` markets** (goalscorer, to-score, assist, hat-trick, …) —
   the name is in `Option`; reject line expressions (digits, "or more",
   "Over"/"Under", "Yes"/"No", over-long combo text).
3. Everything else is not player-centric.

Stage 1 must be evaluated **before** stage 2: `Assists {PLAYER}` and
`To score or assist` both match an "assist" keyword, and only the template test
separates them.

### Consequences of the amendment

- Player coverage rises well above the original 62.3%; the pipeline reports the
  measured figure rather than restating a constant.
- No Spanish dictionary is hardcoded, so the method survives new markets and new
  competitions.
- The entity-resolution limitation is unchanged: `Mbappe` and `Kylian Mbappé`
  remain distinct rows. That is the reconciliation service's problem, not Betflow's.
- **Recorded deliberately rather than silently corrected.** A decision that
  survives re-testing is worth more than one that was never re-tested, and the
  original pessimistic claim would have been demonstrably false if published.
