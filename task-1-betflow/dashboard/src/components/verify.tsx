/* Verification wiring.
 *
 * The design principle (DESIGN.md #1): no claim without a path to the rows it
 * came from. A finding carries a `verify_ref`; clicking "verify" scrolls the
 * evidence table into view and outlines the exact rows that back the number.
 * This context is the shared channel between the two — the finding publishes a
 * target, every table row asks whether it is the target.
 *
 * Matching mirrors `pipeline.resolve_ref` and `payload.resolveRef`: string
 * equality on every key in the ref's `select`. The row owns the comparison so
 * that tables never learn the shape of a particular finding. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import type { VerifyRef } from '../lib/payload'

interface VerifyState {
  /** The active target, or null when nothing is being verified. */
  active: VerifyRef | null
  /** Publish a target and scroll its section into view. */
  request: (ref: VerifyRef) => void
  /** Clear the highlight (Escape, or a second click on the same finding). */
  clear: () => void
  /** True when this row's fields satisfy the active ref's `select`. */
  isTarget: (section: string, row: Record<string, unknown>) => boolean
}

const VerifyContext = createContext<VerifyState | null>(null)

export function VerifyProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<VerifyRef | null>(null)

  const request = useCallback((ref: VerifyRef) => {
    setActive(ref)
    // Defer the scroll one frame so the target section is mounted/expanded
    // before we measure it.
    requestAnimationFrame(() => {
      const el = document.getElementById(`section-${ref.section}`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [])

  const clear = useCallback(() => setActive(null), [])

  // Escape clears the highlight — verification is a mode you step out of.
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setActive(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active])

  const isTarget = useCallback(
    (section: string, row: Record<string, unknown>) => {
      if (!active || active.section !== section) return false
      return Object.entries(active.select).every(
        ([key, value]) => String(row[key]) === String(value),
      )
    },
    [active],
  )

  const value = useMemo<VerifyState>(
    () => ({ active, request, clear, isTarget }),
    [active, request, clear, isTarget],
  )

  return <VerifyContext.Provider value={value}>{children}</VerifyContext.Provider>
}

export function useVerify(): VerifyState {
  const ctx = useContext(VerifyContext)
  if (!ctx) throw new Error('useVerify must be used within <VerifyProvider>')
  return ctx
}
