# 1. Analyse currencies separately instead of converting

Date: 2026-07-23

## Status

Accepted

## Context

The betslip exports carry three currencies with no FX rate supplied:

| Currency | Betslips | Region |
|---|---|---|
| EUR | 68,575 | Spain (all regions) |
| PEN | 7,425 | PERU only |
| USD | 66 | PERU only |
| *(null)* | 1,366 | ESTATAL 1,310 · PERU 119 · other 21 |

*(Betslip counts reflect the corrected key of ADR-0003.)*

Summing these figures directly would be arithmetically meaningless. Because
1 EUR is roughly 4 PEN, an unconverted sum reports Peru as **25.2%** of turnover
when its real economic weight is closer to **7–8%** — a three-fold
overstatement of a whole market.

Two facts make separation clean:

- No betslip mixes currencies (verified: 0 cases).
- PEN and USD appear exclusively in the PERU region.

One fact complicates it: **1,366 betslips (1,450 legs, 31,456 turnover units)
carry no currency at all.** They cannot be assigned by region either — they
straddle both tracks (1,310 in ESTATAL, 119 in PERU). Inferring their currency
would be exactly the kind of invented number this decision exists to avoid.

Three options were considered:

1. **Convert** using a rate fixed in code and declared as an assumption.
2. **Separate** — never sum across currencies; every volume figure is reported
   within one currency.
3. **EUR-only scope**, with Peru as an appendix.

## Decision

Analyse **Spain (EUR) and Peru (PEN/USD) separately**. No currency conversion is
performed anywhere in the pipeline. No figure ever sums across currencies.

Betslips with a null currency form a third, explicit **"currency unresolved"**
bucket: excluded from every money figure, included in every currency-free measure
(counts, timing, concentration, price value), and reported by size wherever money
totals appear — so a reader can see exactly what sits outside the two tracks.

The artifact schema enforces this structurally: money-bearing blocks nest under a
currency key, making a cross-currency sum impossible to express rather than
merely discouraged.

Any chart or table showing turnover states its currency. Cross-market comparison
uses currency-free measures — shares, counts, timing distributions, concentration
ratios, price value in odds terms — never absolute money.

## Consequences

**Positive**

- No invented number enters the analysis. Every monetary figure is exactly what
  the source system recorded.
- Removes an obvious line of attack: a reviewer cannot ask "where did that FX
  rate come from?"
- Currency-free measures (concentration, timing, price value) remain fully
  comparable across markets, and those carry most of the analytical weight.

**Negative**

- No single consolidated "total turnover" figure exists for the client as a
  whole. The report must resist the reflex to produce one.
- Volume sections fragment into two tracks, costing some narrative simplicity.
- USD (66 betslips, 0.04%) is too small to analyse on its own and is reported as
  a residual rather than a third track.

**Revisit if** an official FX rate is supplied, or if the client asks for a
consolidated group figure. Conversion would then be a presentation layer over
the same native-currency aggregates, not a change to the pipeline.
