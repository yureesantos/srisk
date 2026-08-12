> Part of the [build plan](../BUILD-PLAN.md). Conventions (`$CH`, `$FP`) are
> defined there. Update this file with what was actually measured once the
> branch lands — the plan is corrected by results, not defended against them.

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

---

## Risk

**API/cache — VCL wrong in a way that is invisible until it is not**
(ADR-0011 names this). A miswritten BAN or TTL serves stale data with a
confident face. Mitigation is branch 4 test 3 exercising the BAN end to end
before the demo depends on it; fallback per the cut order — TTL-only policy,
coalescing still measured, event invalidation conceded in writing. Second:
k6 plus 100 readers plus ingest inside the same 4-CPU Docker budget contends
with the thing being measured. Run k6 from the host (it is a host binary, not
a container), and record CPU allocation alongside every figure.
