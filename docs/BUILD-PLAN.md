# Build plan

The executable expansion of DESIGN-STREAMING.md's build order. The design says
*what* each step is; this says which files, which commands prove it, and what
"done" means. Nothing here revisits a decision — where a decision is still open
it is flagged as open, once, below.

Conventions used throughout:

```bash
# ClickHouse HTTP endpoint (docker-compose maps 8123 -> 18123; ADR-0008 stack)
CH='http://localhost:18123/?user=srisk&password=srisk&database=srisk'

# Order-independent fingerprint of the collapsed table — the comparison
# primitive for every replay test. sum() over per-row hashes is commutative,
# so insertion order cannot affect it.
FP="SELECT count() AS rows,
           sum(cityHash64(row_key, version, turnover, ggr, net_revenue)) AS fp
    FROM srisk.betslip_leg FINAL"
```

---

## Where this stands

**Done and measured** (step 1, `feat/clickhouse-schema`; ADR-0012):

- ClickHouse up under compose, 2 CPUs / 4 GB, DDL applied
  (`streaming/schema/001_betslip_leg.sql`, `002_current_view.sql`).
- 20M calibrated rows synthesised server-side (`streaming/load/synthesise.sql`):
  Gini 0.820 against a measured 0.803, median 4 legs/Uid, cardinalities exact.
- Collapse is `FINAL`, never `argMax GROUP BY row_key` — the latter dies with
  MEMORY_LIMIT_EXCEEDED at 20M identities.
- One breakdown over 20M rows: 0.29 s compacted, 0.82 s over 5 parts. Seven
  breakdowns: 6.06 s as separate scans, **0.93 s as a single pass** — the
  refresh job issues one pass, this is settled.
- Per-event Python cost: canonicalise+hash 902k ev/s, `json.dumps` 267k ev/s,
  against a required 8,333 ev/s (500k/min). Per-event work is not the
  bottleneck; contention inside Docker's 4-CPU / 8.3 GB allocation is the
  expected one.
- Storage 1.16 GiB for 20M rows; `max_threads` saturates at 2 (container limit).

**Remaining**: five branches, in dependency order —
`feat/producer` → `feat/consumer` → `feat/refresh` → `feat/api-cache` →
`feat/load-harness`. The batch pipeline (`betflow/src`) is the correctness
oracle and is not modified except for the dashboard's operations panel.

**Time**: under 24 hours remain. Honest estimates — producer ~3 h, consumer
~3 h, refresh ~5 h, api-cache ~5 h, harness ~3 h — sum to more than will fit
once anything goes wrong, and something will. The cut order at the end is part
of the plan, not a contingency. Producer + consumer + refresh alone is a
defensible submission: data in, metrics out, correctness proven against the
oracle. Everything after that strengthens the answer; nothing after that
rescues it if the oracle comparison fails.

**Tooling gaps on the target machine**, checked today: `k6` is not installed
(`brew install k6`, needed by branch 4) and no ClickHouse Python client is
installed — the consumer uses the HTTP interface with the standard library, so
no new dependency is required.

---

## Open decision: a log between producer and consumer

Not settled, and deliberately so — this is the one decision the plan flags for
a human rather than makes. The rate does not require a log: 8,333 ev/s is 32x
inside the measured `json.dumps` budget on one core. What a log buys is the
**demo**: consumer lag as a first-class observable (consumer-group offsets) and
live consumer rescale (partition rebalance) — which is literally steps 3–5 of
the scaling demo in DESIGN-STREAMING.md.

| | With Redpanda | Without (direct socket/pipe) |
|---|---|---|
| Consumer lag | Read from the broker, trustworthy | Synthesised by the consumer from its own queue depth — self-reported |
| Scale consumers live | `docker compose up -d --scale consumer=3`, rebalance is automatic | Restart the consumer with more workers; the "live" in "scale live" weakens |
| Replay-to-watermark (ADR-0009) | Retention gives it directly | Requires the producer to persist its output stream anyway |
| Cost | One more container from the 4-CPU / 8.3 GB budget (~0.5 CPU, ~1 GB); one more thing that can be misconfigured | Bespoke lag accounting and a weaker demo |

**Decide before `feat/consumer` starts** — the consumer's input interface is
the first thing it touches. `feat/producer` is not blocked either way: the
producer writes to a sink interface (`stdout` NDJSON, file, or Kafka-protocol),
and every producer test below runs against the file sink.

---

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
streaming/producer/sinks.py        # stdout/file now; kafka if the log decision lands
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

## Branch 2: `feat/consumer`

**Scope.** Reads events from a source (file now; log if decided), canonicalises
into the ADR-0007 identity, hashes it, stamps `version = emitted_at`, and
batch-inserts. It does not aggregate, deduplicate, or interpret — supersedence
belongs to the engine (ADR-0007/0008/0012). Two tuning knobs, both reported:
`--batch-size` (default 10,000) and `--flush-ms` (default 500).

