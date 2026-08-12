# 11. Cache the artifact as HTTP, and invalidate by event

Date: 2026-08-12

## Status

Accepted. Implements the per-class cache policy declared in ADR-0009.

## Context

The brief asks for 100 steady concurrent requests against the front end, names
Varnish as an option, and leaves the invalidation strategy open. ADR-0009 fixed
*what* the policy must express — a different freshness per layer, with windowed
statistics invalidated when their window closes rather than when a clock expires.
This record fixes *where that runs*.

Three properties of this workload decide the choice, and all three are already
established rather than assumed:

**Every request is identical.** Personalisation happens after delivery — the
currency control is client-side state selecting between values the payload
already carries (ADR-0009). There are no per-user responses, no auth, no query
parameters. The response is an anonymous, cacheable `GET`.

**The response is regenerated on a known tick, not on request.** The refresh job
publishes; the API never computes (ADR-0008). So the cache is not protecting an
expensive computation from repetition — it is fanning out one artifact to many
readers.

**Invalidation is event-driven for one class.** A windowed statistic stops being
current the moment its window closes. Waiting out a TTL would serve a Gini that
is known to be superseded.

There is also a failure mode worth naming because it is the only way 100 readers
can hurt this system: when a cached entry expires, every reader misses at once
and hits the backend simultaneously. The steady-state load is trivial; the
expiry-instant load is 100x that. Any serious answer has to address it.

### Candidates

**Varnish.** A reverse HTTP cache holding responses in memory, configured in VCL.
Two of its features map directly onto requirements above rather than
coincidentally:

- **Request coalescing.** Concurrent requests for the same missing object are
  collapsed into a single backend fetch; the others wait and are served the same
  response. This is precisely the expiry-instant stampede, solved by default
  rather than by configuration.
- **PURGE/BAN.** An explicit command drops a cached object on demand. This is
  ADR-0009's event-driven invalidation: when the refresh job closes a window, it
  BANs the corresponding artifact and the stale one is gone immediately, without
  waiting for a TTL.

It also supports serving stale content while revalidating, which is the exact
policy ADR-0009 specifies for Class 1.

**nginx.** Also caches HTTP, and is more widely known. Its cache is disk-backed
with an in-memory index, which is fine at this size. Two gaps: selective
invalidation (`proxy_cache_purge`) is a commercial feature in nginx Plus, with
open-source workarounds that amount to deleting files by hashed path; and request
collapsing exists (`proxy_cache_lock`) but is off by default and coarser. It
would work — the invalidation story is simply weaker, and invalidation is the
part the brief asked to see.

**Redis.** Excellent, and the wrong layer. It caches *data*, not HTTP responses,
so every reader still executes application code to fetch and serialise. It earns
its place when responses are assembled per request; here they are byte-identical
files. It would also be the right answer if the API were multi-instance and
needed shared state — which it is not, because the artifact is the state.

**Application-level cache only.** Keeping the last artifact in process memory and
serving it is nearly free and genuinely sufficient at 100 readers. Rejected not
because it fails, but because it puts the fan-out inside the process that must
stay responsive, and it gives no vocabulary for invalidation, which is a stated
part of the exercise.

## Decision

**Varnish in front of the artifact API, with TTL per class and BAN on window
close.**

```
browser → Varnish → API → artifact (published by refresh job)
```

| Class | `Cache-Control` | Invalidation |
|---|---|---|
| 1 — placement-complete | `max-age=2, stale-while-revalidate=5` | TTL only |
| 2 — settlement-complete | `max-age=30` | TTL only |
| 3 — windowed | `max-age=300` | **BAN on window close**, issued by the refresh job |

The TTLs are the cadences ADR-0009 derived from the data, expressed as HTTP. The
Class 1 `stale-while-revalidate` is what keeps a reader from ever waiting on a
refresh: an expired-but-recent artifact is served immediately while the new one
is fetched behind it.

**Request coalescing is left on**, and is the mechanism by which 100 concurrent
readers cost one backend request rather than 100. This is the specific answer to
the brief's concurrency requirement, and it is measurable: cache hit rate under
load is one of the numbers the load harness reports.

**The server is Varnish plus a minimal API process.** The API's only job is to
return the current artifact for a class with the right `Cache-Control` header. It
holds no session, no per-user state, and no computation — which is why it scales
horizontally by adding processes (ADR-0010) and why the cache in front of it is
the component that actually absorbs reader load.

## Consequences

**Positive**

- The stampede at TTL expiry — the only way 100 readers stress this system — is
  handled by a default rather than by discipline.
- Event-driven invalidation is expressed in the mechanism instead of approximated
  by a short TTL. A closed window's artifact is dropped when it closes.
- The cache is measurable in the same terms the brief asks about: hit rate,
  backend request count under 100 concurrent readers, p95 latency.
- The API stays trivial, which is what keeps it horizontally scalable.
- Answering in the vocabulary the brief used (Varnish, invalidation strategy)
  costs nothing technically, since the workload genuinely suits an HTTP cache.

**Negative**

- Another component to run and understand. At 100 readers, an in-process cache
  would be sufficient, and this is defensible only because invalidation strategy
  was explicitly part of the exercise — the honest framing is that Varnish is
  chosen for what it demonstrates as much as for what it is needed for at this
  scale.
- VCL is a bespoke configuration language. The configuration here is small, but
  it is one more thing that can be wrong in a way that is invisible until a
  reader sees a stale number.
- Cached responses live in memory and vanish on restart. Harmless — the artifact
  is republished on the next tick — but it means a Varnish restart briefly
  exposes the backend to full reader load.
- A BAN is issued by the refresh job, so invalidation correctness now depends on
  a component that could fail to send it. A missed BAN serves a stale windowed
  artifact for up to its TTL. Mitigated by keeping the Class 3 TTL finite rather
  than infinite, which makes a missed BAN a delay rather than a permanent error.
