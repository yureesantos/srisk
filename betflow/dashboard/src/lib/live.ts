/* Live mode: poll the streaming API instead of reading the build-time artifact.
 *
 * The dashboard's contract does not change — it still renders one artifact and
 * computes nothing. What changes is where that artifact comes from and how
 * often it is replaced.
 *
 * Polling is a single 5-second interval across every artifact, not one interval
 * per class. The per-class cadences (ADR-0009: 5s / 60s / window-close) are
 * enforced where they belong, in the cache: Varnish holds class 2 for 30s and
 * class 3 for 300s, so asking every 5 seconds returns a cache HIT and never
 * reaches the backend. One interval here, three cadences in effect, and the
 * measured cost is 85 backend fetches for 5,201 client requests.
 *
 * Freshness is read from the response headers rather than inferred: the API
 * stamps `X-Artifact-Age-Seconds` per artifact, and the envelope carries the
 * watermark — the stream position this artifact saw (ADR-0009). */

import { applyLivePayload, bakedPayload, type Payload } from './payload'

const DEFAULT_BASE = 'http://localhost:18081'
const POLL_MS = 5000

/** Artifacts the API serves, and the payload key each one populates. */
const ARTIFACTS = [
  'overview',
  'flow',
  'timing',
  'prices',
  'concentration',
  'anomalies',
  'sharp',
  'data_quality',
] as const

/** The freshness fields every artifact response carries (ADR-0009). */
interface LiveEnvelope {
  generated_at?: string
  payload_hash?: string
  watermark?: number
}

export interface ArtifactStatus {
  name: string
  ageSeconds: number
  cls: number
  cached: boolean
}

export interface LiveState {
  /** `off` when no API is configured, `connecting` before the first success. */
  mode: 'off' | 'connecting' | 'live' | 'error'
  /** Bumped on every successful swap, so React can re-render the tree. */
  revision: number
  watermark: number | null
  payloadHash: string | null
  generatedAt: string | null
  artifacts: ArtifactStatus[]
  /** Seconds since the oldest artifact was regenerated — what the reader sees. */
  oldestAgeSeconds: number | null
  error: string | null
}

export const INITIAL_LIVE: LiveState = {
  mode: 'off',
  revision: 0,
  watermark: null,
  payloadHash: null,
  generatedAt: null,
  artifacts: [],
  oldestAgeSeconds: null,
  error: null,
}

/** Where the API lives. `?api=` overrides, for pointing at a remote stack. */
export function apiBase(): string | null {
  if (typeof window === 'undefined') return null
  const params = new URLSearchParams(window.location.search)
  const override = params.get('api')
  if (override) return override.replace(/\/$/, '')
  // Live mode is opt-in: without it the page renders the build-time artifact,
  // which is what the static GitHub Pages deploy serves.
  if (params.get('live') === '1') return DEFAULT_BASE
  return null
}

async function fetchArtifact(
  base: string,
  name: string,
): Promise<{ data: unknown; envelope: LiveEnvelope; status: ArtifactStatus }> {
  const response = await fetch(`${base}/artifact/${name}`, { cache: 'no-store' })
  if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`)
  const body = (await response.json()) as Record<string, unknown> & LiveEnvelope
  return {
    data: body.data,
    envelope: body,
    status: {
      name,
      // Falls back to the envelope's own timestamp when the header is absent —
      // a proxy that strips it should degrade the display, not break the page.
      ageSeconds: Number(response.headers.get('X-Artifact-Age-Seconds') ?? 0),
      cls: Number(response.headers.get('X-Artifact-Class') ?? 0),
      cached: response.headers.get('X-Cache') === 'HIT',
    },
  }
}

/** One poll: fetch every artifact, assemble one payload, swap it in. */
export async function pollOnce(base: string, previous: LiveState): Promise<LiveState> {
  const results = await Promise.allSettled(
    ARTIFACTS.map((name) => fetchArtifact(base, name)),
  )

  const next: Record<string, unknown> = {}
  const statuses: ArtifactStatus[] = []
  const failures: string[] = []

  results.forEach((result, index) => {
    const name = ARTIFACTS[index]
    if (result.status === 'fulfilled') {
      next[name] = result.value.data
      statuses.push(result.value.status)
    } else {
      failures.push(name)
      // A class that has not been computed yet keeps whatever the page already
      // has, rather than blanking a section. The status list omits it, so the
      // ops panel shows it as missing instead of pretending it is fresh.
      next[name] = (bakedPayload as unknown as Record<string, unknown>)[name]
    }
  })

  // Taken outside the loop: assigning to a `let` inside a callback defeats
  // TypeScript's flow analysis, which then narrows it to `never`. Every
  // artifact carries the same envelope fields, so the first success will do.
  const envelope: LiveEnvelope | undefined = results.find(
    (r): r is PromiseFulfilledResult<Awaited<ReturnType<typeof fetchArtifact>>> =>
      r.status === 'fulfilled',
  )?.value.envelope

  if (failures.length === ARTIFACTS.length) {
    return {
      ...previous,
      mode: 'error',
      error: `no artifact reachable at ${base}`,
    }
  }

  // `meta` is not served as an artifact of its own; the page needs its section
  // registry (the verify path resolves refs through it), so it is carried over
  // from the build-time artifact and the live envelope's identity is layered on.
  next.meta = {
    ...(bakedPayload.meta as unknown as Record<string, unknown>),
    generated_at: envelope?.generated_at ?? null,
    payload_hash: envelope?.payload_hash ?? null,
    watermark: envelope?.watermark ?? null,
  }

  applyLivePayload(next as unknown as Payload)

  return {
    mode: 'live',
    revision: previous.revision + 1,
    watermark: envelope?.watermark ?? null,
    payloadHash: envelope?.payload_hash ?? null,
    generatedAt: envelope?.generated_at ?? null,
    artifacts: statuses,
    oldestAgeSeconds: statuses.length
      ? Math.max(...statuses.map((s) => s.ageSeconds))
      : null,
    error: failures.length ? `stale: ${failures.join(', ')}` : null,
  }
}

export { POLL_MS, ARTIFACTS }
