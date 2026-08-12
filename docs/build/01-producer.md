> Part of the [build plan](../BUILD-PLAN.md). Conventions (`$CH`, `$FP`) are
> defined there. Update this file with what was actually measured once the
> branch lands — the plan is corrected by results, not defended against them.

## Branch 1: `feat/producer`

**Scope.** Rate-dialled event generator: 70k–500k/min, values drawn from the
calibrated distributions already proven in `streaming/load/synthesise.sql` —
ported to Python, not re-derived. Injects settlement reversals and duplicate
deliveries at configurable shares. The dial changes emission rate only, never
data shape (DESIGN-STREAMING: a rate change must be interpretable).

**Files.**

```
streaming/producer/__main__.py     # CLI: --rate, --duration|--count, --seed,
                                   #      --reversal-share, --duplicate-share, --sink
streaming/producer/generate.py     # distributions, ported from synthesise.sql
streaming/producer/sinks.py        # stdout/file for testing; kafka per ADR-0013
streaming/producer/check_shape.py  # calibration assertions (test tool, also CI-able)
```

**Contract.** One NDJSON event per leg, the 17 export fields plus `emitted_at`
(epoch ms, becomes `version` — ADR-0007) and `event_kind`
(`placement|settlement|reversal`). Reversals carry the same identity fields, a
higher `emitted_at`, and the measured signature `ggr == turnover` (14 of 14
revised rows in the real export, ADR-0007). Distributions to reproduce, all
already calibrated in `synthesise.sql`:

| Field | Target |
|---|---|
| Uid | power 2.0 over a 200k pool → Gini 0.820 (real 0.803), median 4 legs/Uid, max/median ~530x |
| Stake | log-normal μ=2.3 σ=2.4, clipped [0.10, 500000] |
| Price | log-normal μ=0.85 σ=0.55, clipped [1.01, 250] |
| Cardinalities | competition 56 · fixture 453 · market 119 · player 2,714 · selection 6,014 · region 31 |
| Currency | EUR 88% / PEN 12% / USD <1% |
| Bet type | SIMPLE 78% / COMBINED 22% |

**Done when** all three tests below pass.

**Test 1 — the dial is honest.** At both ends of the brief's range:

```bash
python -m streaming.producer --rate 70000  --duration 60 --seed 1 --sink stdout | wc -l
# assert: 70000 ± 2%
python -m streaming.producer --rate 500000 --duration 60 --seed 1 --sink stdout > /dev/null
# assert: the producer's own stderr rate report says ≥ 500000/min sustained.
# If a single process cannot hold 8,333 ev/s despite the 32x measured headroom,
# that is a finding to record (serialisation overhead beyond json.dumps), and
# the fallback is N producer processes with disjoint seeds — not a slower dial.
```

**Test 2 — the shape survives the port.** Same checks that calibrated
`synthesise.sql`, now against the Python port:

```bash
python -m streaming.producer --count 2000000 --seed 1 \
    --reversal-share 0.02 --duplicate-share 0.01 --sink stdout \
  | python streaming/producer/check_shape.py
# check_shape.py asserts, printing each measured value next to its target:
#   turnover-per-Uid Gini in [0.78, 0.86]        (target 0.820, real 0.803)
#   median legs per Uid == 4
#   currency shares EUR 0.88 ± 0.01, PEN 0.12 ± 0.01
#   distinct competitions ≤ 56, markets ≤ 119, fixtures ≤ 453 (pool bounds)
#   reversal share 0.02 ± 0.002, and every reversal has ggr == turnover
#   duplicate share 0.01 ± 0.002 (byte-identical event pairs)
# Gini via betflow.src.betflow.gini_lorenz — the same code the oracle uses.
```

**Test 3 — determinism.** Two runs with the same seed are byte-identical
(this is what makes every downstream replay test meaningful):

```bash
python -m streaming.producer --count 100000 --seed 7 --sink stdout | shasum
# run twice; assert identical digest
```

---

---

## Risk

**Producer — the port drifts from the calibration.** The SQL and Python RNG
paths differ (cityHash64-derived uniforms vs Python's), so constants that
produced Gini 0.820 in SQL may land elsewhere in Python. That is why
`check_shape.py` asserts ranges, not equality. Fallback: recalibrate the two
free parameters (uid exponent, stake σ) against the check — an hour, not a
redesign. Second risk: a single process misses 8,333 ev/s despite the measured
headroom (the 267k ev/s figure excludes transport writes). Fallback: N
processes, disjoint seeds; the dial semantics do not change.
