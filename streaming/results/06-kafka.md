# Branch 6 — Kafka as the transport, measured

Raw results for `docs/build/02-consumer.md`. Reproduce with the commands shown.

ADR-0013 chose Kafka on three grounds, none of them throughput: observable
consumer lag, adding consumers without a restart, and replay to a watermark.
This file tests all three, and the headline is that **the first and third work as
claimed, while the second needed the load pushed to 6x the brief's ceiling before
it demonstrated anything** — because one consumer is nowhere near saturated at
the rate the brief actually asks for.

## Setup

```
kafka        1 CPU / 1.5 GB    apache/kafka:3.8.0, KRaft (no ZooKeeper), 1 GB heap
akhq         0.5 CPU / 512 MB  operations UI on :18080
clickhouse   2 CPU / 4 GB      unchanged from earlier branches
consumer     0.5 CPU / 512 MB  per replica, containerised only so it can scale
```

Docker total is 4 CPUs / 8.3 GB, shared with ClickHouse, Varnish and the API.
The broker is deliberately the modest allocation: the rate does not need a log,
so the log does not get the budget.

Client library: `confluent-kafka` 2.15.0. The arm64 wheel bundles librdkafka, so
no system package and no fallback to `kafka-python-ng` was needed.

```
$ pip install confluent-kafka
Successfully installed confluent-kafka-2.15.0
```

## Topic

```
$ docker exec srisk-kafka /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:9092 --create \
    --topic betslips --partitions 6 --replication-factor 1
Created topic betslips.
```

**Six partitions.** The count is the ceiling on consumer parallelism (ADR-0010)
and cannot be raised at runtime without repartitioning, so it is chosen up front.
Six because the scaling demo goes to three consumers and 6 divides evenly by 1,
2, 3 and 6 — every step of that demo rebalances into equal shares rather than a
skewed one. More than 6 would buy parallelism a 4-CPU machine cannot execute.

### Partitioning by `hash(uid)` — verified, not assumed

ADR-0013 requires all of one customer's activity in one partition, because the
sharp-behaviour and repeat-backing analyses group by Uid and need per-Uid
ordering. `confluent-kafka` hashes the message key (murmur2) to pick the
partition, and the producer sets `key = uid`. Checked over 50,000 events:

```
events read      : 50,000
distinct uids    : 4,965
uids split across: 0 partitions  <- must be 0
per-partition    : {0: 7743, 1: 8432, 2: 7580, 3: 8189, 4: 8379, 5: 9677}
```

Zero Uids split across partitions. The spread (7,580–9,677) is uneven because the
Uid pool is deliberately skewed, which is the point: partition balance follows
customer distribution, not a round robin.

## 1. Throughput, against the fifo baseline

```
$ streaming/load/kafka_test.sh 500000 60
```

| | fifo baseline (05) | **through Kafka** |
|---|---|---|
| producer sustained | 8,591 ev/s | **8,591 ev/s** (515,434/min) |
| events | — | 515,483 in 60.0s |
| consumer drained | 8,591 ev/s | all 515,483, lag → 0 |
| rows after collapse | — | 372,861 |
| insert retries | — | **0** |

**Inserting a broker into the path cost nothing measurable at the brief's
ceiling.** The producer hit the same 8,591 ev/s it hit writing to a fifo — the
dial is the constraint, not the transport. That is the expected result given
ADR-0013's measurement (per-event work is 32–108x the required rate) and it is
worth stating plainly: the log is not slowing anything down, and it is also not
speeding anything up.

Where the broker's real ceiling sits, measured separately by removing the dial:

```
$ python -m streaming.producer --count 3000000 --rate 2000000 --sink kafka ...
[producer] done: 3,000,018 events in 87.4s = 34,324 ev/s (2,059,436/min)
```

**34,324 ev/s to the broker — 4.1x the brief's 8,333 ev/s requirement.** Pushed
harder still, the producer reached 53,680 ev/s, at which point `docker stats`
shows the broker pinned at its limit:

```
srisk-kafka   104.53%   709.7MiB / 1.5GiB
```

So the binding constraint at extreme rates is the 1 CPU allocated to Kafka, not
the design. That is a budget decision, and it is reversible.

## 2. Consumer lag, read from the broker

