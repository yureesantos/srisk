# Submission notes

**Name:** _(fill in)_
**Date:** 2026-07-24
**Approx. time spent:** ~3.5 hours
**Language / key libraries:** Python 3.10, standard library only (json, dataclasses, datetime, unicodedata, fractions). Dev dependency: pytest.

## How to run

```bash
python -m src            # reads feeds/*.json → writes out/canonical.json + out/review.json, prints a summary
pip install pytest && python -m pytest   # 38 tests
```

## Key decisions (and why)

- **Flag, don't guess.** Anything below the match threshold stays `unmatched` in the output with its single source id and a review item, never force-matched; no conflict is silently dropped. This is the safe failure direction for a betting book — a wrong auto-match settles a bet against the wrong entity.
- **Confidence as documented tiers, not a fake-continuous similarity.** `1.0` exact-after-normalization, `0.9` initial-expansion (`"E. Haaland"`↔`"Erling Haaland"`), `0.6` nickname-prefix (`"Rodri"`⊂`"Rodrigo Hernandez"`). ≥0.8 matched, 0.5–0.8 provisional (merged + flagged), <0.5 unmatched. Discrete tiers say honestly how a match was made rather than implying precision the method doesn't have.
- **Score conflict (2-1 vs 2-2) resolved on evidence, not by preferring a provider.** Both feeds' own per-player goal tallies sum to 2-1, so beta's `result: 2-2` contradicts beta's own lineup. Canonical = 2-1, with the reasoning recorded and a high-severity review item carrying alpha's result, beta's result, and both tallies.
- **Kickoff compared as an instant, not a string.** `15:30Z` and `16:30+01:00` are the same moment; after normalization they agree and no review is raised. (Python 3.10's `fromisoformat` rejects `Z`, handled explicitly.)
- **Odds are quotes, not facts.** Both feeds' decimal-normalized prices are always kept side by side; a divergence (player_goals over 2.40 vs 2.50) is flagged `info`, never collapsed to one number.
- **Diacritics that resist NFKD** (`Ø`/`ø`, and the `Đ/Ł/ð` class) are mapped explicitly — the generic combining-mark strip can't reach them, which would otherwise silently break the `Ødegaard`↔`Odegaard` match.
- **Dependency-ordered matching:** teams scope players, players scope player-markets. A player prop only maps once its player mapped.

## Where this would mis-map / what it would cost downstream

- **The nickname-prefix heuristic** is the sharpest edge. False positive: two teammates whose names share a prefix ("Silva"/"Silvano") could pair at 0.6 — mitigated by keeping it *provisional* + flagged, not silently merged. False negative: a true alias with no lexical overlap (a genuine nickname or shirt name) lands in `unmatched` instead. Both directions are surfaced for review; the cost of an unreviewed wrong match is a player prop settling against the wrong player — direct monetary exposure — which is why nothing below threshold is auto-accepted.
- **Team matching leans on the home/away roles agreeing.** If a feed swapped them, the name-verification step catches it (and flags), but a feed that both swapped roles *and* used ambiguous names would need a stronger key.
- **The stats "prior" (prefer alpha) is a prior, not evidence.** Where only the shot count differs it's low-stakes, but a feed-quality regression in alpha would propagate silently for stats that both feeds carry; the flag mitigates but doesn't prevent.
- **Two-feed only.** The conflict policies (corroborate-by-tally, single prior) generalize to N feeds but weren't built for it.

## What I'd do with more time

- A curated **alias / nickname reference table** (turns the Rodri case from provisional-0.6 into a confident match, and catches zero-overlap aliases the heuristic can't).
- **Stat-line corroboration as a secondary matching signal** — Rodri's `g/sh/sot` is identical in both feeds; using that would raise its confidence honestly rather than lexically.
- A **Levenshtein / token-set fallback tier** between initial-expansion and nickname-prefix for typos and reorderings.
- **JSON-schema validation** of each input feed, so a malformed feed fails loudly at the boundary.
- **Confidence calibration** against a labelled set of known pairs, so the tiers map to real match probabilities.
- Generalize the reconciler to **N providers** with a pluggable per-field policy.

## Anything you want us to know

The two feeds are a well-designed adversarial fixture — beyond the brief's named challenges I found a fourth genuine conflict (player_goals odds 2.40 vs 2.50) and the goal-tally corroboration that makes the score resolution evidence-based rather than arbitrary. Both are handled and tested. The 10 review items the pipeline emits are the honest surface of everything it couldn't decide on its own.
