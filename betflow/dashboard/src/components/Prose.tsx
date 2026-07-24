/* Subheadings inside a cockpit panel — above a chart or a table. The cockpit
 * carries no lead prose; the only text furniture left is this quiet label that
 * separates two widgets in one section. */

import type { ReactNode } from 'react'

export function Subhead({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-3 mt-6 text-[11px] font-semibold uppercase tracking-wide text-muted first:mt-0">
      {children}
    </h3>
  )
}
