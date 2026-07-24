/* The affordance that replaces prose in the cockpit.
 *
 * The report used to carry assumptions, limitations and method notes as
 * always-on paragraphs. An operator scanning for anomalies does not read those;
 * but the take-home audience (a CTO/CEO) values the rigour, so the notes must
 * stay one hover or tap away — never gone, never a wall of text. InfoTip is that
 * one hover: a small info icon that opens the notes on demand, keyboard
 * focusable, so nothing is lost, only folded.
 *
 * A single note renders inline; a list renders as numbered lines, mirroring the
 * old Notes block but on demand. */

import { Info } from 'lucide-react'
import { Tooltip, TooltipTrigger, TooltipContent } from './ui/tooltip'

interface InfoTipProps {
  /** One note, or several. Several render as a numbered list. */
  notes: string | string[]
  /** Accessible name for the trigger — defaults to a generic label. */
  label?: string
  size?: number
}

export function InfoTip({ notes, label = 'Notes and assumptions', size = 14 }: InfoTipProps) {
  const list = (Array.isArray(notes) ? notes : [notes]).filter(
    (n) => n && n.trim().length > 0,
  )
  if (list.length === 0) return null

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className="
            inline-flex size-5 shrink-0 items-center justify-center rounded
            text-muted transition-colors hover:text-ink2
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring
          "
        >
          <Info size={size} strokeWidth={1.75} />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-sm">
        {list.length === 1 ? (
          <p className="leading-relaxed">{list[0]}</p>
        ) : (
          <ul className="space-y-1.5">
            {list.map((note, i) => (
              <li key={i} className="flex gap-2 leading-relaxed">
                <span className="tnum shrink-0 text-muted">{String(i + 1).padStart(2, '0')}</span>
                <span>{note}</span>
              </li>
            ))}
          </ul>
        )}
      </TooltipContent>
    </Tooltip>
  )
}
