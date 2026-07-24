# Two-feed match reconciliation

Reconciles one football match described by two providers with completely
different schemas into a single canonical model — carrying both source ids and a
confidence on every mapped entity, resolving conflicts on the evidence, and
flagging anything it cannot map or resolve for human review rather than guessing.

## Run

```bash
python -m src                      # reads feeds/*.json, writes out/*.json
python -m src <alpha> <beta> --out <dir>
python -m pytest                   # the test suite (needs: pip install pytest)
```

`python -m src` prints a one-screen summary and writes:

- `out/canonical.json` — the reconciled match.
- `out/review.json` — the human-review list.

Runtime is the **standard library only** (`json`, `dataclasses`, `datetime`,
`unicodedata`, `fractions`). The single dev dependency is `pytest`.

## The canonical model

One `Match` with reconciled match-level fields (competition, kickoff, status,
score), and lists of `Team`, `Player`, `Market`. Two ideas run through it:

- **Facts get a resolved value with provenance.** Score, stats and kickoff are
  facts about the match, so each is a `FieldValue`: the chosen `value`, whether
  the feeds `agreement`d, each feed's raw value in `sources`, and — on
  disagreement — the `resolution` rule and a `review_ref`.
- **Quotes are never collapsed.** Odds are per-bookmaker prices, not facts, so a
  `Selection` keeps both feeds' decimal-normalized prices side by side; a
  divergence is flagged as *info*, not resolved away.

Every mapped entity carries **both source ids** (either may be null) and a
`Mapping` with a `status` (`matched` / `provisional` / `unmatched`), a
`confidence`, and the `method` used.

## Key decisions

- **Flag, don't guess.** Below the match threshold an entity stays `unmatched`,
  kept in the output with its single source id and a review item — never
  force-matched. Nothing is silently dropped.
- **Confidence is a few documented tiers, not a fake-continuous score:** `1.0`
  exact after normalization · `0.9` structural/initial-expansion (`"E. Haaland"`
  ↔ `"Erling Haaland"`) · `0.6` nickname-prefix heuristic (`"Rodri"` ⊂
  `"Rodrigo Hernandez"`). Auto-accept ≥ 0.8; 0.5–0.8 provisional (merged, both
  ids kept, flagged); < 0.5 unmatched.
- **Score conflict resolved on evidence.** The feeds disagree (2-1 vs 2-2). Each
  feed's own per-player goals sum to 2-1 — so beta's `result` contradicts beta's
  own lineup. Canonical = 2-1 with that reasoning recorded, both values kept, and
  a high-severity review item carrying all four numbers. This beats an arbitrary
  "prefer provider X".
- **Time compared as an instant, not a string.** `15:30:00Z` and
  `16:30:00+01:00` are the same moment; normalization dissolves the apparent
  conflict, so no review item is raised.
- **Stats prior:** on a per-stat disagreement the stats-specialist feed (alpha)
  is taken, both values kept, flagged.
- **Player markets depend on player mapping.** A shots-on-target market maps only
  because its player mapped; ids are resolved through the player mapping before
  markets are keyed.

## Layout

```
src/
  normalize.py   names/diacritics, fractional→decimal odds, instants, market vocab
  loaders.py     each provider's schema → one uniform intermediate
  models.py      the canonical dataclasses + serialization
  match.py       teams → players → markets, with confidence tiers
  reconcile.py   per-field conflict policies with provenance
  review.py      the human-review list
  pipeline.py    orchestration + summary
  __main__.py    CLI
tests/           pytest: normalize, match, reconcile, and an end-to-end run
```
