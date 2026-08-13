/* Live status, when the page is reading a stream rather than a frozen file.
 *
 * ADR-0009's rule is that no figure appears without the reader being able to
 * learn how old it is. Under batch that was one hash in the footer, because the
 * whole artifact came from one immutable run. Under streaming there are three
 * cadences on screen at once — turnover refreshed seconds ago, GGR up to a
 * minute, a windowed Gini up to five — so a single timestamp would be a lie.
 *
 * This is the one place a reader looks to learn what they are looking at: age
 * per artifact, the stream position it saw, and whether the last poll landed.
 * Individual figures are not tagged inline — the cockpit is dense by design,
 * and per-number annotations would cost more legibility than they buy. That is
 * the trade ADR-0009 records, and it is reversible.
 *
 * Renders nothing in batch mode: a static artifact has no live status, and an
 * empty panel implying otherwise would be worse than no panel. */

import { Activity, AlertTriangle, Database, Radio } from 'lucide-react'
import type { LiveState } from '../lib/live'

/** Seconds, phrased the way an operator reads them. */
function age(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 1) return 'now'
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  const minutes = Math.floor(seconds / 60)
  return minutes < 60 ? `${minutes}m ago` : `${Math.floor(minutes / 60)}h ago`
}

/** Class 1 is expected within seconds; 3 is windowed and legitimately old. */
function toneFor(cls: number, seconds: number): string {
  const budget = cls === 1 ? 15 : cls === 2 ? 120 : 900
  return seconds > budget ? 'text-warn' : 'text-ink2'
}

export function OpsPanel({ live }: { live: LiveState }) {
  if (live.mode === 'off') return null

  const connecting = live.mode === 'connecting'
  const failed = live.mode === 'error'

  return (
    <section
      aria-label="Live pipeline status"
      className="
        mt-6 rounded-lg border border-border bg-panel/60 px-4 py-3
        text-[11px] leading-relaxed text-ink2
      "
    >
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <span className="flex items-center gap-1.5 font-medium text-ink">
          {failed ? (
            <AlertTriangle className="size-3.5 text-warn" />
          ) : (
            <Radio className={`size-3.5 ${connecting ? 'text-ink3' : 'text-ok'}`} />
          )}
          {connecting ? 'Connecting' : failed ? 'Stream unreachable' : 'Live'}
        </span>

        {live.oldestAgeSeconds !== null && (
          <span className="flex items-center gap-1.5">
            <Activity className="size-3.5" />
            oldest figure <span className="tnum text-ink">{age(live.oldestAgeSeconds)}</span>
          </span>
        )}

        {live.watermark !== null && (
          <span className="flex items-center gap-1.5">
            <Database className="size-3.5" />
            {/* The stream position this artifact saw. ADR-0009 replaced the
              * batch dataset fingerprint with this: the claim is no longer
              * "reproducible from this file" but "reproducible by replaying to
              * this watermark". */}
            watermark <span className="tnum text-ink">{live.watermark}</span>
          </span>
        )}

        {live.payloadHash && (
          <span className="tnum" title={live.payloadHash}>
            {live.payloadHash.replace(/^sha256:/, '').slice(0, 10)}
          </span>
        )}
      </div>

      {live.artifacts.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 border-t border-border/60 pt-2.5">
          {live.artifacts.map((artifact) => (
            <span key={artifact.name} className="flex items-baseline gap-1.5">
              <span className="text-ink3">{artifact.name}</span>
              <span className={`tnum ${toneFor(artifact.cls, artifact.ageSeconds)}`}>
                {age(artifact.ageSeconds)}
              </span>
              {/* Served from cache rather than recomputed — the reason 100
                * concurrent readers cost one backend fetch per TTL, not 100. */}
              {artifact.cached && <span className="text-ink3">·cached</span>}
            </span>
          ))}
        </div>
      )}

      {live.error && (
        <p className="mt-2 text-warn">
          {live.error}
          {/* A failed poll keeps the last good payload on screen. Freshness
            * degrades and is reported; availability does not. */}
          {live.mode === 'error' && ' — showing the last artifact received'}
        </p>
      )}
    </section>
  )
}
