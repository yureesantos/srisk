/* The cockpit header — the first thing an operator sees, replacing the old
 * prose "book at a glance". No title, no standfirst, no paragraphs: a dense KPI
 * strip in the desk's own language (turnover, GGR, margin, sharp flags), each
 * tile carrying a trend from the daily series, followed by a compact daily tape.
 *
 * The one framing fact that must not be lost — this is a ~23-day June book, not
 * a four-month series — survives as a chip on the tape and an info affordance,
 * because it changes how every figure reads. It is load-bearing, so it stays
 * visible; it just is not a paragraph any more. */

import { Receipt, Rows3, Coins, Landmark, Percent, Crosshair } from 'lucide-react'
import { payload } from '../lib/payload'
import { GrainBadge } from '../components/Section'
import { KpiCard, KpiGrid } from '../components/Stat'
import { Sparkline } from '../components/Sparkline'
import { InfoTip } from '../components/InfoTip'
import { DailyActivity } from '../charts/DailyActivity'
import { useCurrency } from '../components/currency'
import { int, money, compactMoney, pct } from '../lib/format'

export function Overview() {
  const u = payload.overview.universe
  const t = payload.overview.turnover
  const daily = payload.timing.daily
  const sharp = payload.sharp.report
  const { currency } = useCurrency()

  // Sparkline fuel — the daily series, and the operating-period band within it.
  const betslipSeries = daily.rows.map((r) => r.betslips)
  const legSeries = daily.rows.map((r) => r.legs)
  const turnoverSeries = daily.rows.map((r) => r.turnover.by_currency[currency] ?? 0)
  const opIdx = daily.rows.reduce<[number, number] | null>((acc, r, i) => {
    if (!r.in_operating_period) return acc
    return acc ? [acc[0], i] : [i, i]
  }, null) ?? undefined

  // Deltas from the monthly series (two shipped numbers, shown as a read).
  const months = payload.overview.monthly_betslips.rows
  const jun = months.at(-1)?.betslips ?? 0
  const may = months.at(-2)?.betslips ?? 0

  // Selected-currency money (never summed across currency — ADR-0001).
  const turnoverCcy = t.turnover.by_currency[currency]
  const ggrCcy = t.ggr.by_currency[currency]
  const marginPct = turnoverCcy ? (ggrCcy ?? 0) / turnoverCcy : null
  const avgStake = turnoverCcy ? turnoverCcy / u.betslips : null
  const otherCcy = Object.keys(t.turnover.by_currency)
    .filter((c) => c !== currency)
    .sort()

  return (
    <section id="section-overview" aria-label="Cockpit overview" className="scroll-mt-20 pt-6 pb-8">
      <KpiGrid>
        <KpiCard
          icon={Landmark}
          accent="bronze"
          label={`Turnover · ${currency}`}
          value={compactMoney(turnoverCcy, currency)}
          visual={
            <Sparkline
              values={turnoverSeries}
              band={opIdx}
              ariaLabel={`Daily turnover in ${currency}`}
            />
          }
          micro={
            otherCcy.length
              ? `+ ${otherCcy.map((c) => compactMoney(t.turnover.by_currency[c], c)).join(' · ')}`
              : 'single currency'
          }
          info={`Exact: ${money(turnoverCcy, currency)}. Turnover is total staked in ${currency}; never summed across currencies (ADR-0001).`}
        />
        <KpiCard
          icon={Coins}
          accent="s3"
          label={`GGR · ${currency}`}
          value={compactMoney(ggrCcy, currency)}
          delta={
            marginPct !== null
              ? { dir: null, text: `${pct(marginPct, 1)} margin` }
              : undefined
          }
          visual={
            <MarginBar margin={marginPct} />
          }
          micro={avgStake !== null ? `avg stake ${money(avgStake, currency)}` : undefined}
          info={[
            'GGR is gross gaming revenue — stake minus returns — in this currency.',
            'Margin is GGR ÷ turnover for the selected currency only; never mixed across currencies (ADR-0001).',
          ]}
        />
        <KpiCard
          icon={Crosshair}
          accent="s2"
          label="Sharp flagged"
          value={`${int(sharp.flagged_windows)}`}
          delta={{ dir: null, text: `of ${int(sharp.flag_eligible_windows)}` }}
          visual={<FlagDots flagged={sharp.flagged_windows} />}
          micro={`q=${pct(sharp.fdr_q, 0)} · ~${sharp.expected_false_discoveries.toFixed(1)} false`}
          info="Customer windows beating the reference price by more than chance, corrected for testing many at once (Benjamini-Hochberg). Not a leaderboard — a significance test."
        />
        <KpiCard
          icon={Receipt}
          accent="s1"
          label="Betslips"
          value={int(u.betslips)}
          delta={{ dir: 'up', text: `Jun ${int(jun)}`, good: true }}
          visual={
            <Sparkline values={betslipSeries} band={opIdx} ariaLabel="Daily betslips" />
          }
          micro={`vs May ${int(may)} · ${daily.rows.length} days`}
        />
        <KpiCard
          icon={Rows3}
          accent="s4"
          label="Selections"
          value={int(u.legs)}
          delta={{
            dir: null,
            text: `${(t.inflation_leg_vs_betslip[currency] ?? 1).toFixed(2)}×`,
          }}
          visual={<Sparkline values={legSeries} band={opIdx} ariaLabel="Daily selections" />}
          micro={`legs per betslip (${currency})`}
        />
        <KpiCard
          icon={Percent}
          accent="s3"
          label="Fixtures"
          value={int(u.fixtures)}
          delta={{ dir: null, text: `${int(u.competitions)} comps` }}
          visual={<ShareBarMini share={payload.flow.by_fixture.rows[0]?.share ?? 0} />}
          micro={`top ${pct(payload.flow.by_fixture.rows[0]?.share ?? 0, 1)} · ${payload.flow.by_fixture.rows[0]?.label ?? ''}`}
        />
      </KpiGrid>

      {/* Daily tape — the shape of the book, with the framing fact pinned. */}
      <div className="mt-4 rounded-lg border border-border bg-surface/50 p-4 shadow-[var(--shadow-raise)]">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">
              Activity per day
            </span>
            <GrainBadge grain="betslip" />
          </div>
          <div className="flex items-center gap-2 rounded-full border border-border bg-raised px-2.5 py-1">
            <span className="size-1.5 rounded-full bg-s1" aria-hidden />
            <span className="text-[11px] text-ink2">16-day June book · Mar–May tail = 132 slips</span>
            <InfoTip notes={[...u.notes, ...daily.notes]} size={13} />
          </div>
        </div>
        <DailyActivity rows={daily.rows} height={200} />
      </div>
    </section>
  )
}

