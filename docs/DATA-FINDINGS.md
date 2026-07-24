# Data-quality findings — Task 1 (Betflow)

Verified empirically on 2026-07-23 against the two exports in `data/raw/`.
Every claim here is reproducible from the pipeline; none is an assumption.

---

## 1. The two exports are NOT copies of each other

An initial assumption — *"~75,568 identical rows; the smaller file is almost
entirely a subset of the larger"* — does not survive measurement.

| | BIG (`051729`) | SMALL (`051904`) |
|---|---|---|
| Rows | 115,769 | 51,334 |
| Distinct rows | 78,937 | 34,081 |
| Distinct MatchIds | 369 | 159 |
| Distinct Uids | 8,909 | 5,685 |
| Competitions | 52 | 27 |
| Betslips up to | 2026-06-20 23:54 | **2026-06-23 22:59** |

- Distinct-row intersection: **301** — not ~75k.
- SMALL is **not** a subset of BIG.
- **84 MatchIds** exist only in SMALL; **4 competitions** exist only in SMALL
  (Brazil Serie D, China League Two, Norway Division 2 G.II, Portuguese Cup).
- **1,496 Uids** exist only in SMALL.
- SMALL carries **more recent** data than BIG (23 Jun vs 20 Jun).
- For a MatchId present in both (33890210): BIG holds 1,700 rows / EUR 10,900
  turnover; SMALL holds 109 rows / EUR 102. Different slices, not a sample.

**Decision:** analyse the **union** of both files. Dropping SMALL would discard
84 fixtures and 4 whole competitions.

**Result after dedup:** 167,103 raw rows → **112,717 distinct legs**.

---

## 2. `TURNOVER` must not be summed across legs

`BetType` is either `COMBINED` (majority) or `SIMPLE`. A combined betslip is
emitted as **one row per leg**, and every leg repeats the same `TURNOVER` and
`GGR`. Summing rows double-counts stake.

```
Turnover summed per leg     : EUR 1,630,637.79
Turnover summed per betslip : EUR 1,524,288.49   <- 1.07x inflation
```

The inflation factor is modest (7%) *after* exact duplicates are removed and the
betslip key is corrected (ADR-0003) — before dedup the same naive sum inflates
far more. It is still material for a risk report, and the two figures must never
share an axis unlabelled.

**Decision:** stake/turnover aggregates at **betslip** level; market, selection
and player analysis aggregates at **leg** level. Every displayed figure states
its aggregation level.

---

## 3. `Uid` is not a betslip id

Evidence that `Uid` alone does not identify a betslip:

- 8,909 Uids across 115,769 rows in BIG.
- Only **38.5%** of Uids carry a single `TURNOVER` value.
- **5,867 Uids** appear across more than one fixture.
- One Uid mixes `COMBINED` and `SIMPLE` legs on different fixtures and dates.
- Two formats coexist: numeric (`1694675`) and string (`MAH-03-03813`).

Nor is it a clean customer id: median activity span is 1 day and 25% of Uids
span zero days — too short for an account, too long for a single slip.

**Adopted key:** `Uid` + `Betslip date (utc)`. This yields 98% constant turnover
and **100% constant `BetType`** within a group — strong evidence it is the
betslip grain. Adding `Management unit` changes nothing (identical group count),
so the unit is an attribute, not part of identity.

### Same-second collisions, resolved

`Uid`+timestamp left **2,213 groups typed `SIMPLE` holding multiple legs** —
impossible, since a simple bet is one selection. Investigating them settles which
hypothesis is right:

- **87%** (1,921) hold all legs on the **same fixture**.
- **100%** sit inside a **single region** — no collision crosses geography.
- **854** carry **different turnover values** across their legs.

Worked example: same fixture (Ceara–Avai), same market (Total passes), two
different selections (70+ and 65+), stakes of EUR 117 and EUR 183, same second.

That is **two separate single bets from one customer in the same second**, not
one mislabelled bet. Second-resolution timestamps simply cannot separate them.

Resolved in ADR-0003 by splitting the key on `BetType`: `SIMPLE` legs get
distinct identities, `COMBINED` legs stay grouped. **6,706 legs** are flagged
`had_key_collision` and reported rather than hidden.

**Result:** 0 `SIMPLE` betslips with multiple legs; **77,432 betslips** across
112,717 legs.

### The two Uid formats are two source systems

| Format | Dominant units | Currency skew |
|---|---|---|
| numeric | `RETABET *` (own brand) | carries almost all PEN (Peru) |
| string | regional units (`EUSKADI`, `VALENCIA`, `GALICIA`) | EUR |

Most plausible reading: online (own brand) vs retail (regional), or ES vs PE
platform. Not asserted as fact — recorded as a signal.

---

## 4. Date parsing

Both date columns arrive as **text** in `DD/MM/YYYY HH:MM:SS`. Read without an
explicit `format=`, pandas sorts them alphabetically and yields false ranges
(`01/06 → 31/05`). They must be parsed with
`pd.to_datetime(..., format='%d/%m/%Y %H:%M:%S')`.

