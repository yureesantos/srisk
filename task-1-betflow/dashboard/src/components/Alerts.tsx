/* The active-alerts surface — the cockpit's reason to exist. It answers one
 * question at a glance: what needs attention now? A one-line severity strip sits
 * above a dense, severity-sorted list of individual flags, each linking to the
 * exact evidence via the existing verify wiring. High-count detectors are shown
 * as aggregate lines that jump to their section rather than flooding the panel.
 *
 * Everything is a read of `lib/alerts.ts`, which is itself a read of the
 * payload. No detection or scoring happens here. */

import { ChevronRight } from 'lucide-react'
import {
  buildAlerts,
  buildAggregates,
  severityCounts,
  SEVERITY_COLOR,
  SEVERITY_LABEL,
  type Severity,
} from '../lib/alerts'
import { VerifyButton } from './VerifyButton'
import { ScrollArea } from './ui/scroll-area'
import { int } from '../lib/format'

const STRIP_ORDER: Severity[] = ['critical', 'serious', 'warning', 'signature']

/** One-line severity summary — the chips at the very top of the cockpit. */
export function AlertStrip() {
  const counts = severityCounts()
  const aggregates = buildAggregates()

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border bg-surface/60 px-4 py-2.5">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">
        Active
      </span>
      {STRIP_ORDER.map((sev) =>
        counts[sev] > 0 ? (
          <span key={sev} className="flex items-center gap-1.5 text-[12px]">
            <Dot severity={sev} />
            <span className="tnum font-semibold text-ink">{counts[sev]}</span>
            <span className="text-ink2">{SEVERITY_LABEL[sev].toLowerCase()}</span>
          </span>
        ) : null,
      )}
      <span className="mx-1 hidden h-4 w-px bg-border sm:block" aria-hidden />
      {aggregates.map((ag) => (
        <a
          key={ag.label}
          href={`#section-${ag.section}`}
          className="flex items-center gap-1.5 text-[12px] text-muted transition-colors hover:text-ink2"
        >
          <span className="tnum font-medium text-ink2">{int(ag.count)}</span>
          {ag.label}
        </a>
      ))}
    </div>
  )
}

/** The dense, always-visible list of individual flags — the panel proper. */
export function AlertsPanel() {
  const alerts = buildAlerts()
  const aggregates = buildAggregates()

  return (
    <div className="rounded-lg border border-border bg-surface/50 shadow-[var(--shadow-raise)]">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">
          Active alerts
        </span>
        <span className="tnum text-[11px] text-muted">
          {int(alerts.length)} flagged · sorted by severity
        </span>
      </div>

      {alerts.length === 0 ? (
        <div className="flex items-center gap-2 px-4 py-3 text-[13px] text-ink2">
          <Dot severity="signature" />
          All detectors nominal — 0 active flags.
        </div>
      ) : (
        <ScrollArea className="max-h-[320px]">
          <ul>
            {alerts.map((a) => (
              <li
                key={a.id}
                className="flex items-center gap-3 border-b border-grid/60 px-4 py-2 last:border-b-0 hover:bg-raised/40"
              >
                <Dot severity={a.severity} />
                <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                  {a.label}
                </span>
                <span className="hidden items-center gap-3 md:flex">
                  {a.cells.map((c) => (
                    <span key={c.k} className="whitespace-nowrap text-[12px] text-ink2">
                      <span className="text-muted">{c.k} </span>
                      <span className="tnum text-ink">{c.v}</span>
                    </span>
                  ))}
                </span>
                {a.verifyRef ? (
                  <VerifyButton refTo={a.verifyRef} />
                ) : (
                  <span className="w-[68px]" aria-hidden />
                )}
              </li>
            ))}
          </ul>
        </ScrollArea>
      )}

      {/* Aggregate detectors — one line each, jumping to their section. */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-border px-4 py-2">
        {aggregates.map((ag) => (
          <a
            key={ag.label}
            href={`#section-${ag.section}`}
            className="flex items-center gap-1.5 text-[12px] text-muted transition-colors hover:text-ink2"
          >
            <span className="tnum font-medium text-ink2">{int(ag.count)}</span>
            {ag.label}
            <ChevronRight size={12} />
          </a>
        ))}
      </div>
    </div>
  )
}

function Dot({ severity }: { severity: Severity }) {
  return (
    <span
      className="size-2 shrink-0 rounded-full"
      style={{ background: SEVERITY_COLOR[severity] }}
      aria-hidden
    />
  )
}
