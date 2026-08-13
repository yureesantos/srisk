# Ingest and read, at the same time

The question every earlier measurement dodged: does read latency hold **while**
data is arriving? Everything before this ran sequentially — ingest, then refresh,
then read — which answers a question nobody asked.

Reproduce with `streaming/load/concurrent_test.sh 500000 60`.

## Setup

Running simultaneously for 60 seconds, inside Docker's 4 CPU / 8.3 GB allocation:

- **producer** at 500,000/min (the brief's ceiling), 2% reversals, 1% duplicates
- **consumer** canonicalising and inserting, batch 20k / flush 1s
- **refresh** recomputing class 1 in a loop
- **k6** with 100 concurrent readers against Varnish

## Result

| | |
|---|---|
| ingest sustained | **8,591 ev/s** (515,443/min) |
| rows | 76,603 → **577,003** (+500,400) |
| **read p50** | **1.71 ms** |
| **read p95** | **5.10 ms** |
| read max | 130.96 ms |
| failed requests | **0.00%** (0 of 5,501) |
| checks | **100%** (16,503) |
| cache hit rate | 99.85% |
| backend fetches | 88 |

**Thresholds passed.** For comparison, the same k6 scenario with no write load
measured p50 2.42 ms / p95 5.41 ms — the difference is noise. Sustained ingestion
at the brief's ceiling does not move front-end latency.

## Why, and which component does what

```
Producer → [Kafka] → Consumer → ClickHouse → refresh → API + Varnish → UI
                                                ↑                ↑
                                      load shows up here    and not here
```

- **ClickHouse** absorbs 8,591 inserts/s without disturbing reads. That is why
  ingestion does not compete with querying.
- **The artifact boundary** is what makes read latency independent of volume: the
  reader fetches a file, so nothing happening behind it can slow the response.
- **The refresh is where growth actually shows.** Tick duration over the run:
  **mean 6.61s, min 2.12s, max 13.76s**, climbing as the table grew from 76k to
  577k rows. This is the real bottleneck, and the reason for the SQL migration —
  it does not affect *latency*, it affects *freshness*: at 577k rows the figure
  on screen was up to 13.76s old rather than 5s.
- **Kafka was not in this run** (a fifo stood in for it). It buys observable
  consumer lag and live rescale, not latency.

## The distinction that matters

Three numbers get confused with each other, and only the first is what a user
waits for:

| | Measured | What it is |
|---|---|---|
| response latency | **1.71 ms** | what the reader waits |
| data age | 2–14 s | how stale the figure on screen is |
| recompute cost | 2.12–13.76 s | what runs in the background |

Volume moves the third, which moves the second. It does not move the first.
