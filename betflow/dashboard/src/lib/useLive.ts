/* The polling loop, as a hook.
 *
 * Returns a `revision` that increments on every successful swap. App uses it as
 * a React key, which remounts the tree against the new payload — blunt, but
 * correct: twenty-three modules read `payload` at render time, and a key change
 * is the one mechanism that guarantees every one of them sees the new object.
 *
 * The alternative — threading the artifact through context to all of them —
 * would be less blunt and much larger, and the page is small enough that a
 * remount every five seconds is not perceptible. */

import { useEffect, useRef, useState } from 'react'
import { INITIAL_LIVE, POLL_MS, apiBase, pollOnce, type LiveState } from './live'

export function useLive(): LiveState {
  const [state, setState] = useState<LiveState>(INITIAL_LIVE)
  // Held in a ref so the interval callback always sees the latest revision
  // without the effect re-subscribing on every tick.
  const latest = useRef<LiveState>(INITIAL_LIVE)

  useEffect(() => {
    const base = apiBase()
    if (!base) return

    let cancelled = false
    setState((s) => ({ ...s, mode: 'connecting' }))

    const tick = async () => {
      try {
        const next = await pollOnce(base, latest.current)
        if (cancelled) return
        latest.current = next
        setState(next)
      } catch (error) {
        if (cancelled) return
        const message = error instanceof Error ? error.message : String(error)
        // Keep the last good payload on screen rather than blanking the page:
        // a failed poll degrades freshness, which the ops panel then reports,
        // and that is the ADR-0009 posture — declare staleness, do not hide it.
        latest.current = { ...latest.current, mode: 'error', error: message }
        setState(latest.current)
      }
    }

    void tick()
    const timer = window.setInterval(tick, POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  return state
}
