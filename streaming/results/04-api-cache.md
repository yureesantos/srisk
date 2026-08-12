# Branch 4 — API + cache, measured

Raw results for `docs/build/04-api-cache.md`. Reproduce with the commands shown.

## Setup

```
ClickHouse   2 CPU / 4 GB      20M-row table, 76,603 collapsed rows loaded
api          0.5 CPU / 256 MB  stdlib ThreadingHTTPServer, serves files only
varnish      0.5 CPU / 256 MB  64 MB malloc storage
k6           on the host, not containerised
```

Artifacts served: 396 KB total, largest `anomalies.json` at 142 KB.

## Cache headers (ADR-0011 policy, verbatim)

```
$ curl -sD - -o /dev/null http://localhost:18088/artifact/flow
Cache-Control: public, max-age=2, stale-while-revalidate=5
X-Artifact-Class: 1

$ curl -sD - -o /dev/null http://localhost:18081/artifact/sharp
Cache-Control: public, max-age=300
X-Artifact-Class: 3
```

First request through Varnish is `X-Cache: MISS`, second is `HIT` — the policy is
applied, not merely declared.

## 100 steady concurrent readers

```
$ k6 run -e DURATION=60s streaming/load/k6_readers.js
```

| | |
|---|---|
| requests | 6,001 in 60s (100.01/s) |
| **cache hit rate** | **99.91%** (5,996 of 6,001) |
| **backend fetches** | **94** |
| **client:backend ratio** | **64:1** |
| p50 latency | **2.42 ms** |
| p95 latency | **5.41 ms** |
| p99 latency | under the 250 ms threshold |
| failed requests | **0.00%** (0 of 6,001) |
| checks | 100% (18,003 of 18,003) |

All declared thresholds passed: `http_req_failed rate==0`,
`http_req_duration p(95)<100`, `cache_hit_rate rate>0.90`.

**94 backend fetches is the figure that answers the brief.** With a 2-second TTL
on class 1, sixty seconds admits roughly 30 fetches per class-1 artifact; three
class-1 artifacts plus the slower classes lands where it landed. Without the
cache the backend would have seen all 6,001.

## The unpaced run, and why it is reported

The first attempt used `constant-vus`, which loops as fast as the network allows:

| | unpaced (`constant-vus`) | paced (`constant-arrival-rate`) |
|---|---|---|
| requests | 81,774 | 6,001 |
| data transferred | **2.1 GB (35 MB/s)** | 159 MB (2.6 MB/s) |
| p95 | **208 ms** | 5.41 ms |
| backend fetches | 93 | 94 |
| varnish CPU | **0.33%** | — |

The p95 threshold failed on the unpaced run, and the cause is worth stating: at
0.33% CPU the cache was not the constraint. 100 virtual users pulling 142 KB
artifacts in a closed loop saturate byte-copying, not caching. The brief asks for
"100 steady concurrent requests", which is a polling dashboard — the paced
scenario — and the unpaced figure is kept here because it names where this
actually breaks: bandwidth, at roughly 35 MB/s on this machine.

Note the backend fetch count barely moved (93 vs 94) across a 13x difference in
client requests. That is coalescing doing exactly what ADR-0011 selected it for.
