> Part of the [build plan](../BUILD-PLAN.md). Conventions (`$CH`, `$FP`) are
> defined there. Update this file with what was actually measured once the
> branch lands — the plan is corrected by results, not defended against them.

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

## The transport is now real (branch 6, `feat/kafka-transport`)

Everything above describes the file-sink path, which is still how every
correctness test runs — no broker required. What changed is that the Kafka path
in ADR-0013 went from written-but-never-executed to measured. Results:
`streaming/results/06-kafka.md`.

**Stack.** `streaming/docker-compose.yml` gains `kafka` (apache/kafka:3.8.0,
KRaft, no ZooKeeper, 1 CPU / 1.5 GB, 1 GB heap) and `akhq` (the operations UI, on
:18080). Topic `betslips`, **6 partitions**, keyed on `uid`. Six because the
count caps consumer parallelism (ADR-0010) and cannot be raised at runtime, and 6
divides evenly by 1, 2, 3 and 6 — every step of the scaling demo rebalances into
equal shares. Per-Uid partition affinity is verified rather than assumed: 4,965
Uids over 50,000 events, **zero split across partitions**.

**The consumer commits after inserting, never before.** `iter_kafka` became the
`KafkaSource` class, because the commit point is not inside the iteration — it is
after the caller's insert returns, and a generator cannot know when that
happened. The previous code committed at yield time, which acknowledged events
still sitting in a Python list. A crash in that window lost them.

**A third source of ticks.** `KafkaSource` yields `None` on an idle poll so the
`--flush-ms` deadline is evaluated even when nothing is arriving. Without it a
batch smaller than `--batch-size` that stops growing is never inserted and never
committed — a stall that reads exactly like a consumer bug on the lag graph. It
was found by measurement, not by review.

**The consumer no longer requires pandas.** It imports `normalise_market` from
`betflow/src/load.py` (ADR-0004), and that module imports pandas at module level.
Rather than install the batch analytics stack into every consumer replica, the
import falls back to executing that file's pandas-free prelude, with the split
point asserted so a future edit fails loudly. Both paths agree on all tested
cases.

**Test 5 — throughput through the broker.** `streaming/load/kafka_test.sh`.
Producer sustained **8,591 ev/s**, identical to the fifo baseline in
`05-concurrent.md`: at the brief's ceiling the transport costs nothing
measurable. Broker ceiling measured separately at **34,324 ev/s** (4.1x the
requirement), rising to 53,680 ev/s before the broker's 1 CPU saturates.

**Test 6 — lag as a broker-owned observable.** `streaming/load/kafka_lag.sh`
reads `kafka-consumer-groups --describe`. Nothing asks the consumer for its own
backlog.

**Test 7 — live rescale, and the honest caveat.**
`streaming/load/kafka_rescale.sh`. **At the brief's rate this demo cannot be
made, and that is the finding:** one consumer sustains ~31,600 ev/s, 3.8x the
requirement, so lag never accumulates and adding consumers changes nothing
visible. The producer is therefore driven to 6.4x the ceiling to saturate one
consumer. Lag then rises to 1.79M, `--scale consumer=3` rebalances the partitions
two-per-replica with the producer still running, and lag drains to 0. The
mechanism is proven; the need for it at 500k/min is not.

**Test 8 — idempotency across a `SIGKILL`.**
`streaming/load/kafka_restart.sh`. Kill the consumer mid-stream, restart it,
drain, then reset offsets to earliest and replay the entire log into the table
that already holds it. The fingerprint is unchanged — which is the ADR-0007
contract, and the reason commit-after-insert is safe rather than merely careful.

---

## Risk

**Consumer — parts, not throughput.** The measured risk is not event cost but
insert cadence: small frequent batches multiply parts, and `FINAL` over 5
parts already costs 2.8x (ADR-0012), so an over-eager flush interval degrades
the *refresh* path, not the ingest path — a coupling that would be easy to
misattribute. Fallback: larger batches, and `OPTIMIZE TABLE … FINAL` on
sealed partitions as routine operation (already promoted by ADR-0012).
Second: a canonicalisation mismatch (Decimal formatting, timestamp precision)
that makes replayed events hash differently — caught immediately by branch 2
test 1, which is why it is the branch's done criterion.
