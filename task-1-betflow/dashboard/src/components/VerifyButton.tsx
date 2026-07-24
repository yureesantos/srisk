/* The finding-side half of verification. A finding — a flagged window, a sharp
 * price move — renders this next to its claim. Clicking it scrolls to the
 * evidence table and outlines the exact rows behind the number; clicking again
 * clears the highlight. Keyboard-operable, because verification is a primary
 * action here, not a decoration. */

import { useVerify } from './verify'
import type { VerifyRef } from '../lib/payload'

export function VerifyButton({ refTo }: { refTo: VerifyRef }) {
  const { active, request, clear } = useVerify()
  const isActive =
    active?.section === refTo.section &&
    JSON.stringify(active.select) === JSON.stringify(refTo.select)

  return (
    <button
      type="button"
      onClick={() => (isActive ? clear() : request(refTo))}
      aria-pressed={isActive}
      title={refTo.note || 'Show the rows behind this figure'}
      className={`
        inline-flex items-center gap-1.5 rounded-md border px-2 py-1
        text-[11px] font-medium transition-colors duration-150
        ${
          isActive
            ? 'border-bronze bg-bronze/15 text-ink'
            : 'border-grid text-ink2 hover:border-bronze/60 hover:text-ink'
        }
      `}
    >
      <svg
        width="12"
        height="12"
        viewBox="0 0 12 12"
        fill="none"
        aria-hidden
        className="shrink-0"
      >
        <path
          d="M1.5 6s1.6-3.2 4.5-3.2S10.5 6 10.5 6 8.9 9.2 6 9.2 1.5 6 1.5 6Z"
          stroke="currentColor"
          strokeWidth="1"
        />
        <circle cx="6" cy="6" r="1.4" fill="currentColor" />
      </svg>
      {isActive ? 'Clear' : 'Verify'}
    </button>
  )
}
