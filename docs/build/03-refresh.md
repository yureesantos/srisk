> Part of the [build plan](../BUILD-PLAN.md). Conventions (`$CH`, `$FP`) are
> defined there. Update this file with what was actually measured once the
> branch lands — the plan is corrected by results, not defended against them.

## Branch 3: `feat/refresh`

**Scope.** The sweep: collapse, aggregate, publish, per class (ADR-0009).
Class 1/2 metrics come from **one single-pass SQL aggregate** over
`betslip_leg_current` (0.93 s vs 6.06 s measured — `GROUPING SETS` over the
seven breakdown dimensions, one scan). Class 3 (Gini/Lorenz, anomalies, sharp)
pulls the collapsed window slice into pandas and calls the existing
`betflow/src` code **unchanged**: `gini_lorenz()` on the per-Uid turnover
vector, `prices.analyse` → `sharp.analyse` on the window's legs. Reused, not
reimplemented — the whole point of the oracle is that both paths run the same
statistics.

Each artifact carries the DESIGN-STREAMING envelope: `payload_hash` (same
canonicalisation as `pipeline.py:_build_meta` — `json.dumps(sort_keys=True)`,
timestamp excluded), `watermark` = `max(version)` the sweep saw, `window` where
applicable.

**Files.**

```
streaming/refresh/__main__.py      # --once | --loop, --classes, --out
streaming/refresh/sweep.py         # single-pass SQL, class scheduling
streaming/refresh/publish.py       # envelope, hash, watermark, atomic write
streaming/refresh/compare_oracle.py  # the test below
```

**Done when the artifact matches the batch pipeline's over the same input.**
The batch pipeline is the oracle: same input, same numbers, or one of them is
wrong.

**Test 1 — the oracle.** Run against ONE export file, not both: the two files
overlap and disagree on 14 rows (ADR-0007), and the batch pipeline's
union/dedup semantics over that overlap are not the merge contract — comparing
over a single file removes the ambiguity instead of arguing about it.

```bash
mkdir -p /tmp/oracle_raw && cp data/raw/excel_BillingByBetslips-24062026_051729.xlsx /tmp/oracle_raw/
cd betflow && python -m src.pipeline --raw-dir /tmp/oracle_raw \
    --out /tmp/oracle_out --frontend /tmp/oracle_payload.json && cd ..
# oracle artifacts now in /tmp/oracle_out/artifacts (batch reference: 8.4s / 113k rows)

curl -s "$CH" --data-binary 'TRUNCATE TABLE srisk.betslip_leg'
python streaming/tools/export_to_events.py /tmp/oracle_raw/*.xlsx > /tmp/export.ndjson
python -m streaming.consumer --source /tmp/export.ndjson
python -m streaming.refresh --once --classes all --out /tmp/streaming_out/artifacts

python streaming/refresh/compare_oracle.py \
    --batch /tmp/oracle_out/artifacts --streaming /tmp/streaming_out/artifacts
# Asserts, section by section, printing every divergence:
#   counts (legs, betslips, per-breakdown rows): exact
#   money (turnover, ggr, per currency):         exact to the cent
#   concentration (Gini, Lorenz points):         exact (same gini_lorenz code)
#   sharp (flagged set, p-values, wilson_lb):    identical flagged Uids; floats ≤ 1e-9
# Expected outcome: exact equality where the same code ran, and the compare
# script names any section where SQL aggregation replaced pandas — that list
# is the review surface for this branch, not a footnote.
```

**Test 2 — replay determinism** (ADR-0009's guarantee made real): run
`refresh --once` twice against the unchanged table; assert both runs produce
the same `payload_hash` and the same `watermark`. Then re-ingest
`/tmp/export.ndjson` and refresh again: hash still identical (idempotent
ingest ⇒ identical artifact).

**Test 3 — cost at target volume.** Re-synthesise 20M rows
(`streaming/load/synthesise.sql`, params `rows=20000000, uid_pool=200000`),
then:

```bash
time python -m streaming.refresh --once --classes 1
# The SQL single pass is measured at 0.93s; the tick end-to-end (query + envelope
# + hash + write) is EXPECTED under 2s and is UNMEASURED until this runs.
# Whatever it is, it gets recorded — it either fits the 1–5s Class 1 cadence
# (ADR-0009) or the cadence table gets a measured correction, ADR-0012 style.
```

Class 3 at 20M is window-bounded by construction; the cost of pulling one
window's slice into pandas is unmeasured and gets measured here too.

---

---

## Risk

**Refresh — the oracle disagrees.** The most likely divergence is leg→betslip
reconstruction: the batch pipeline builds betslips in pandas
(`_betslip_frame`), and reproducing that grain in SQL for turnover-by-currency
is the subtlest translation in the plan. Fallback, in order: pull the
collapsed frame into pandas and run the batch code path wholesale (correct by
construction, slow — acceptable for the oracle test, temporary for the tick),
then move aggregates to SQL one at a time with the compare script pinpointing
each divergence. The oracle makes this a bisection, not a debugging session.
Second: sharp/prices need columns the schema does not carry (normalised
market, resolved player). If the adapter cannot supply them losslessly, the
oracle comparison narrows to the sections that can be compared exactly, and
the narrowed scope is stated in the compare output rather than glossed.