**Files.**

```
streaming/consumer/__main__.py     # CLI: --source, --batch-size, --flush-ms
streaming/consumer/canonical.py    # identity tuple -> row_key
streaming/consumer/insert.py       # batched INSERT ... FORMAT JSONEachRow over CH HTTP
streaming/tools/export_to_events.py  # xlsx export -> NDJSON events (oracle adapter;
                                     # emitted_at from the filename's HHMMSS, ADR-0007)
```

**Contract.** `row_key` = first 8 bytes of BLAKE2b over the canonical
serialisation of `(Uid, betslip timestamp, BetType, MatchId, Market, Player,
Option, Price)` — the ADR-0007 key, the measured 902k ev/s path. Note the
digest differs from `synthesise.sql`'s stand-in `cityHash64` by design; the two
populations never mix (synthesised data is truncated before consumer tests).
Inserts are append-only `INSERT`, never `UPDATE`. At-least-once and
out-of-order input are assumed, not tolerated (DESIGN-STREAMING: log→consumer).

**Done when replaying the same input twice leaves the collapsed table
identical** — idempotency tested, not assumed — and out-of-order replay
converges to the same state.

**Test 1 — idempotent replay.**

```bash
curl -s "$CH" --data-binary 'TRUNCATE TABLE srisk.betslip_leg'
python -m streaming.producer --count 500000 --seed 42 \
    --reversal-share 0.02 --duplicate-share 0.01 --sink stdout > /tmp/fixture.ndjson
python -m streaming.consumer --source /tmp/fixture.ndjson
curl -s "$CH" --data-binary "$FP"          # -> R1
python -m streaming.consumer --source /tmp/fixture.ndjson   # replay, no truncate
curl -s "$CH" --data-binary "$FP"          # -> R2
# assert R1 == R2, including the row count: the second pass changed nothing.
```

**Test 2 — order independence** (ADR-0007: version wins, never arrival order):

```bash
curl -s "$CH" --data-binary 'TRUNCATE TABLE srisk.betslip_leg'
python -c "import random,sys; l=open('/tmp/fixture.ndjson').readlines(); \
           random.seed(0); random.shuffle(l); sys.stdout.writelines(l)" > /tmp/shuffled.ndjson
python -m streaming.consumer --source /tmp/shuffled.ndjson
curl -s "$CH" --data-binary "$FP"
# assert: equals R1. Same events, different order, same collapsed state.
```

**Test 3 — supersedence on a single identity** (the ADR-0012 row-level check):

```bash
curl -s "$CH" --data-binary "
  SELECT row_key, count() FROM srisk.betslip_leg
  GROUP BY row_key HAVING count() > 1 LIMIT 1"          # any reversed identity
curl -s "$CH" --data-binary "
  SELECT ggr, turnover FROM srisk.betslip_leg FINAL WHERE row_key = <key>"
# assert: one row, and ggr == turnover — the reversal (highest version) won.
```

**Test 4 — throughput, measured not assumed.** `--source /tmp/fixture.ndjson`
with timing: assert sustained ≥ 8,333 ev/s end-to-end (parse → hash → insert).
Expected comfortably; if not, the batch size is the first knob and the finding
gets recorded either way. Watch part count while doing it: many small inserts
create many parts, and `FINAL` over 5 parts already costs 2.8x (ADR-0012).

---

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

## Branch 4: `feat/api-cache`

**Scope.** Three pieces. (1) A minimal artifact API — stdlib
`ThreadingHTTPServer`, no framework: `GET /artifact/<class>` returns the
current file with the per-class `Cache-Control` from ADR-0011, plus
`GET /artifact/ops` for the operations feed. It computes nothing (ADR-0011:
the cache is fanning out one artifact, not protecting a computation). (2)
Varnish in front, VCL with coalescing left on and BAN on window close, issued
by the refresh job. (3) The dashboard's **operations panel**: ingest rate,
consumer lag, refresh duration p50/p99, per-layer age and watermark — the
footer region, which already carries the guarantee (ADR-0009).

**Files.**

```
streaming/api/server.py            # artifact serving + Cache-Control map
streaming/api/default.vcl          # TTL per class, BAN handling, coalescing default
streaming/docker-compose.yml       # + varnish (proposed: 0.25 CPU / 256M), + api
betflow/dashboard/src/components/OpsPanel.tsx
betflow/dashboard/src/lib/useArtifact.ts   # polling fetch, per-class interval
streaming/load/k6_readers.js       # the 100-reader simulation
```

Cache policy is ADR-0011 verbatim: Class 1 `max-age=2,
stale-while-revalidate=5`; Class 2 `max-age=30`; Class 3 `max-age=300` + BAN
on window close. The dashboard change is additive — the batch payload import
stays; streaming mode fetches. The panel is also the first thing cut (below),
so it lands last within this branch.