Lag here is `log-end-offset − committed-offset`, taken from
`kafka-consumer-groups --describe`. Nothing asks the consumer for its own
backlog — that is the ADR-0013 argument, and `streaming/load/kafka_lag.sh` is it
made operational.

At the brief's ceiling with one consumer, lag oscillates and never grows:

```
 elapsed     committed       log-end         LAG   members
      6s         26626         35651        9025         1
     23s        166651        176156        9505         1
     32s        254082        255288        1206         1
     54s        445412        447987        2575         1
     63s        506584        515483        8899         1
```

This is the healthy regime of ADR-0010: lag bounded by the batch size (20,000),
sawtoothing as each batch commits, with no upward trend. **It is also the reason
the scaling demo below had to abandon the brief's rate** — a flat lag line means
adding consumers demonstrates nothing.

## 3. Live rescale — the finding is that the brief's rate cannot show it

**One consumer sustains ~31,600 ev/s**, which is 3.8x the brief's requirement.
The first attempt at this demo produced a 3M-event backlog and started one
consumer to drain it; it drained faster than a 3-second sampling loop could
observe. A demo built on that would be theatre.

So the producer is driven to **53,680 ev/s — 6.4x the brief's ceiling** —
deliberately, to saturate one consumer and make lag rise. What the run proves is
the *mechanism*, not that the brief's rate needs it:

```
$ streaming/load/kafka_rescale.sh 3600000 90
```

```
 elapsed         LAG   members  event
     19s     1086193         1
     24s     1220761         1
     28s     1376867         1
     35s     1561488         1  <-- scaled to 3, no restart of anything else
     41s     1790698         0        <- rebalance in progress: partitions revoked
     47s     1768344         3        <- three members, lag stops growing
     53s     1709639         3
     74s     1653253         3
     94s     1252302         3
    100s      946247         3
    108s      479845         3
    114s      120117         3
    119s           0         3
lag drained to 0
```

The scale command, run while the producer was still emitting:

```
$ docker compose --profile scale up -d --scale consumer=3 consumer
```

| | before scale (35s) | after rebalance (47s) | end (119s) |
|---|---|---|---|
| members | 1 | **3** | 3 |
| lag | 1,561,488 | 1,768,344 | **0** |
| trend | rising ~45k/s | flat, then falling | drained |

Final assignment — two partitions each, which is why 6 was chosen:

```
PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG  CONSUMER-ID
0          790979          790979          0    rdkafka-011acf27...
1          808706          808706          0    rdkafka-011acf27...
4          805553          805553          0    rdkafka-bdb1d735...
5          829756          829756          0    rdkafka-bdb1d735...
2          797486          797486          0    rdkafka-7488e148...
3          799903          799903          0    rdkafka-7488e148...
```

Three things to read out of this. **The rebalance is visible as `members 1 → 0 →
3`** at 41s: the group briefly has no members while partitions are revoked and
reassigned, which is the cost of a rebalance and is worth knowing about rather
than hiding. **Lag keeps rising for ~12s after the scale command** — new replicas
must start, install the client and join the group, so scaling is not
instantaneous and a runbook should not promise that it is. **Nothing was
restarted**: the producer ran throughout, and replica 1 was never recreated.

## 4. Idempotency across a restart

The consumer commits offsets only after a batch is inserted, so a crash replays
the uncommitted batch. That is safe because ingestion is idempotent (ADR-0007).
Tested by `SIGKILL` — no chance to flush, commit or run a handler:

```
$ streaming/load/kafka_restart.sh 1500000
```

```
── filling the log ───────────────────────────────────────
[producer] done: 1,500,016 events in 29.2s = 51,453 ev/s (3,087,200/min)

── consumer, killed mid-stream ───────────────────────────
killed -9 after 12s (SIGKILL: no chance to flush or commit)
rows at kill: 368706
lag at kill:
  committed 440000 / log-end 1500016 / LAG 1060016

── restart, drain to the end ─────────────────────────────
[consumer] done: 492,503 rows in 33.6s = 14,665 ev/s | 28 batches | 0 retries | parts 6
fingerprint after restart : 1455589	14563765890659912731

── full replay from offset 0, into the same table ────────
committed offset after reset: 0  (must be 0 for the replay to mean anything)
[consumer] done: 1,500,016 rows in 56.2s = 26,685 ev/s | 77 batches | 0 retries | parts 6
fingerprint after replay  : 1455589	14563765890659912731

CONVERGED: replay changed nothing (1455589	14563765890659912731)
```

