# 13. A log between producer and consumer, for observability rather than throughput

Date: 2026-08-12

## Status

Accepted. Settles the decision DESIGN-STREAMING.md and `docs/BUILD-PLAN.md`
deliberately left open pending this record.

## Context

The design needs a transport between the producer and the consumer. The obvious
justification — "we need a log because of the volume" — **is not available here,
and claiming it would be false.**

Measured on the target machine: per-event application work runs at 902k ev/s
(canonicalise + hash) and 267k ev/s (`json.dumps`), against a required
**8,333 ev/s** at the brief's 500k/min ceiling. That is 32–108x of headroom on a
single core. A direct socket or pipe between the two processes would carry this
rate without difficulty.

So the question is not whether the rate demands a log. It does not. The question
is what a log buys that is worth a container.

Three things, and all three are requirements this design already committed to
elsewhere:

**Consumer lag as a trustworthy observable.** ADR-0010 makes lag the number that
separates the two failure regimes — flat lag with rising latency (freshness
degrading within declared bounds) versus unbounded lag growth (an outage in slow
motion). In a log, lag is `latest offset − committed offset`: computed by the
broker from facts it owns. Without a log, the consumer reports its own backlog,
which is the component under suspicion vouching for itself.

**Adding consumers without stopping the producer.** Steps 3–5 of the scaling demo
are: raise the rate until lag grows, name the saturated component, add consumers,
watch lag drain. With a log this is a partition rebalance — genuinely live.
Without one, it is restarting the consumer with more workers, which is a restart
with extra steps.

**Replay to a watermark.** ADR-0009 replaced the batch artifact hash with
"reproducible by replaying the stream to this watermark". That guarantee requires
the stream to still exist after being consumed. It is the load-bearing property,
and it eliminates one candidate outright.

### Candidates

**RabbitMQ.** Rejected, despite having the best out-of-the-box operator
experience of the three — a management UI is built in, with no extra container.
The model is wrong for this use: a message consumed and acknowledged is
**deleted**. There is nothing to replay to, so ADR-0009's guarantee would have to
be rewritten rather than implemented. Queue depth is also a weaker signal than
offset lag: a queue being drained can look healthy while the consumer falls
behind. Throughput is adequate at 8,333 ev/s but becomes the binding constraint
well before the rest of the system does, which would make the demo measure
RabbitMQ rather than this design.

**Kafka.** Accepted. A partitioned, append-only log with per-consumer offsets and
retention — exactly the three properties above. It is also the vocabulary the
client's CTO used when discussing this problem, which is not a technical argument
but is a real one: an answer is worth less if it has to be translated before it
can be evaluated.

**Redpanda.** Kafka-protocol compatible, single native binary, no JVM, materially
lighter (roughly 0.5–1 GB against 1.5–2 GB) and faster to start. Technically
interchangeable — same protocol, same client library, same code. Rejected on the
narrow ground that Kafka is the established name in this conversation. The local
resource argument that favoured it was resolved by other means: stopping an
unrelated container stack on the machine freed ~1 GB and the CPU it was using.

## Decision

**Kafka between producer and consumer, with AKHQ as the operations UI.**

- Topic `betslips`, **partitioned by `hash(uid)`** so all activity for one
  customer window lands in one partition. Per-Uid ordering is then meaningful
  without a global order, and the sharp-behaviour and repeat-backing analyses —
  both of which group by Uid — see a coherent stream.
- Partition count is the ceiling on consumer parallelism (ADR-0010) and is chosen
  up front rather than tuned later.
- Retention long enough to cover the replay window ADR-0009's guarantee claims.
  Beyond retention the claim weakens from "reproducible" to "audited", and that
  boundary is stated rather than implied.
- **AKHQ** for topics, consumer groups and per-partition lag. Kafka ships no UI;
  any of AKHQ, Kafka UI or Redpanda Console would serve, and AKHQ is chosen as
  the most commonly deployed of the three.

**The justification is observability and live rescale, never throughput.** If
asked why a log at 8,333 ev/s, the answer is the measurement above: the rate does
not require one, and the log is there because lag must be trustworthy and
consumers must scale without a restart.

## Consequences

**Positive**

- Lag comes from the broker rather than from the component being diagnosed.
- The demo's central move — scale consumers, watch lag drain — is a rebalance
  rather than a restart, and its safety traces to ADR-0007's idempotent,
  order-independent ingestion. Without that contract this step would corrupt data
  instead of fixing throughput.
- ADR-0009's replay-to-watermark guarantee becomes implementable rather than
  aspirational.
- Kafka absorbs ingest during a ClickHouse restart, which is what makes the
  vertical-scaling step of ADR-0010 non-destructive on a single node.
- Nothing in the producer or consumer is Kafka-specific beyond a client library;
  swapping to Redpanda is a compose-file edit if the JVM footprint becomes a
  problem.

**Negative**

- Two more containers (broker, UI) inside a 4 CPU / 8.3 GB Docker allocation
  shared with ClickHouse. The JVM's footprint is the largest single cost, and it
  competes with the thing being measured — CPU allocation is therefore recorded
  alongside every figure the load harness produces.
- A log is genuinely unnecessary at this rate. Someone reading only the
  architecture, without the measurement, would reasonably call it
  over-engineering; the defence is the measurement, and it has to be stated
  rather than assumed.
- Partition count fixes the consumer scaling ceiling before the load that tests
  it. Too low caps the demo early; too high adds per-partition overhead for
  capacity never used.
- Kafka is more to operate and to get wrong than a direct connection: listeners,
  heap sizing, and a coordination mode (KRaft) that must be configured correctly
  or the broker will not start.
- Retention bounds the replay guarantee. This is a real limit on ADR-0009's
  claim, not a configuration detail.
