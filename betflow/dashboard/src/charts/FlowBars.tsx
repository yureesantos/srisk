/* The flow breakdown — where the money goes, by any dimension.
 *
 * One row per category (a market, a competition, a fixture, a team). The row is
 * a hybrid: a proportional bar carries the shape so a column can be scanned for
 * concentration at a glance, and exact figures sit beside it so nothing has to
 * be estimated off the bar. This is the "charts AND tables" the brief asks for,
 * collapsed into one object — the bar answers "which dominates?", the numbers
 * answer "by exactly how much?", and they never disagree because they render
 * the same value.
 *
 * Turnover is shown per currency, stacked, never summed across currencies
 * (ADR-0001): a row can carry EUR and PEN, and folding them into one number
 * would invent an exchange rate the dataset doesn't contain. The bar length
 * encodes the share of betslips (a currency-free count), so the visual
 * comparison stays honest even where money can't be compared.
 *
 * Rows can be verify targets: when a finding elsewhere points at a category,
 * its row lights up. */

import type { BreakdownRow } from '../lib/payload'
import { useVerify } from '../components/verify'
import { useCurrency } from '../components/currency'
import { int, money } from '../lib/format'

interface FlowBarsProps {
  sectionId: string
  rows: BreakdownRow[]
  /** Column header for the category (e.g. "Market", "Competition"). */
  dimensionLabel: string
  /** Cap rows rendered here; the table below carries the full set. */
  limit?: number
}

export function FlowBars({
  sectionId,
  rows,
  dimensionLabel,
  limit = 12,
}: FlowBarsProps) {
  const { isTarget } = useVerify()
  const { currency } = useCurrency()
  const shown = rows.slice(0, limit)
  const maxShare = Math.max(...shown.map((r) => r.share), 0.0001)

  return (
    <div className="overflow-hidden rounded-xl border border-grid">
      <div className="grid grid-cols-[1fr_auto] gap-4 border-b border-grid bg-surface/70 px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted">
        <span>{dimensionLabel}</span>
        <span className="text-right">Betslips · turnover</span>
      </div>
      <ul>
        {shown.map((row) => {
          const target = isTarget(sectionId, row as unknown as Record<string, unknown>)
          const barPct = (row.share / maxShare) * 100
          const selected = row.turnover.by_currency[currency]
          const others = Object.keys(row.turnover.by_currency).filter(
            (c) => c !== currency,
          ).length
          return (
            <li
              key={row.key}
              className={`
                grid grid-cols-[1fr_auto] items-center gap-4 border-b border-grid/60 px-4 py-2.5
                last:border-b-0 transition-colors duration-150
                ${target ? 'is-verify-target' : 'hover:bg-raised/40'}
              `}
            >
              <div className="min-w-0">
                <div className="mb-1.5 flex items-baseline justify-between gap-3">
                  <span className="truncate text-[13px] text-ink" title={row.label}>
                    {row.label}
                  </span>
                  <span className="tnum shrink-0 text-[12px] text-muted">
                    {(row.share * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-raised">
                  <div
                    className="h-full rounded-full bg-s1/70"
                    style={{ width: `${Math.max(barPct, 1)}%` }}
                    aria-hidden
                  />
                </div>
              </div>
              <div className="flex flex-col items-end gap-0.5 text-right">
                <span className="tnum text-[13px] font-medium text-ink">
                  {int(row.betslips)}
                </span>
                {selected !== undefined ? (
                  <span className="tnum whitespace-nowrap text-[11px] text-ink2">
                    {money(selected, currency)}
                    {others > 0 && <span className="text-muted"> +{others}</span>}
                  </span>
                ) : (
                  <span className="text-[11px] text-muted">no {currency}</span>
                )}
              </div>
            </li>
          )
        })}
      </ul>
      {rows.length > limit && (
        <div className="border-t border-grid bg-surface/40 px-4 py-2 text-[11px] text-muted">
          Top {int(limit)} of {int(rows.length)} shown, ranked by betslips. Full
          breakdown in the table below.
        </div>
      )}
    </div>
  )
}
