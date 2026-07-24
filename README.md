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

See [`task-1-betflow/dashboard/README.md`](task-1-betflow/dashboard/README.md)
for how the two fit together, and [`PRODUCT.md`](PRODUCT.md) /
[`DESIGN.md`](DESIGN.md) for the product and design decisions.

## Task 2 — Two-feed reconciliation

Reconciling one match from two provider feeds into a canonical model
(`task-2-reconciliation`).

## Documentation

- [`PRODUCT.md`](PRODUCT.md) — who this is for and what it must do.
- [`DESIGN.md`](DESIGN.md) — the visual system and its constraints.
- [`CONTEXT.md`](CONTEXT.md) — the domain glossary (ubiquitous language).
- [`docs/DATA-FINDINGS.md`](docs/DATA-FINDINGS.md) — measured facts about the data.
- [`docs/adr/`](docs/adr) — architecture decision records.
