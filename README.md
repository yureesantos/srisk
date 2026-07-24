# Sporting Risk — betting intelligence

Two components of a betting-risk stack: **Betflow**, an operational analytics
cockpit that turns raw betslip data into a trading desk's view of its book, and
**Reconciliation**, a service that fuses match data from disagreeing providers
into one trustworthy canonical model.

They are independent — different problems, different stacks — but both answer the
same question a risk desk lives by: *can I trust this number, and where did it
come from?*

---

## Betflow — betting-flow analytics

**Live: https://yureesantos.github.io/srisk/**

An analysis of how betting flow develops across football fixtures, markets,
teams, players, selections, bet types and timing phases — turnover and GGR,
timing relative to kick-off, market and customer concentration, price value and
movement, anomaly detection, and statistically-flagged sharp customers.

It is delivered as two layers with a hard seam between them:

- **The pipeline** (`betflow/src`) — a deterministic Python pipeline that reads
  the raw exports, does every calculation once, validates eight families of
  invariants, and emits a single hashed artifact. It is the source of truth.
- **The cockpit** (`betflow/dashboard`) — a dense, always-on monitoring surface
  (React + Vite + TypeScript + ECharts) that renders that artifact and **computes
  nothing of its own**. Active alerts sit on top; every figure can be traced to
  the exact rows behind it via a built-in verify path.

Why the split matters: if a number on screen looks wrong, it is a pipeline
question, not a UI one — the dashboard only ever shows what the pipeline
validated, and the footer carries the dataset fingerprint + payload hash to prove
which run produced it.

```bash
# regenerate the artifact from the raw exports
cd betflow && python -m src.pipeline

# run the cockpit locally
cd betflow/dashboard && npm install && npm run dev     # http://localhost:5173
npm run build                                          # static build → dist/
```

The cockpit deploys to GitHub Pages automatically on every push that touches it
(`.github/workflows/deploy-dashboard.yml`); the site is fully static, with the
artifact baked in at build time, so there is no backend to run.

See [`betflow/dashboard/README.md`](betflow/dashboard/README.md) for how the two
layers fit together, and [`PRODUCT.md`](PRODUCT.md) / [`DESIGN.md`](DESIGN.md) for
the product and design decisions.

### What it surfaces

- **Key findings** — a trader-friendly briefing (what happened, why it matters,
  what to investigate), each linked to its evidence.
- **Flow by dimension** — turnover and volume by market, competition, fixture,
  selection, team, region and bet type, with the aggregation grain always stated.
- **Timing** — flow relative to kick-off (pre-match, post-line-ups proxy,
  in-play upper bound).
- **Price value & movement** — taken prices vs a later reference price; steamers
  and drifters.
- **Concentration** — Lorenz curves and Gini for customers and fixtures.
- **Anomaly detectors** — turnover spikes, abnormal exposure, sharp price moves,
  repeated backing, same-second clusters — each with its rule and confidence.
- **Sharp behaviour** — customers beating the reference price by more than
  chance, flagged by a significance test with false-discovery-rate control, not
  a leaderboard.
- **Data quality** — the known imperfections and the decisions taken around them.

---

## Reconciliation — canonical model from two feeds

Two providers describe the same match with completely different schemas —
different id types, name formats, odds representations, stat keys, and even a
disagreement on the final score. This service maps their entities into one
canonical model, **carrying both source ids and a confidence on every mapping**,
resolves conflicts on the evidence, and **flags what it cannot map for human
review rather than guessing**.

```bash
cd reconciliation
python -m src                          # feeds/*.json → out/canonical.json + out/review.json
pip install pytest && python -m pytest # 38 tests
```

The decisions are the substance: the score conflict is resolved on evidence (each
feed's own per-player goal tally corroborates one score and contradicts the
other), kickoff is compared as an instant rather than a string, odds are kept as
per-source quotes rather than collapsed, and nothing below the match threshold is
ever force-matched.

See [`reconciliation/README.md`](reconciliation/README.md) for the model and the
run details, and [`reconciliation/SUBMISSION.md`](reconciliation/SUBMISSION.md)
for the decisions and their rationale.

---

## Repository

```
betflow/            betting-flow analytics
  src/              the Python analysis pipeline
  dashboard/        the React monitoring cockpit
  outputs/          generated analysis artifacts
reconciliation/     two-feed canonical reconciliation (Python)
docs/
  DATA-FINDINGS.md  measured facts about the source data
  adr/              architecture decision records
PRODUCT.md          who the cockpit is for and what it must do
DESIGN.md           the visual system and its constraints
CONTEXT.md          the domain glossary (ubiquitous language)
```
