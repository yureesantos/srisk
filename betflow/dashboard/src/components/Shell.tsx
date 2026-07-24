/* The page frame beneath the topbar: a fixed left rail that indexes the report,
 * and the scrolling column of sections beside it. On narrow viewports the rail
 * collapses to a horizontal strip above the content — structural
 * responsiveness, not fluid type (product register).
 *
 * The rail doubles as the reading-position indicator: `useScrollSpy` marks the
 * section currently in view, and each item carries an icon so the index reads
 * as a control surface, not a link list. */

import { useEffect, useState, type ReactNode } from 'react'
import type { LucideProps } from 'lucide-react'
import type { ComponentType } from 'react'
import { ScrollArea } from './ui/scroll-area'
import { payload } from '../lib/payload'
import { alertsBySection, SEVERITY_COLOR } from '../lib/alerts'
import { dateTime } from '../lib/format'

export interface NavItem {
  id: string
  label: string
  icon: ComponentType<LucideProps>
}

// Height of the sticky Topbar; the rail hangs directly beneath it.
const TOPBAR = 57

function useScrollSpy(ids: string[]): string | null {
  const [active, setActive] = useState<string | null>(ids[0] ?? null)

  useEffect(() => {
    const targets = ids
      .map((id) => document.getElementById(`section-${id}`))
      .filter((el): el is HTMLElement => el !== null)

    // A band across the upper third: a section is "current" once its heading
    // crosses into that band, which matches how people read top-to-bottom.
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) {
          setActive(visible[0].target.id.replace(/^section-/, ''))
        }
      },
      { rootMargin: '-15% 0px -70% 0px', threshold: 0 },
    )

    targets.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [ids])

  return active
}

export function Shell({ nav, children }: { nav: NavItem[]; children: ReactNode }) {
  const ids = nav.map((n) => n.id)
  const active = useScrollSpy(ids)

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col lg:flex-row">
      <Rail nav={nav} active={active} />
      <main className="min-w-0 flex-1 px-5 pb-32 sm:px-8 lg:px-12">{children}</main>
    </div>
  )
}

function Rail({ nav, active }: { nav: NavItem[]; active: string | null }) {
  const u = payload.overview.universe
  const badges = alertsBySection()
  const operatingDays = payload.timing.daily.rows.filter((r) => r.in_operating_period).length

  return (
    <aside
      style={{ top: TOPBAR }}
      className="
        sticky z-sticky shrink-0 self-start
        border-b border-border bg-page/85 backdrop-blur
        lg:flex lg:h-[calc(100vh-57px)] lg:w-64 lg:flex-col lg:border-b-0 lg:border-r
      "
    >
      <div className="hidden px-6 pb-2 pt-6 lg:block">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">
          Report sections
        </div>
      </div>

      <ScrollArea className="lg:min-h-0 lg:flex-1">
        <nav
          aria-label="Report sections"
          className="
            flex gap-1 overflow-x-auto px-3 py-3
            lg:flex-col lg:gap-0.5 lg:overflow-visible lg:px-3 lg:py-1
          "
        >
          {nav.map((item) => {
            const isActive = item.id === active
            const Icon = item.icon
            const badge = badges[item.id]
            return (
              <a
                key={item.id}
                href={`#section-${item.id}`}
                aria-current={isActive ? 'true' : undefined}
                className={`
                  flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2 text-[13px]
                  transition-colors duration-150 lg:shrink
                  ${
                    isActive
                      ? 'bg-raised font-medium text-ink shadow-[var(--shadow-raise)]'
                      : 'text-ink2 hover:bg-raised/60 hover:text-ink'
                  }
                `}
              >
                <Icon
                  size={16}
                  strokeWidth={1.75}
                  className={isActive ? 'text-bronze' : 'text-muted'}
                />
                <span className="flex-1 truncate">{item.label}</span>
                {badge && (
                  <span
                    className="tnum inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                    style={{
                      color: SEVERITY_COLOR[badge.severity],
                      background: `color-mix(in oklab, ${SEVERITY_COLOR[badge.severity]} 16%, transparent)`,
                    }}
                    title={`${badge.count} flagged`}
                  >
                    {badge.count > 999 ? `${(badge.count / 1000).toFixed(1)}k` : badge.count}
                  </span>
                )}
              </a>
            )
          })}
        </nav>
      </ScrollArea>

      {/* System plate: the instrument's calibration, always in view at the foot
          of the rail — what it is running on, not dead space. */}
      <div className="hidden border-t border-border px-6 py-4 lg:block">
        <div className="mb-2 text-[10px] font-medium uppercase tracking-wide text-muted">
          System
        </div>
        <dl className="space-y-1.5 text-[11px]">
          <PlateRow label="Operating">
            {operatingDays} of {payload.timing.daily.rows.length} days
          </PlateRow>
          <PlateRow label="Coverage">
            {u.fixtures.toLocaleString('en-GB')} fixtures · {u.competitions} comps
          </PlateRow>
          <PlateRow label="Detectors">5 · 4 fired</PlateRow>
          <PlateRow label="Built">
            <span title={payload.meta.payload_hash}>
              {dateTime(payload.meta.generated_at).slice(0, 10)}
            </span>
          </PlateRow>
        </dl>
      </div>
    </aside>
  )
}

function PlateRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-muted">{label}</dt>
      <dd className="tnum truncate text-ink2">{children}</dd>
    </div>
  )
}
