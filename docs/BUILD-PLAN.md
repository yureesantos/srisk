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

## The five branches

Each branch has its own record, written to be read on its own and updated with
measurements once it lands.

| # | Branch | Plan | Done when |
|---|---|---|---|
| 1 | `feat/producer` | [01-producer.md](build/01-producer.md) | Dial honest at 70k and 500k; shape matches the calibration |
| 2 | `feat/consumer` | [02-consumer.md](build/02-consumer.md) | Replaying the same input twice leaves the table identical |
| 3 | `feat/refresh` | [03-refresh.md](build/03-refresh.md) | Artifact matches the batch pipeline over the same input |
| 4 | `feat/api-cache` | [04-api-cache.md](build/04-api-cache.md) | 100 concurrent readers, hit rate and backend fetches measured |
| 5 | `feat/load-harness` | [05-load-harness.md](build/05-load-harness.md) | Rate raised to degradation, bottleneck named, consumers scaled live |

Confidence is not uniform across them. Branches 1 and 2 are firm: they depend
only on what is already measured. **Branches 3 to 5 are intent, not
specification** — each depends on what the previous one reveals, and the
ClickHouse measurement in ADR-0012 is the standing evidence that a plan written
before measuring can be wrong in its central recommendation. Expect them to be
corrected.

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

