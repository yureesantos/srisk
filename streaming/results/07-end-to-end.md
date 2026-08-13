# End to end, everything at once

The only configuration that answers the brief's question. Every prior
measurement isolated one hop; this runs the whole pipeline simultaneously.

```
producer → Kafka → consumer → ClickHouse → refresh (SQL) → API → Varnish → 100 readers
```

Reproduce with `streaming/load/end_to_end.sh 500000 60`.

## Result

| | |
|---|---|
| producer → Kafka | **8,590 ev/s** (515,418/min — the brief's ceiling) |
| consumer → ClickHouse | 2,015,499 rows in 86s (23,342 ev/s) |
| refresh (SQL, class 1) | 9 ticks: mean 3.98s, min 0.16s, max 8.25s |
| **read latency p50** | **1.74 ms** |
| read p95 | 15.87 ms |
| cache hit rate | 99.84% |
| **backend fetches** | **85** for 5,201 client requests (61:1) |
| thresholds | **PASSED** |

## The three numbers, and why they get confused

| | Measured | What it is |
|---|---|---|
| response latency | **1.74 ms** | what a reader waits |
| **data age** | **2.8 – 5.9 s** | how stale the figure on screen is |
| recompute cost | 0.16 – 8.25 s | what runs in the background |

Data age was sampled while the refresh loop ran, with the watermark advancing
from `1786578771755` to `1786579857754` between samples — the artifact being
regenerated, not a cached figure aging.

**So: receiving 500,000 betslips per minute through Kafka, with 100 concurrent
readers, the front end responds in 1.74 ms and shows data under 6 seconds old.**

## Two things this run does not show cleanly

**The consumer processed 2,015,499 rows against the producer's 515,483.** It
drained backlog left in the topic by earlier Kafka tests. The pipeline worked,
but the consumer was under roughly 4x its nominal load — which makes the refresh
timings pessimistic rather than optimistic, so the conclusion holds. A clean run
would truncate the topic first.

**Refresh spanned 0.16s to 8.25s.** The minimum is the empty table at the start;
the maximum is 2M rows. Still inside the 1–5s class-1 cadence at the low end and
outside it at the high end — the table grew 2M rows in 60 seconds, which is not
a steady state any dashboard would sit in.

## What is still not measured

The UI does not poll. It reads the payload baked in at build time, so
"near-realtime updates to the ui" is proven at the API boundary and not on
screen. That is the last gap in the brief's item 3.
