/* Formatting only: how digits look, never what they are.
 *
 * Payload values arrive pre-rounded from the pipeline (money 2dp, rates 4dp).
 * Nothing here sums, divides or re-rounds — double rounding is how "43.5% here,
 * 43.4% there" happens. */

import type { MoneyBlock } from './payload'

const INT = new Intl.NumberFormat('en-GB')
const MONEY = new Intl.NumberFormat('en-GB', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

type Maybe = number | null | undefined

const missing = (value: Maybe): value is null | undefined =>
  value === null || value === undefined || Number.isNaN(value)

export const int = (value: Maybe): string => (missing(value) ? 'n/a' : INT.format(value))

export const money = (value: Maybe, currency?: string | null): string =>
  missing(value) ? 'n/a' : currency ? `${MONEY.format(value)} ${currency}` : MONEY.format(value)

/** Rates ship as fractions. Scaling by 100 for display is presentation. */
export const pct = (rate: Maybe, decimals = 1): string =>
  missing(rate) ? 'n/a' : `${(rate * 100).toFixed(decimals)}%`

export const signedPct = (rate: Maybe, decimals = 1): string =>
  missing(rate) ? 'n/a' : rate > 0 ? `+${pct(rate, decimals)}` : pct(rate, decimals)

export const price = (value: Maybe): string => (missing(value) ? 'n/a' : value.toFixed(2))

/** Compact money for tight KPI cells: 1.12M, 376k, 596. Presentation only —
 *  the exact value is always one info-icon or table cell away. */
const COMPACT = new Intl.NumberFormat('en-GB', {
  notation: 'compact',
  maximumFractionDigits: 2,
})
export const compactMoney = (value: Maybe, currency?: string | null): string => {
  if (missing(value)) return 'n/a'
  const n = COMPACT.format(value)
  return currency ? `${n} ${currency}` : n
}

/** p-values span orders of magnitude; fixed decimals would print 0.0000 for
 *  the strongest findings, which reads as "no evidence" rather than "strong". */
export const pValue = (value: Maybe): string => {
  if (missing(value)) return 'n/a'
  if (value === 0) return '<1e-12'
  return value < 0.001 ? value.toExponential(1) : value.toFixed(4)
}

export const days = (value: Maybe): string =>
  missing(value) ? 'n/a' : value < 1 ? '<1d' : `${Math.round(value)}d`

export const date = (value?: string | null): string => (value ? String(value).slice(0, 10) : 'n/a')

export const dateTime = (value?: string | null): string =>
  value ? String(value).slice(0, 16).replace('T', ' ') : 'n/a'

/** One entry per currency, joined — never a sum across them. */
export const moneyBlock = (block?: MoneyBlock | null): string => {
  if (!block?.by_currency) return 'n/a'
  const parts = Object.keys(block.by_currency)
    .sort()
    .map((code) => money(block.by_currency[code], code))
  return parts.length ? parts.join('  ·  ') : 'n/a'
}

/** A single currency out of a block, for a table column. */
export const currencyOf = (block: MoneyBlock | null | undefined, code: string): string => {
  const value = block?.by_currency?.[code]
  return value === undefined ? '—' : MONEY.format(value)
}

export const truncate = (text: unknown, limit: number): string => {
  const value = String(text ?? '')
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value
}