Two separate properties, and the second is the stronger one:

**The restart lost nothing.** At `SIGKILL` the committed offset was 440,000 while
1,060,016 events were still unread. The restarted consumer resumed from the last
committed offset — replaying whatever the killed process had inserted but not
acknowledged — and drained to the end. The 1,500,016 events collapse to
**1,455,589** rows, the difference being the injected duplicates and reversals.

**The full replay changed nothing at all.** Offsets were reset to earliest
(verified at 0, because `--reset-offsets` fails quietly on a live group) and all
1,500,016 events were delivered a second time into a table that already contained
them. Both the row count *and* the hash over `(row_key, version, turnover, ggr,
net_revenue)` are identical. The count alone would not prove this — a count can
match while values differ — which is why the fingerprint is the comparison.

This is what makes commit-after-insert the correct trade. The consumer
deliberately acknowledges late and accepts replay as the cost, because ADR-0007
makes replay free. Under the original commit-before-insert code the same
`SIGKILL` would have silently dropped every event between the last commit and the
crash.

The row count reproduced at 1,455,589 across three independent runs of this
script with different kill points (368,706 / 446,331 / 446,332 rows at kill), so
the converged state does not depend on where the process died.

## What broke, and what it cost

**The Kafka code had never been run, and three things were wrong.**

*The producer never checked delivery.* `flush()` returns the count of
still-undelivered messages and the original discarded it, so a run could report
events it had not sent. It now fails loudly. `produce()` also raises
`BufferError` when the local queue fills; the original had no handler, so
backpressure would have surfaced as a crash mid-run.

*The consumer committed before inserting, not after.* The original called
`consumer.commit(message, asynchronous=True)` immediately after yielding each
event — acknowledging data that existed only in a Python list, with the insert
still hundreds of events away. A crash in that window loses events silently, and
the code's own comment claimed the opposite ("Offsets commit only after a batch
is inserted"). This is the one bug that would have caused data loss in
production. The fix restructured the source from a generator into a class,
because a generator can yield events but cannot know when the batch they joined
was durably written.

*A partly-filled batch never flushed.* This one was found by measurement, not by
reading. After the rescale run, lag sat frozen at 26,546 with three healthy
members assigned — the signature of a stalled consumer. The cause: the flush
deadline was only evaluated when a *new* event arrived, so once the producer
stopped, a batch smaller than `--batch-size` sat in memory forever, inserted and
committed by nothing. The Kafka source now yields an idle tick so the deadline is
checked while the stream is quiet.

**One containerisation finding.** The consumer imports `normalise_market` from
`betflow/src/load.py` (ADR-0004), which imports pandas at module level — pulling
the whole batch analytics stack into a streaming container for one pure-string
function, ~50 MB per replica. The consumer now falls back to loading the
pandas-free prelude of that module directly, with the split point asserted at
import so a future edit fails loudly instead of silently. Both paths were checked
to agree on 11 cases including the `{COMPETITOR1}` and non-string edge cases:
zero mismatches.

**One operational trap worth writing down.** `docker compose up --scale` reuses
an existing container when the image has not changed, and that container keeps
its *original* environment. A replica left over from a previous run therefore
rejoins the previous consumer group, its offsets never move, and the lag graph
looks exactly like a stalled consumer. `kafka_rescale.sh` now passes
`--force-recreate` on the initial scale for this reason. Similarly
`--reset-offsets` refuses to act on a group with live members and *fails quietly*
— a replay that consumes nothing then "converges" trivially and proves nothing,
so the script now verifies the reset landed before trusting the comparison.

## What this does not show

- **Kafka was not run alongside the 100-reader load** as `05-concurrent.md` did
  for the fifo path. Read latency under simultaneous ingest was measured there
  (p50 1.71 ms) and the artifact boundary is what guarantees it; nothing about
  the transport changes that, but it is an inference here rather than a
  measurement.
- **Retention was set to 24h and never tested at its boundary.** ADR-0009's
  replay-to-watermark guarantee is bounded by retention, and every replay here
  ran well inside it.
- **Single broker, replication factor 1.** Nothing here says anything about
  broker failure, and with one broker there is no answer to give.