/* A margin gauge — GGR as a share of turnover, the book's headline ratio. */
function MarginBar({ margin }: { margin: number | null }) {
  if (margin === null) return <div className="min-h-[30px]" />
  const w = Math.max(0, Math.min(1, margin)) * 100
  return (
    <div className="flex h-[30px] flex-col justify-center gap-1">
      <div className="h-2 w-full overflow-hidden rounded-full bg-raised">
        <div className="h-full rounded-full bg-s3" style={{ width: `${w}%` }} aria-hidden />
      </div>
      <span className="tnum text-[10px] text-muted">hold {pct(margin, 1)}</span>
    </div>
  )
}

/* One dot per flagged window — the count made visible. */
function FlagDots({ flagged }: { flagged: number }) {
  return (
    <div className="flex min-h-[30px] flex-wrap content-center gap-1">
      {Array.from({ length: flagged }).map((_, i) => (
        <span key={i} className="size-2 rounded-full bg-s2" aria-hidden />
      ))}
    </div>
  )
}

/* A share of the whole, as a thin bar — the top fixture's grip on the book. */
function ShareBarMini({ share }: { share: number }) {
  const w = Math.max(0, Math.min(1, share)) * 100
  return (
    <div className="flex h-[30px] items-center">
      <div className="h-2 w-full overflow-hidden rounded-full bg-raised">
        <div className="h-full rounded-full bg-s4/80" style={{ width: `${Math.max(w, 2)}%` }} aria-hidden />
      </div>
    </div>
  )
}
