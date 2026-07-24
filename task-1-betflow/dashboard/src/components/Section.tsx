/* A panel of the cockpit. Carries the scroll anchor the rail and the verify
 * wiring both target (`section-<id>`), a compact one-line header — icon, title,
 * an info affordance for the assumptions that used to be a paragraph, and an
 * optional right-aligned stat/control — and the content.
 *
 * Sections are the spine, so the id is load-bearing: `Shell`'s scroll-spy and
 * `verify.request` both compute `section-${id}`. */

import type { ComponentType, ReactNode } from 'react'
import type { LucideProps } from 'lucide-react'
import { Receipt, Rows3 } from 'lucide-react'
import { InfoTip } from './InfoTip'

interface SectionProps {
  id: string
  title: string
  icon?: ComponentType<LucideProps>
  /** Assumptions / limitations, folded behind an info icon (was a paragraph). */
  info?: string | string[]
  /** Right-aligned slot — a grain badge, a key stat, a control. */
  aside?: ReactNode
  children: ReactNode
}

export function Section({ id, title, icon: Icon, info, aside, children }: SectionProps) {
  return (
    <section
      id={`section-${id}`}
      aria-labelledby={`heading-${id}`}
      className="scroll-mt-20 border-b border-grid py-8 first:pt-6 lg:scroll-mt-4"
    >
      <header className="mb-4 flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-2.5">
          {Icon && <Icon size={17} strokeWidth={1.75} className="shrink-0 text-muted" />}
          <h2
            id={`heading-${id}`}
            className="font-display truncate text-lg font-semibold tracking-tight text-ink"
          >
            {title}
          </h2>
          {info && <InfoTip notes={info} />}
        </div>
        {aside && <div className="flex shrink-0 items-center gap-3">{aside}</div>}
      </header>
      {children}
    </section>
  )
}

/** The grain a set of numbers was aggregated at — one bet, or one selection on
 *  a bet. Stated because the same word ("volume") means different things at
 *  each grain, and mixing them is the classic betting-analytics error. */
export function GrainBadge({ grain }: { grain: 'betslip' | 'leg' }) {
  const label = grain === 'betslip' ? 'per betslip' : 'per selection'
  const Icon = grain === 'betslip' ? Receipt : Rows3
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted"
      title={
        grain === 'betslip'
          ? 'Aggregated at betslip grain: one row per placed bet.'
          : 'Aggregated at leg grain: one row per selection within a bet.'
      }
    >
      <Icon size={12} strokeWidth={2} className="text-muted" />
      {label}
    </span>
  )
}
