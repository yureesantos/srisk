/* Currency selection, shared across the whole cockpit.
 *
 * Money never crosses a currency in this dataset (ADR-0001), so a single figure
 * can only ever mean one currency. Rather than stack EUR · PEN · USD in every
 * money cell, the operator picks the currency once and every money figure in
 * the product answers in it. The default is the currency carrying the most
 * turnover, so the first read is the one that matters.
 *
 * This is display-only: it selects which pre-computed per-currency value to
 * show. It never converts or sums across currencies — there is no exchange rate
 * in the data, and inventing one would be a lie. */

import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { payload } from '../lib/payload'

export type Currency = string

interface CurrencyState {
  currency: Currency
  setCurrency: (c: Currency) => void
  /** Every currency present in the dataset, busiest first. */
  available: Currency[]
}

const CurrencyContext = createContext<CurrencyState | null>(null)

/** Currencies ranked by total turnover — the busiest is the sensible default. */
function rankedCurrencies(): Currency[] {
  const byCcy = payload.overview.turnover.turnover.by_currency
  return Object.keys(byCcy).sort((a, b) => byCcy[b] - byCcy[a])
}

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const available = useMemo(rankedCurrencies, [])
  const [currency, setCurrency] = useState<Currency>(available[0] ?? 'EUR')
  const value = useMemo<CurrencyState>(
    () => ({ currency, setCurrency, available }),
    [currency, available],
  )
  return (
    <CurrencyContext.Provider value={value}>{children}</CurrencyContext.Provider>
  )
}

export function useCurrency(): CurrencyState {
  const ctx = useContext(CurrencyContext)
  if (!ctx) throw new Error('useCurrency must be used within <CurrencyProvider>')
  return ctx
}
