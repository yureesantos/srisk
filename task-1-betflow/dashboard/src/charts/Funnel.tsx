/* A filtering cascade: a population narrowed by successive, stated conditions.
 *
 * Used twice — how the leg population narrows to those with a comparable
 * reference price, and how scored customer-windows narrow to the few that
 * survive the significance test. It is deliberately NOT the marketing funnel
 * cone: each step is a labelled horizontal bar whose length is the count and
 * whose caption is the condition that removed the rows above it. The reader can
 * see both what survived and, in the drop between bars, what was excluded and
 * why — which is the honest way to present a filter (nothing disappears
 * silently).
 *
 * Built as an HTML/flex component, not an ECharts chart: the value here is the
 * count-plus-reason on every row, and native text lays that out better than a
 * canvas ever will. */

import { int, pct } from '../lib/format'

export interface FunnelStep {
  label: string
  count: number
  /** Why the rows between the previous step and this one fell away. */
  note?: string
  /** Highlight the terminal survivors (e.g. the flagged windows). */
  terminal?: boolean
}

export function Funnel({ steps }: { steps: FunnelStep[] }) {
  const top = steps[0]?.count ?? 0

  return (
    <ol className="space-y-2.5">
      {steps.map((step, i) => {
        const frac = top > 0 ? step.count / top : 0
        const prev = i > 0 ? steps[i - 1].count : null
        const dropped = prev !== null ? prev - step.count : null
        return (
          <li key={step.label}>
            {dropped !== null && dropped > 0 && (
              <div className="mb-1.5 flex items-center gap-2 pl-1 text-[11px] text-muted">
                <span aria-hidden className="text-s2">
                  ↳
                </span>
                <span>
                  −{int(dropped)} {step.note ?? 'excluded'}
                </span>
              </div>
            )}
            <div className="flex items-center gap-3">
              <div
                className={`
                  relative h-9 min-w-0 flex-1 overflow-hidden rounded-md border
                  ${step.terminal ? 'border-bronze/60' : 'border-grid'}
                `}
              >
                <div
                  className={`absolute inset-y-0 left-0 ${
                    step.terminal ? 'bg-bronze/25' : 'bg-s1/20'
                  }`}
                  style={{ width: `${Math.max(frac * 100, 2)}%` }}
                  aria-hidden
                />
                <div className="relative flex h-full items-center justify-between px-3">
                  <span className="truncate text-[13px] text-ink2">{step.label}</span>
                  <span className="tnum ml-3 shrink-0 text-[13px] font-medium text-ink">
                    {int(step.count)}
                  </span>
                </div>
              </div>
              <span className="tnum w-12 shrink-0 text-right text-[11px] text-muted">
                {pct(frac, 1)}
              </span>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