Correctly parsed range: **2026-03-10 → 2026-06-24**. Zero unparsed values.

---

## 5. In-play share ≈ 6.9% (union)

`Betslip date > Event date`:

| Scope | Share |
|---|---|
| BIG only | 4.83% |
| SMALL only | 4.30% |
| **Union (analysed universe)** | **6.87%** |

The union is higher because it includes the fixtures unique to SMALL, whose
profile differs.

**Caveat, not yet resolved:** `Event date` is the *declared* kick-off. A bet
timestamped shortly after it may be a late pre-match bet with delayed
settlement rather than a true in-play bet. Treated as an upper bound on in-play
activity until validated against the shape of the timing distribution.

---

## 6. Three currencies, no FX rate supplied — and 1,366 betslips with none

Betslip-grain counts: `EUR` 68,575 · `PEN` 7,425 · `USD` 66 · **null 1,366**.

No exchange rate ships with the data. Summing unconverted would report Peru as
~25% of turnover when its real economic weight is ~7–8%, because 1 EUR ≈ 4 PEN.
Resolved in ADR-0001: **analyse Spain and Peru separately, never convert.**

**1,366 betslips (1,450 legs, 31,456 turnover units) carry no currency at all**
and cannot be assigned by region either — they straddle both tracks (1,310 in
ESTATAL, 119 in PERU). They form an explicit "currency unresolved" bucket:
excluded from money figures, retained in currency-free measures.

---

## 7. Unresolved template placeholders in `Market`

**23.7% of legs** (26,761) carry an unsubstituted template in the market name
across 39 distinct raw labels: `Shots on target {PLAYER} (Star Substitute)`,
`{goalnr}{ordinal} goal scorer`, `Saves {PLAYER}`, and others.

Two of them are the *entire* market name rather than a slot inside it:

| Raw | Legs | What it actually is |
|---|---|---|
| `{COMPETITOR1}` | 9,467 | home-side same-game combo |
| `{COMPETITOR2}` | 2,474 | away-side same-game combo |

Inspecting these rows shows `Player` holds the team name (sometimes in Spanish —
"Francia", "Sudáfrica") and `Option` describes the real combo
("France win y Over 2.5 goals"). These are **bet builders**, not plain 1X2 —
a distinct risk and margin profile.

A naive strip-the-placeholder rule maps both to an empty string, dumping 10.6%
of all legs into `UNKNOWN`. They are therefore named explicitly.

**Result:** `UNKNOWN` markets reduced from 11,941 legs to **0**.

---

## 8. The export is effectively a June book, not a Mar–Jun series

Betslip volume by month:

| Month | Active days | Betslips | Median/day |
|---|---|---|---|
| March | 4 | **4** | 1 |
| April | 5 | **11** | 1 |
| May | 29 | **117** | 3 |
| **June** | 23 | **77,300** | **3,417** |

**June carries 99.8% of all betslips.** March through May contribute 132
betslips across 38 days — that is not a quiet trading period, it is residual
early betting on June fixtures (the 2026 World Cup appears throughout the data).

**Consequences:**

- Describing the dataset as "Mar–Jun 2026" is misleading. It is a ~23-day book
  with a three-month tail.
- **Time-series anomaly detection is not supportable.** A whole-period baseline
  compares June against March and flags every June day; a 21-day trailing window
  runs off the end of the operating period. The turnover-spike detector is
  therefore restricted to the dense operating period and reported as
  low-confidence by construction, rather than tuned until it produces
  satisfying-looking output.
- Any per-day or per-week trend claim would be reading noise. Timing analysis
  runs on **minutes to kick-off**, which is well-populated, rather than on
  calendar time.

---

## 9. The `Player` column does not contain players

The column named `Player` holds the **Spanish translation of the market name**,
not a person. Its twelve most frequent values are all market labels:
`1-X-2 / Ventaja 2 goles` (15,019), `Corners equipo` (8,935), `Goleador durante
el partido` (7,050), `Partido` (6,091). **52.7% of legs** carry a recognisably
Spanish market label there.

Real player names live in **`Option`** on player-centric markets: Mbappe (2,513),
Cristiano Ronaldo (2,229), Lionel Messi (1,927), Harry Kane (1,874), Haaland
(1,400) — 691 distinct names.

A naive `groupby("Player")` would output translated market names labelled as
players. Resolved in ADR-0004 (as amended) with a market-family-scoped resolver:
`{PLAYER}` template markets carry the name inside the Spanish label and yield it
via a data-derived prefix; the remaining families read it from `Option`.
**Measured coverage: 99.98% of player-centric legs (44,229 of 44,237), 1,026
distinct players.**

---

## 10. `Management unit` has duplicate granularity

31 raw values containing apparent brand/region pairs: `EUSKADI` **and**
`RETABET EUSKADI`; `ANDALUCIA` **and** `RETABET ANDALUCIA`; `PERU` **and**
`RETABET PERÚ` (accented).

Normalised to **21 canonical regions** by stripping the brand prefix/suffix and
accents, preserving the original value so the origin channel is not lost.
