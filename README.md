# Sporting Risk — take-home

Two independent exercises for Sporting Risk.

## Task 1 — Betflow Analysis

An analysis of betting flow (turnover, timing, concentration, price value and
movement, anomaly detection, sharp-customer flagging) delivered as:

- a **Python pipeline** (`task-1-betflow/src`) that produces a single validated
  artifact from the raw exports, and
- an **operational dashboard** (`task-1-betflow/dashboard`) — a dense monitoring
  cockpit that reads that artifact and lets every figure be traced to its
  evidence.

**Live dashboard:** https://yureesantos.github.io/srisk/

See [`task-1-betflow/dashboard/README.md`](task-1-betflow/dashboard/README.md)
for how the two fit together, and [`PRODUCT.md`](PRODUCT.md) /
[`DESIGN.md`](DESIGN.md) for the product and design decisions.

## Task 2 — Two-feed reconciliation

Reconciling one match, described by two providers with completely different
schemas, into a canonical model — carrying both source ids and a confidence on
every mapped entity, resolving conflicts on the evidence, and flagging what it
cannot map for human review rather than guessing.

```bash
cd task-2-reconciliation
python -m src               # reads feeds/*.json → out/canonical.json + out/review.json
pip install pytest && python -m pytest
```

See [`task-2-reconciliation/README.md`](task-2-reconciliation/README.md) and its
[`SUBMISSION.md`](task-2-reconciliation/SUBMISSION.md) for the reconciliation
decisions and their rationale.

## Documentation

- [`PRODUCT.md`](PRODUCT.md) — who this is for and what it must do.
- [`DESIGN.md`](DESIGN.md) — the visual system and its constraints.
- [`CONTEXT.md`](CONTEXT.md) — the domain glossary (ubiquitous language).
- [`docs/DATA-FINDINGS.md`](docs/DATA-FINDINGS.md) — measured facts about the data.
- [`docs/adr/`](docs/adr) — architecture decision records.
