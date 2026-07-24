/* Assumptions, limitations and data-quality caveats attached to a figure.
 *
 * Every table and report block in the payload carries a `notes: string[]`. The
 * brief asks for assumptions and limitations to travel *with* the numbers, not
 * in a footnote nobody reads — so notes render inline, directly under the thing
 * they qualify, open by default. A trader should never have to hunt for the
 * caveat that changes how a number reads.
 *
 * Deliberately not a coloured callout with a side-stripe: caveats here are the
 * norm, not an alarm. A quiet bordered panel with a mono marker reads as
 * "here's what shaped this number", which is the honest register. */

interface NotesProps {
  notes: string[]
  /** Optional heading override; defaults to the neutral "Notes". */
  label?: string
}

export function Notes({ notes, label = 'Notes' }: NotesProps) {
  const items = notes.filter((n) => n && n.trim().length > 0)
  if (items.length === 0) return null

  return (
    <div className="mt-4 rounded-lg border border-grid bg-surface/60 px-4 py-3">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
        {label}
      </div>
      <ul className="space-y-1.5">
        {items.map((note, i) => (
          <li key={i} className="flex gap-2.5 text-[13px] leading-relaxed text-ink2">
            <span className="tnum mt-px shrink-0 text-muted" aria-hidden>
              {String(i + 1).padStart(2, '0')}
            </span>
            <span className="min-w-0">{note}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
