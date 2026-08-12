# 10. Scale by naming what breaks first, and where the state is

Date: 2026-08-12

## Status

Accepted for the design; the measurements it commits to are marked as
**predictions** until the load harness produces figures. Predictions that turn
out wrong are corrected here rather than quietly dropped.

## Context

"Scale horizontally and vertically with zero downtime" is answerable in two
registers. The first lists technologies that are known to scale. The second
names the specific resource that saturates first, the number at which it
saturates, and what the operator does about it — and is the only one that
survives a question.

This record commits to the second, which requires stating what we expect to
break **before** measuring it, so the measurement can contradict us.

A load path exists to make this observable: the producer's rate is a dial from
70k/min to 500k/min (1,167 to 8,333 events/s), and it can be pushed past the
brief's ceiling. The demo is to raise it until something visibly degrades, point
at the saturated resource, act on it, and watch the system recover.

## The observable that matters

**Consumer lag** — the distance between what the producer has written and what
the consumer has processed. It is the single number that separates the two
failure regimes:

- **Lag stable, latency rising** → the system keeps up; work is queued elsewhere.
  Freshness degrades, correctness does not.
- **Lag growing without bound** → arrival exceeds capacity. Nothing recovers
  until capacity rises or arrival falls.

The distinction matters because the responses are opposite. Rising latency with
flat lag is often acceptable — ADR-0009 already declares GGR freshness at 30–60 s,
so a refresh taking 8 s instead of 2 s changes nothing a reader can see. Growing
lag is an outage in slow motion, and it must be visible before it is felt.

This is the primary argument for putting a log between producer and consumer.
The ingest rate does not require one: 8,333 events/s is comfortably within a
direct-write path. What the log buys is **lag as a first-class, observable
quantity** and the ability to add consumers without stopping the producer. Those
are operational properties, not throughput ones, and the justification should be
stated that way rather than as "it scales".

## What we predict breaks, in order

Stated as predictions so the harness can refute them.

**1. The refresh sweep, not the ingest path.** ClickHouse ingesting 8,333 rows/s
in batches is unremarkable; the seven breakdowns plus the read-time `argMax`
collapse (ADR-0008) is the heavier side. Prediction: at ~5–10x the design point,
refresh duration exceeds the Class 1 tick interval and ticks begin to overlap.

*Response, in order:* (a) restrict the collapse to recent partitions and
`OPTIMIZE … FINAL` sealed cold ones, so history is physically deduplicated and
never re-collapsed; (b) give ClickHouse more cores — this workload is
embarrassingly parallel across parts and vertical scaling is genuinely effective
here; (c) split the refresh so Class 1 and Class 2 sweep independently, since
they already have different cadences.

**2. Consumer throughput.** A single consumer process doing canonicalisation and
hashing is CPU-bound in Python. Prediction: it saturates before ClickHouse does,
somewhere around 2–4x the design point.

*Response:* add consumer instances. This is the horizontal step the demo shows
live — partitions redistribute, lag drains visibly. It works **only because**
ADR-0007 made ingestion order-independent and idempotent: two consumers
processing overlapping ranges converge to the same state. Without that property
this step would corrupt data instead of fixing throughput.

**3. Serving.** Last, and least interesting: 100 concurrent readers hitting a
cached artifact is a trivial load, and it stays trivial as readers grow because
the artifact is computed once per tick regardless of who reads it (ADR-0009).

## Decision

**Horizontal, vertical, and what cannot move**

*Scales horizontally — add instances, no coordination:*

- **Consumers.** Stateless between batches. Their correctness under parallelism
  is inherited from ADR-0007's idempotent, order-independent contract.
- **API and cache nodes.** They serve a precomputed artifact; any node answers
  any request.
- **The dashboard.** Static assets.

*Scales vertically — and should:*

- **ClickHouse.** Aggregation over columnar data parallelises across cores within
  a node, and 20M rows is small enough that a single well-provisioned node beats
  a distributed cluster on both latency and operational burden. Adding cores and
  memory is the correct first move, and going multi-node
  (`ReplicatedReplacingMergeTree` + Keeper) should be deferred until vertical
  headroom is genuinely exhausted, because it is a real step up in operational
  cost.

*Cannot be replicated away — the state that blocks it:*

- **Partition assignment.** A partition has one owner at a time; this is what
  makes ordering-within-partition meaningful. Consumers scale to the partition
  count and no further. Raising the count is a planned operation, not a runtime
  knob — the ceiling must be chosen up front.
- **The window boundary.** Class 3 statistics are defined over a closed window
  (ADR-0009), and a window closes once. Two workers cannot each close it. Window
  computation is singleton work, guarded by a lease; it scales vertically only.
- **The FDR family.** Benjamini–Hochberg needs every p-value in the family at
  once. It cannot be sharded without changing what the test means — and this is a
  statistical constraint, not an engineering one, so no infrastructure resolves
  it.
- **Kick-off arrival.** Sharp behaviour for a fixture cannot be computed before
  that fixture kicks off (ADR-0009). Infinite hardware does not shorten it.

**Zero downtime**

Zero downtime is a consequence of properties established elsewhere, not a
deployment technique bolted on:

- **Consumers** are replaced one at a time. An in-flight batch that is
  reprocessed after a restart is harmless because re-delivery is idempotent
  (ADR-0007). This is the property that makes rolling deploys safe; without it,
  every deploy risks double-counting.
- **Schema changes** are additive. ClickHouse `ALTER TABLE ADD COLUMN` is
  metadata-only; new columns are written by new consumers and ignored by old
  ones, so producer, consumer and reader versions may differ during a rollout.
  Destructive changes go through a new table and a switch of the read path, never
  through mutation in place.
- **The API** serves the last good artifact. A refresh job that dies mid-sweep
  publishes nothing; readers keep the previous artifact and its watermark, which
  visibly stops advancing. Failure degrades freshness, which is declared, rather
  than availability.
- **ClickHouse vertical scaling** is the one genuinely disruptive step on a
  single node. With replication it is a failover; without it, it is a restart
  during which ingest buffers in the log and drains afterwards — the log absorbs
  the outage, which is a second operational reason for having it.

## Consequences

**Positive**

- The scaling story is falsifiable. Each claim names a resource and an expected
  breaking point, and the harness either confirms it or corrects this record.
- The horizontal step that matters (adding consumers) is demonstrable live, and
  its safety traces to a documented property rather than to hope.
- Non-scalable state is enumerated rather than discovered under load. Three of
  the four items are domain constraints, which is worth saying explicitly: they
  would exist in any implementation.
- Zero downtime falls out of idempotency and additive schema change, both already
  decided, rather than requiring a separate mechanism.

**Negative**

- Partition count is a ceiling chosen before the load that will test it. Choose
  too low and consumer scaling stops early; too high and every consumer carries
  per-partition overhead for capacity it never uses.
- Single-node ClickHouse means vertical scaling requires a restart. Accepted for
  this exercise, with the log absorbing the gap; a production deployment would
  replicate, at materially higher operational cost.
- The predictions above are unmeasured at the time of writing. They are recorded
  so they can be wrong in public.
- Zero downtime here means *no reader-visible unavailability*. It does not mean
  no degradation: freshness is explicitly allowed to slip, which is only
  acceptable because ADR-0009 makes freshness visible rather than implied.
