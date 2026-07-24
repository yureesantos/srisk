/* Small cell renderers shared across tables. Presentation only — they read
 * pre-computed payload values and format them; they never do arithmetic. */

import type { MoneyBlock } from '../lib/payload'
import { money, signedPct, int } from '../lib/format'
import { useCurrency } from './currency'

/* Money in the currency the operator selected — one figure, never a
 * cross-currency total (ADR-0001). If a row carries other currencies too, their
 * presence is noted quietly ("+2 ccy") so nothing is hidden, but the column
 * stays scannable: one aligned number per row in the chosen currency. */
export function MoneyCell({ block }: { block?: MoneyBlock | null }) {
  const { currency } = useCurrency()
  if (!block?.by_currency || Object.keys(block.by_currency).length === 0) {
    return <span className="text-muted">—</span>
  }
  const codes = Object.keys(block.by_currency)
  const selected = block.by_currency[currency]
  const others = codes.filter((c) => c !== currency).length

  return (
    <div className="flex flex-col items-end gap-0.5">
      {selected !== undefined ? (
        <span className="whitespace-nowrap">{money(selected, currency)}</span>
      ) : (
        <span className="text-muted" title={`no ${currency} in this row`}>
          — {currency}
        </span>
      )}
      {(others > 0 || block.unresolved_units > 0) && (
        <span className="text-[11px] text-muted">
          {others > 0 && `+${others} ccy`}
          {others > 0 && block.unresolved_units > 0 && ' · '}
          {block.unresolved_units > 0 && `${int(block.unresolved_units)} n/c`}
        </span>
      )}
    </div>
  )
}

/* A signed movement, coloured by direction. Steamers (price shortened, the
 * market backing the selection) and drifters (price lengthened) are the two
 * directions traders read first, so they get the two primary series colours —
 * not red/green, which would imply good/bad where none is meant. */
export function Delta({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return <span className="text-muted">—</span>
  }
  const colour = value > 0 ? 'text-s1' : value < 0 ? 'text-s2' : 'text-ink2'
  return <span className={`tnum ${colour}`}>{signedPct(value)}</span>
}

/* A share of a whole, shown as a value plus a thin proportional bar so a column
 * of shares can be scanned for shape, not just read row by row. */
export function ShareBar({ share }: { share: number }) {
  const pct = Math.max(0, Math.min(1, share)) * 100
  return (
    <div className="flex items-center justify-end gap-2">
      <span className="tnum text-ink2">{pct.toFixed(1)}%</span>
      <span className="relative hidden h-1.5 w-16 overflow-hidden rounded-full bg-raised sm:block">
        <span
          className="absolute inset-y-0 left-0 rounded-full bg-s1/70"
          style={{ width: `${pct}%` }}
        />
      </span>
    </div>
  )
}