**Done when 100 concurrent readers show a measured hit rate and a backend
request count that proves coalescing** — roughly one backend fetch per TTL
period per class, not one per reader.

**Test 1 — headers are right before load is applied.**

```bash
curl -sD - -o /dev/null http://localhost:8088/artifact/flow | grep -i cache-control
# assert: max-age=2, stale-while-revalidate=5   (API direct, class 1)
curl -sD - -o /dev/null http://localhost:8081/artifact/flow   # via Varnish
curl -sD - -o /dev/null http://localhost:8081/artifact/flow | grep -i '^age'
# assert: second request within the TTL carries Age > 0 — served from cache.
```

**Test 2 — 100 readers** (the brief's number, measured):

```bash
brew install k6   # not currently installed
docker exec srisk-varnish varnishstat -1 | egrep 'MAIN.(cache_hit|cache_miss|backend_req)'  # baseline
k6 run streaming/load/k6_readers.js
# 100 VUs, constant, 60s, each looping GETs across all artifact classes.
# Declared thresholds (k6 fails the run if violated): http_req_failed == 0,
# p(95) < 100ms. JSON summary written to streaming/load/results/ as evidence.
docker exec srisk-varnish varnishstat -1 | egrep 'MAIN.(cache_hit|cache_miss|backend_req)'
# The assertion that answers the brief: over 60s, backend_req delta ≈
#   flow-class artifacts: 60/2s TTL ≈ 30 fetches; class 2: 2; class 3: ≤ 1
# against tens of thousands of client requests. If backend_req scales with
# readers instead of with TTL periods, coalescing is not working and the
# branch is not done. Expected hit rate > 99%; that number is UNMEASURED
# until this runs, and whatever it is goes in the record.
```

**Test 3 — BAN on window close** (ADR-0011's event-driven invalidation):

```bash
curl -s http://localhost:8081/artifact/concentration | python -c \
  "import json,sys; print(json.load(sys.stdin)['payload_hash'])"   # H_old, cached
# refresh job closes a window -> publishes + BANs; simulate by hand first:
curl -s -X BAN http://localhost:8081/artifact/concentration
curl -sD - http://localhost:8081/artifact/concentration | grep -i '^age'
# assert: Age: 0 (refetched, not served stale) and payload_hash != H_old
# after a republish. Then the same assertion driven by the refresh job itself.
```

---

## Branch 5: `feat/load-harness`

**Scope.** The live demo, scripted so it is reproducible: step the rate
through the DESIGN-STREAMING schedule, sample the operations feed throughout,
write one JSON record per run. The dashboard is the demonstration; the JSON is
the evidence.

**Files.**

```
streaming/load/harness.py          # rate schedule, sampling, record writing
streaming/load/results/            # one JSON per run (committed)
```

**The run:**

```bash
python -m streaming.load.harness \
  --plan baseline:70000:120,ceiling:500000:300,past:1000000:300,hold:1000000:180 \
  --record streaming/load/results/run-$(date +%s).json
# Record fields: per step — target rate, achieved rate, lag series (events and
# seconds), refresh p50/p99 per class, part count, artifact hashes, and a
# varnishstat snapshot if branch 4 landed.
```

Then the live part, which depends on the log decision: with Redpanda,
`docker compose up -d --scale consumer=3` mid-hold and the record shows lag
draining; without it, the consumer restarts with more workers and the record
shows the same drain with a gap — stated plainly in the record, not smoothed
over. The step past the brief's ceiling is the point: find where it degrades
on this machine, name the saturated component from the panel (expected: CPU
contention inside the 4-CPU allocation or the ClickHouse insert path — both
are expectations, not measurements, and the first prediction in this project
was two orders of magnitude off), and remove it live. Scaling consumers
mid-flight is only safe because ingestion is idempotent — branch 2's tests are
what make step 5 of the demo honest (ADR-0007).

**Done when** the record exists with every field populated, the ceiling on
this machine is a measured number with a named cause, and — where degradation
was reached — the drain after scaling is in the lag series.

**Sequencing note.** A reduced harness (rate schedule + lag/refresh sampling,
no Varnish figures, panel optional) only needs branches 1–3. If branch 4 is at
risk, the harness runs against the refresh job's own metrics rather than
waiting — measurement never waits on presentation.

---

## End-to-end verification

Once producer, consumer and refresh have landed (branches 4–5 extend this,
they do not gate it):

```bash
docker compose -f streaming/docker-compose.yml up -d --wait
curl -s "$CH" --data-binary 'TRUNCATE TABLE srisk.betslip_leg'

# 1. Correctness before volume: the oracle chain (branch 3, test 1) end to end.
#    This is the whole system exercised on real data with a known answer.

# 2. Volume: producer at the brief's floor for 10 minutes, live chain.
python -m streaming.producer --rate 70000 --duration 600 --seed 3 \
    --reversal-share 0.02 --duplicate-share 0.01 --sink <decided transport> &
python -m streaming.consumer --source <decided transport> &
python -m streaming.refresh --loop &
# assert while running: watermark advances every Class-1 tick; collapsed row
# count grows at ~1,150/s (70k/min minus the duplicate share); lag stays flat.

# 3. Convergence: stop the producer, wait one Class-2 tick, then
curl -s "$CH" --data-binary "$FP"    # -> F1
python -m streaming.refresh --once   # -> hash H1
python -m streaming.refresh --once   # -> hash H2; assert H1 == H2
# The stream stopped, so the artifact must be a fixed point.

# 4. Readers (requires branch 4): k6 run during step 2, not after it —
#    100 readers against a table under live ingest is the brief's actual
#    scenario. Same assertions as branch 4 test 2.
```

Plus one destructive check worth 30 seconds: `docker restart
srisk-clickhouse` mid-ingest, assert the consumer reconnects and the
fingerprint after re-delivery equals a clean run's — at-least-once plus
idempotency surviving a real failure, not a simulated one.

---

## Cut order

Fixed in DESIGN-STREAMING and repeated here so nobody re-decides it at hour
20: first the **dashboard operations panel** goes (the harness JSON and
`varnishstat` carry the same numbers without the rendering), then **Varnish**
(the API's `Cache-Control` headers still state the policy; coalescing goes
unmeasured and is said so), then the **API itself** (artifacts are files on
disk; k6 is dropped). **Measurement never gets cut** — a smaller system with
measured behaviour beats a complete system with claimed behaviour, and the
exercise's real question is answered by the numbers, not the surface area.

What each floor still defends:

| Shipped | What it proves | What it concedes |
|---|---|---|
| 1–3 (producer, consumer, refresh) | Data in at rate, metrics out, correctness against the oracle, idempotent replay | Reader-side answer stays on ADR-0011's reasoning plus the step-1 measurements, unexercised |
| 1–3 + API | Serving path exists; per-class TTL stated in headers | Coalescing and hit rate unmeasured |
| 1–4 | The full brief except the staged demo | The scaling story is measured (harness-lite) but not performed |
| 1–5 | Everything | Nothing — this is the plan, not the expectation |

---

## Risks

Per branch: the most likely failure, and the fallback that keeps the branch
shippable.

**Producer — the port drifts from the calibration.** The SQL and Python RNG
paths differ (cityHash64-derived uniforms vs Python's), so constants that
produced Gini 0.820 in SQL may land elsewhere in Python. That is why
`check_shape.py` asserts ranges, not equality. Fallback: recalibrate the two
free parameters (uid exponent, stake σ) against the check — an hour, not a
redesign. Second risk: a single process misses 8,333 ev/s despite the measured
headroom (the 267k ev/s figure excludes transport writes). Fallback: N
processes, disjoint seeds; the dial semantics do not change.

**Consumer — parts, not throughput.** The measured risk is not event cost but
insert cadence: small frequent batches multiply parts, and `FINAL` over 5
parts already costs 2.8x (ADR-0012), so an over-eager flush interval degrades
the *refresh* path, not the ingest path — a coupling that would be easy to
misattribute. Fallback: larger batches, and `OPTIMIZE TABLE … FINAL` on
sealed partitions as routine operation (already promoted by ADR-0012).
Second: a canonicalisation mismatch (Decimal formatting, timestamp precision)
that makes replayed events hash differently — caught immediately by branch 2
test 1, which is why it is the branch's done criterion.

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

**API/cache — VCL wrong in a way that is invisible until it is not**
(ADR-0011 names this). A miswritten BAN or TTL serves stale data with a
confident face. Mitigation is branch 4 test 3 exercising the BAN end to end
before the demo depends on it; fallback per the cut order — TTL-only policy,
coalescing still measured, event invalidation conceded in writing. Second:
k6 plus 100 readers plus ingest inside the same 4-CPU Docker budget contends
with the thing being measured. Run k6 from the host (it is a host binary, not
a container), and record CPU allocation alongside every figure.

**Harness — nothing degrades.** With 32–108x per-event headroom, even 1M/min
may not produce visible lag, leaving the demo without its third act. Fallback:
keep raising the dial (the producer is not the bottleneck) until Docker's CPU
budget binds — the ceiling exists, it is just higher than the brief; a
measured "this machine saturates at X" is a stronger answer than a staged
failure. Inverse risk: ClickHouse degrades non-recoverably under the burst
(part explosion, delayed merges) and the drain never comes. Fallback: the
record keeps the degradation series — a measured failure mode with a named
cause is presentable; an unmeasured success is not.
