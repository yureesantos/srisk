/* A single measured figure with its label and, where it matters, its grain.
 *
 * Not the hero-metric template (big gradient number, tiny label, three
 * supporting stats): those decorate. These inform. A `Stat` is a label, a
 * value in tabular figures, and an optional sub-line that names the grain or
 * the caveat. Placed in a plain flex row (`StatRow`), never a card grid — a
 * grid of identical stat cards is the SaaS reflex the brief rules out.
 *
 * Multi-currency values arrive as separate lines (one per currency), never a
 * summed total: money does not cross a currency in this dataset (ADR-0001). */

import type { ComponentType, ReactNode } from 'react'
import type { LucideProps } from 'lucide-react'
import { InfoTip } from './InfoTip'

interface StatProps {
  label: string
  /** Pre-formatted by the caller via lib/format — this component never computes. */
  value: ReactNode
  /** Grain, unit, or the one caveat that changes how to read the number. */
  sub?: string
  /** Emphasis for the one or two figures that carry the section. */
  emphasis?: boolean
}

export function Stat({ label, value, sub, emphasis }: StatProps) {
  return (
    <div className="min-w-0">
      <div className="text-[12px] font-medium uppercase tracking-wide text-muted">
        {label}
      </div>
      <div
        className={`tnum mt-1 leading-none text-ink ${
          emphasis ? 'text-3xl font-semibold' : 'text-2xl font-medium'
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-1.5 text-[12px] leading-snug text-ink2">{sub}</div>}
    </div>
  )
}

/** Stats in a row that wraps, divided by hairlines — no card grid. */
export function StatRow({ children }: { children: ReactNode }) {
  return (
    <div
      className="
        flex flex-wrap gap-x-10 gap-y-6
        rounded-(--radius-panel) border border-border bg-surface/50 px-6 py-5
        shadow-[var(--shadow-raise)]
      "
    >
      {children}
    </div>
  )
}

type Accent = 's1' | 's2' | 's3' | 's4' | 'bronze'

const TICK: Record<Accent, string> = {
  s1: 'bg-s1',
  s2: 'bg-s2',
  s3: 'bg-s3',
  s4: 'bg-s4',
  bronze: 'bg-bronze',
}

export interface KpiDelta {
  /** Direction glyph; null = no meaningful direction (shown grey, no arrow). */
  dir: 'up' | 'down' | null
  text: string
  /** true → this direction is good for the book (green); false → bad (amber). */
  good?: boolean
}

interface KpiCardProps {
  icon: ComponentType<LucideProps>
  label: string
  value: ReactNode
  accent?: Accent
  /** A delta / secondary read, right of the value. */
  delta?: KpiDelta
  /** Fills the card body — a sparkline, currency lines, dots, a share bar. */
  visual?: ReactNode
  /** One-line read at the foot (mono). */
  micro?: ReactNode
  /** Assumptions / caveats, folded behind an info icon. */
  info?: string | string[]
}

/* A cockpit tile. Dense by design: every row carries a read — accent tick +
 * label + info, value + delta, a data visual (sparkline / lines / dots), and a
 * mono microline. No empty half. Not the hero-metric template: the visual row
 * differs per tile by what the data affords, so the tiles never repeat one
 * icon+heading+text shape. The accent tick encodes category, not decoration. */
export function KpiCard({
  icon: Icon,
  label,
  value,
  accent = 's1',
  delta,
  visual,
  micro,
  info,
}: KpiCardProps) {
  return (
    <div
      className="
        flex min-w-0 flex-col gap-2 rounded-lg border border-border bg-surface
        p-3 shadow-[var(--shadow-raise)] transition-colors hover:border-white/15
      "
    >
      <div className="flex items-center gap-2">
        <span className={`h-3 w-[3px] shrink-0 rounded-full ${TICK[accent]}`} aria-hidden />
        <Icon size={13} strokeWidth={2} className="shrink-0 text-muted" />
        <span className="min-w-0 flex-1 truncate text-[10px] font-semibold uppercase tracking-wide text-muted">
          {label}
        </span>
        {info && <InfoTip notes={info} size={13} />}
      </div>

      <div className="flex items-end justify-between gap-2">
        <div className="tnum min-w-0 text-[22px] font-semibold leading-none tracking-tight text-ink">
          {value}
        </div>
        {delta && <DeltaChip {...delta} />}
      </div>

      {visual && <div className="min-h-[30px]">{visual}</div>}

      {micro && (
        <div className="tnum truncate text-[11px] leading-none text-muted">{micro}</div>
      )}
    </div>
  )
}

function DeltaChip({ dir, text, good }: KpiDelta) {
  const colour =
    dir === null
      ? 'text-muted'
      : good
        ? 'text-good'
        : 'text-serious'
  const glyph = dir === 'up' ? '▲' : dir === 'down' ? '▼' : ''
  return (
    <span className={`tnum flex shrink-0 items-center gap-1 text-[11px] ${colour}`}>
      {glyph && <span aria-hidden>{glyph}</span>}
      {text}
    </span>
  )
}

/** The cockpit KPI strip: dense, one row on wide screens, wraps on narrow. */
export function KpiGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
      {children}
    </div>
  )
}
