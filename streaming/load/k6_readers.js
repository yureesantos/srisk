// 100 steady concurrent readers against the front end — the brief's item 4.
//
//   k6 run streaming/load/k6_readers.js
//   k6 run -e BASE=http://localhost:18088 streaming/load/k6_readers.js   # bypass cache
//
// What proves the requirement is NOT that it survived. 100 readers against a
// 396 KB file is trivial — measured at p50 0.7ms even from Python's stdlib
// server. The number that matters is **how many requests reached the backend**:
// with request coalescing (ADR-0011), a TTL expiry should produce roughly one
// backend fetch per period per class, not one per reader.
//
// So the assertion is on cache hit rate and on the ratio between client
// requests and backend fetches, read from varnishstat after the run.

import http from 'k6/http'
import { check } from 'k6'
import { Counter, Rate, Trend } from 'k6/metrics'

const hits = new Counter('cache_hits')
const misses = new Counter('cache_misses')
const hitRate = new Rate('cache_hit_rate')
const byClass = {
  1: new Trend('latency_class1', true),
  2: new Trend('latency_class2', true),
  3: new Trend('latency_class3', true),
}

const BASE = __ENV.BASE || 'http://localhost:18081'

// Weighted to how a dashboard actually reads: the fast-moving sections are
// polled often, the windowed ones rarely. Uniform sampling would overstate the
// load on class 3, whose TTL is 150x longer.
const ARTIFACTS = [
  { name: 'overview', class: 1, weight: 30 },
  { name: 'flow', class: 1, weight: 30 },
  { name: 'timing', class: 1, weight: 15 },
  { name: 'prices', class: 2, weight: 10 },
  { name: 'data_quality', class: 2, weight: 5 },
  { name: 'concentration', class: 3, weight: 4 },
  { name: 'anomalies', class: 3, weight: 3 },
  { name: 'sharp', class: 3, weight: 3 },
]

const TOTAL_WEIGHT = ARTIFACTS.reduce((sum, a) => sum + a.weight, 0)

function pick() {
  let draw = Math.random() * TOTAL_WEIGHT
  for (const artifact of ARTIFACTS) {
    draw -= artifact.weight
    if (draw <= 0) return artifact
  }
  return ARTIFACTS[0]
}

// A dashboard polls on an interval; it does not loop as fast as the network
// allows. Left unpaced, 100 VUs pull 2.1 GB in 60s (35 MB/s) and the bottleneck
// measured is the copy of bytes rather than the cache — Varnish sat at 0.33%
// CPU while p95 read 208ms. `constant-arrival-rate` models the real thing:
// 100 readers each polling roughly once a second.
const RATE = Number(__ENV.RATE || 100)

export const options = {
  scenarios: {
    steady_readers: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: __ENV.DURATION || '60s',
      preAllocatedVUs: 100,
      maxVUs: 200,
    },
  },
  thresholds: {
    // Pass/fail criteria, declared up front rather than read off the result.
    http_req_failed: ['rate==0'],
    http_req_duration: ['p(95)<100', 'p(99)<250'],
    cache_hit_rate: ['rate>0.90'],
  },
}

export default function () {
  const artifact = pick()
  const response = http.get(`${BASE}/artifact/${artifact.name}`, {
    tags: { artifact: artifact.name, class: String(artifact.class) },
  })

  const cached = response.headers['X-Cache'] === 'HIT'
  hitRate.add(cached)
  if (cached) hits.add(1)
  else misses.add(1)
  byClass[artifact.class].add(response.timings.duration)

  check(response, {
    'status 200': (r) => r.status === 200,
    'body is json': (r) => (r.headers['Content-Type'] || '').includes('json'),
    'cache-control present': (r) => Boolean(r.headers['Cache-Control']),
  })
}

export function handleSummary(data) {
  const metric = (name, stat) => {
    const m = data.metrics[name]
    return m ? (stat === 'count' ? m.values.count : m.values[stat]) : 0
  }
  const total = metric('http_reqs', 'count')
  const hitCount = metric('cache_hits', 'count')

  const lines = [
    '',
    '100 concurrent readers',
    '─'.repeat(52),
    `requests            ${total.toLocaleString()}`,
    `cache hits          ${hitCount.toLocaleString()} (${((hitCount / total) * 100).toFixed(1)}%)`,
    `cache misses        ${metric('cache_misses', 'count').toLocaleString()}`,
    `p50 latency         ${metric('http_req_duration', 'med').toFixed(2)} ms`,
    `p95 latency         ${metric('http_req_duration', 'p(95)').toFixed(2)} ms`,
    `p99 latency         ${metric('http_req_duration', 'p(99)').toFixed(2)} ms`,
    `failed              ${(metric('http_req_failed', 'rate') * 100).toFixed(2)}%`,
    '',
    'The figure that answers the brief is backend fetches, not these numbers:',
    'read it from `varnishstat -1 -f MAIN.backend_req` around the run.',
    '',
  ]

  return {
    stdout: lines.join('\n'),
    'streaming/results/k6_readers.json': JSON.stringify(data, null, 1),
  }
}
