# Emitted → visible on the API

Every other measurement covers one hop. This times a single identifiable event
through all of them, under continuous 500k/min load:

```
producer → Kafka → consumer → ClickHouse → refresh → API → Varnish
```

Reproduce with `python -m streaming.load.latency_probe --probes 6` while the
pipeline is running.

## Result

| probe | to ClickHouse | to API | artifact age when seen |
|---|---|---|---|
| 1 | 547 ms | 5.0 s | 0.7 s |
| 2 | 562 ms | 4.1 s | 0.4 s |
| 3 | 582 ms | 6.1 s | 1.9 s |
| 4 | 607 ms | 4.1 s | 1.0 s |
| 5 | 521 ms | 4.2 s | 0.5 s |
| 6 | 305 ms | 6.3 s | 1.9 s |

**Median: 562 ms to ClickHouse, 5.0 s to the API** (min 4.1 s, max 6.3 s).

## Where the time goes

```
  0.56 s   transport   Kafka + consumer + batched insert     11%
  4.44 s   waiting     for the next refresh tick             89%
```

**The transport is a ninth of the total.** The rest is cadence: an event landing
in ClickHouse a millisecond after a tick waits for the next one, and the refresh
loop here ran every 3 seconds with each pass taking ~1–2 s.

That is a design choice, not a limit. Running the refresh every second would put
this near 1.5 s. ADR-0009 chose seconds rather than sub-second because the data
does not support more: settlements were measured reversing inside 95 seconds, so
a GGR figure refreshed faster than that reports noise as signal. Class 1 is
refreshed fast because its inputs are immutable, and 5 s is comfortably inside
what the ingest path allows.

## How it is measured

The probe carries a unique customer id and its own emission timestamp as its
version. Stage 1 polls ClickHouse for the row key. Stage 2 polls the **API
through Varnish** — the path a reader takes, not a direct database query — and
waits for an artifact whose **watermark** is at or past the probe's version.

The watermark is the test rather than the row count: counts move constantly
under background load, so a rising count would prove nothing about this
particular event. The watermark is the highest version the refresh saw, so an
artifact carrying one at or past the probe's demonstrably includes it.
