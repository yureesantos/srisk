# Product

## Register

product

## Users

**Primary: the Sporting Risk CTO and CEO, in a ~10-minute evaluation call.**
They will not browse this out of curiosity — they are looking for evidence of
analytical judgment and engineering competence. They arrive with no prior
context on the dataset, short on time, carrying one implicit question: *does
this person understand betting risk, or only how to draw a chart?*

**Secondary (simulated): a RetaBet risk trader.** The dashboard should be
plausible as a real trading-desk tool — that plausibility is what proves the
author understood the domain, not just the data.

Job to be done: in minutes, understand where betting flow concentrates, whether
customer behaviour is distributed or anomalous, and **be able to verify every
conclusion** against the data behind it.

## Product Purpose

Turn ~112k raw betslip legs (RetaBet, Spain + Peru, football, Mar–Jun 2026) into
a Betflow read a trader would trust: volume, timing, market/selection
concentration, price movement and anomalies.

Success means the reader can point at a claim and find the figure that supports
it *or breaks it*. The brief asked literally for charts "that allow the
conclusions to be verified" — verifiability is the requirement, illustration is
not.

The Python pipeline is the source of truth; the frontend consumes pre-aggregated
JSON. No business calculation happens in the browser.

## Brand Personality

**Rigorous, direct, no theatre.** The voice of a senior analyst showing their
work: states what the data supports, states explicitly what it does not, and
treats limitations as first-class information rather than an embarrassed
footnote.

Three words: *precise, dense, honest*.

The target emotional register is **sober confidence** — the feeling of reading a
calibrated instrument, not a sales deck.

## Anti-references

- **Generic SaaS dashboard.** No hero-metric template (giant number + tiny label
  + gradient), no endless grid of identical icon+title+text cards, no tracked
  uppercase eyebrow above every section.
- **Consumer betting site.** No neon green, gold, glow, or flashing odds. This is
  an internal risk instrument, not a conversion surface.
- **Crypto/trading-bro.** No neon red/green candles, no theatrical "hacker
  terminal" styling, no decorative glow. Dark, yes; spectacle, no.
- **Stiff corporate report.** No consultancy navy, no flat grey tables without
  hierarchy, no PowerPoint air. Defensive neutrality is an aesthetic choice too —
  and the wrong one here.

## Design Principles

1. **Verifiability over persuasion.** Every strong claim carries the path to
   checking it. A chart that only restates its own title in colour does not earn
   space on the page.
2. **Show the dirty work.** Dedup, in-play ambiguity, currencies without an FX
   rate, unresolved placeholders: data quality is a first-class section, because
   that is where judgment shows. Hiding it would hide the best of the work.
3. **Density in service of reading.** Many numbers is the point — but hierarchy
   decides what gets read first. Dense is not cluttered.
4. **No number without its aggregation grain.** Turnover per leg and per betslip
   differ by 1.12x. Every displayed figure states the level it was aggregated at.
5. **Uncertainty is labelled, not smoothed.** Where the data does not support a
   conclusion, the interface says so instead of picking the prettier reading.

## Accessibility & Inclusion

- **WCAG 2.1 AA.** Body text ≥4.5:1; large text ≥3:1. No decorative light grey
  on body copy.
- **Colour-blind safe.** Series are never distinguished by hue alone — luminance,
  shape or a direct label always accompanies it. Critical here because the
  natural risk pair (profit/loss) is exactly red-green, and deuteranopia/
  protanopia affect ~8% of men.
- **`prefers-reduced-motion`** honoured on every animation, with a crossfade or
  instant-transition alternative.
- Numbers set in a monospace face with **tabular-nums** so columns align
  vertically and comparison holds.
