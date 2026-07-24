# Design

Visual system shared by the **notebook** (matplotlib) and the **frontend**
(HTML/CSS). Both consume the same hexes — if they diverge, that is a bug.

The palette derives from the `dataviz` method and is **script-validated against
Sporting Risk's own surface colour**, not eyeballed:

```
node scripts/validate_palette.js "#3987e5,#d95926,#199e70,#c98500" \
  --mode dark --surface "#1a2129"
→ ALL CHECKS PASS (lightness band, chroma floor, CVD separation,
  normal-vision floor, contrast vs surface)

# scatter/bubble cap — first 3 slots, all pairs
node scripts/validate_palette.js "#3987e5,#d95926,#199e70" \
  --mode dark --surface "#1a2129" --pairs all
→ ALL CHECKS PASS
```

## Brand alignment

The visual identity is taken from **Sporting Risk's own brand**, extracted from
their logo and stylesheet (`sportingrisk.com`), not invented:

| Token | Value | Source |
|---|---|---|
| Body background | `#1a2129` | `body { background: #1a2129 }` |
| Body text | `#ffffff` | `body { color: #ffffff }` |
| Brand accent | `#9b7755` | the logo mark; 44 declarations in their CSS |
| Client typeface | Inter 400/700 | their site (retired here for a 3-role system — see Typography) |

Their site is already dark, so the theme choice below and the brand agree — no
trade-off between serving the use case and honouring the identity.

**Ignored from their stylesheet:** `#0d6efd`, `#dc3545`, `#198754`, `#ffc107`,
`#0dcaf0`, `#6c757d`, `#212529`. That is the stock **Bootstrap 5.2.0** palette
shipping with their theme, not brand identity. Adopting it would be copying a
framework default and mistaking it for a design system.

### How the brand accent is used

`#9b7755` **fails the chart-series chroma floor** (0.066, reads as grey on thin
marks) while **passing contrast against the surface** (≥3:1). So it is an
*identity* colour, not a *data* colour — which is exactly how Sporting Risk
themselves use it: borders, link hover, scrollbar thumb, `::selection`. Never an
area fill.

Permitted: rules and section dividers, focus rings, active/selected state, link
hover, the header mark, table row emphasis.
**Never:** a chart series, a stacked segment, a status colour.

## Theme

**Dark, committed.** The scene sentence that forces the choice: *a risk trader
reading turnover distributions at 11pm, in a low-light room across three
screens, hunting the anomaly nobody has spotted yet.* That scene does not admit
a white page.

This is not dark because "tools look cool dark" — it is dark because the surface
must recede for the data to advance, and because high density on a light ground
fatigues on long reads. It also happens to be what the client's own brand does.

## Color

### Surfaces and ink

Surfaces are the brand's `#1a2129` and steps around it; ink follows the
`dataviz` dark ramp.

| Role | Hex | Note |
|---|---|---|
| Page plane | `#141a20` | one step below the brand background |
| Chart surface | `#1a2129` | **brand body colour** |
| Raised surface | `#222b35` | cards, table headers |
| Primary ink | `#ffffff` | brand text colour |
| Secondary ink | `#c3c2b7` | |
| Muted (axes, labels) | `#898781` | |
| Gridline (hairline) | `#2a333d` | tinted toward the brand hue |
| Baseline / axis | `#38434f` | |
| Brand accent | `#9b7755` | chrome only — never a series |
| Border (hairline ring) | `rgba(255,255,255,0.10)` | |

### Categorical (fixed order, never cycled)

| Slot | Hue | Dark |
|---|---|---|
| 1 | blue | `#3987e5` |
| 2 | orange | `#d95926` |
| 3 | aqua | `#199e70` |
| 4 | yellow | `#c98500` |

**Ceiling of 4 series** for bars/lines/stacks (adjacent pairlist). For
scatter / bubble / small-multiples the ceiling drops to **3 slots** — beyond
that the palette fails the all-pairs colour-vision thresholds. Series 5+ folds
into "Other", a facet, or small multiples. Never generate a new hue.

### Status (reserved, never becomes "series 5")

| Role | Hex |
|---|---|
| good | `#0ca30c` |
| warning | `#fab219` |
| serious | `#ec835a` |
| critical | `#d03b3b` |

Always paired with **icon + label**. Colour never carries meaning alone.

### Sequential / diverging

- **Sequential:** one hue, light→dark. Base blue `#3987e5`.
- **Diverging:** two poles + neutral grey midpoint. Never a hue at the midpoint,
  never a rainbow.

The natural risk pair (profit/loss) is red-green — precisely the axis
deuteranopia/protanopia destroys. Positive vs negative GGR therefore **always**
carries redundant signal (position, direct label, or shape), never colour alone.

## Typography

Three self-hosted roles (via `@fontsource*`), paired on contrast axes, never on
similarity:

- **Numbers and data: JetBrains Mono** (`"JetBrains Mono Variable", ui-monospace,
  …`) with tabular figures. Mandatory in every table, KPI, axis label and hash —
  without it, number columns fail to align and comparison breaks.
- **Titles and headings: Space Grotesk** (`"Space Grotesk Variable", …`, the
  `font-display` token). Used only on section titles, detector headings and the
  Betflow wordmark — never on labels, buttons or data (product ban on display
  fonts in UI chrome).
- **Body and descriptions: Albert Sans** (`"Albert Sans", ui-sans-serif, …`).

The three sit on real contrast axes (geometric-display vs humanist-body vs
monospace-data), so none violates the "never pair two similar sans-serifs" rule.
The earlier single-Inter system is retired; Inter was what the client's own site
used, and the three-role system is a deliberate step up in craft.

Rules: body capped at 65–75ch (applies to the few remaining prose spots — the
cockpit is data-led, not prose-led). Display `letter-spacing` ≥ -0.02em.

## Register: operational cockpit

Task 1 is an **operational monitoring cockpit**, not a readable report: a screen
a risk/trading desk keeps open and scans in seconds. Consequences for design:

- **Maximum density, minimal prose.** No standfirsts, no lead paragraphs.
  Assumptions and limitations fold behind an `InfoTip` (info icon → tooltip),
  reachable but never a wall of text.
- **Alerts first.** An always-visible active-alerts panel (sharp windows,
  exposure, spikes) sits atop the content; the rail carries per-section alert
  badges. Colour on these is severity, mapped to the status ramp (good #0ca30c /
  warning #fab219 / serious #ec835a / critical #d03b3b) plus a neutral
  `signal` class for operational signatures that are not verdicts (ADR-0003).
- **KPI tiles are full.** Every tile carries label + mono value + delta + a data
  visual (sparkline / margin bar / severity dots) + a microline — no dead space,
  which is the failure the redesign fixed.
- **One currency selector** drives every money figure (topbar). Money shows one
  currency at a time, never stacked or summed across currencies (ADR-0001).

## Marks (chart specs)

- Thin marks; 4px rounded data-ends anchored to the baseline.
- 2px lines; ≥8px markers.
- 2px surface-coloured gap between adjacent fills (stacks and bars alike).
- Grid and axes **recessive** — hairline, never competing with the data.
- Selective direct labels. **Never** a number on every point.
- Legend present whenever there are ≥2 series; ≤4 series also carry direct
  labels.
- Text wears ink tokens, **never** the series colour.

## Layout

- Flexbox for 1D, Grid for 2D. Responsive grid without breakpoints:
  `repeat(auto-fit, minmax(280px, 1fr))`.
- Wide content (tables, charts) scrolls inside its own container
  (`overflow-x: auto`). The body never scrolls horizontally.
- Semantic z-index scale (dropdown → sticky → modal → toast → tooltip). Never
  999.

## Motion

- Exponential ease-out (quart/quint/expo). No bounce, no elastic.
- Never animate layout properties.
- Reveals **enhance** an already-visible state — never gate content visibility
  on a class. A chart that only appears after a transition renders blank in
  headless screenshots and hidden tabs.
- `@media (prefers-reduced-motion: reduce)` alternative on every animation.

## Bans (inherited from PRODUCT.md, restated here)

Side-stripe borders · gradient text · decorative glassmorphism · hero-metric
template · identical card grids · tracked eyebrow on every section · numbered
section scaffolding · text overflowing its container · dual-axis (two y-scales)
· rainbow palettes · a hue at the diverging midpoint.
