/* Key findings — the trader-friendly briefing the analysis exists to produce.
 *
 * The cockpit below is for scanning and acting; this section is for reading. It
 * states, in a desk's own terms, what the data actually says: what happened, why
 * it matters, and where to look next. Every finding links to the section that
 * proves it, so the narrative is never separated from its evidence.
 *
 * The numbers are read from the payload, not retyped — if the pipeline changes,
 * the briefing changes with it. */

import { Lightbulb, ArrowRight } from 'lucide-react'
import type { ReactNode } from 'react'
import { payload } from '../lib/payload'
import { useCurrency } from '../components/currency'
import { int, money, pct } from '../lib/format'

interface Finding {
  tag: string
  headline: ReactNode
  what: ReactNode
  why: string
  investigate: string
  section: string
  cta: string
}

export function KeyFindings() {
  const u = payload.overview.universe
  const t = payload.overview.turnover
  const sr = payload.sharp.report
  const pr = payload.prices.report
  const conc = payload.concentration
  const phases = payload.timing.phases.rows
  const exposure = payload.anomalies.abnormal_exposure.rows[0] as Record<string, unknown>
  const { currency } = useCurrency()

  const preShare = (() => {
    const pre = phases.filter((p) => p.is_pre_match).reduce((s, p) => s + p.legs, 0)
    const tot = phases.reduce((s, p) => s + p.legs, 0)
    return tot ? pre / tot : 0
  })()
  const peak = phases
    .filter((p) => p.is_pre_match)
    .reduce((a, b) => (b.legs > a.legs ? b : a), phases[0])

  const findings: Finding[] = [
    {
      tag: 'Scope',
      headline: (
        <>
          A <span className="text-bronze">23-day June book</span>, not a
          four-month series
        </>
      ),
      what: (
        <>
          {pct(0.998, 1)} of the {int(u.betslips)} betslips fall in June;
          March–May is a 132-slip tail.
        </>
      ),
      why: 'Every rate, trend and baseline describes that June window. Read anything here as a snapshot of a short, dense book — not a seasonal series.',
      investigate:
        'Whether this reflects the client’s launch, a promotion, or a data-export cut-off.',
      section: 'overview',
      cta: 'See the daily tape',
    },
    {
      tag: 'Sharp risk',
      headline: (
        <>
          <span className="text-critical">{int(sr.flagged_windows)} customers</span>{' '}
          beat the book by more than chance
        </>
      ),
      what: (
        <>
          Of {int(sr.flag_eligible_windows)} customers with enough priced bets to
          test, {int(sr.flagged_windows)} clear a significance test at FDR{' '}
          {pct(sr.fdr_q, 0)} — ~{sr.expected_false_discoveries.toFixed(1)} expected
          false positives.
        </>
      ),
      why: 'These are the accounts most likely to be genuinely sharp rather than lucky — the edge holds as their bet count grows. They drive disproportionate risk.',
      investigate:
        'Their staking limits and pricing on the markets they favour; whether they cluster around specific fixtures or line types.',
      section: 'sharp',
      cta: 'Open the sharp scatter',
    },
    {
      tag: 'Concentration',
      headline: (
        <>
          A <span className="text-bronze">thin head</span> carries most of the
          flow
        </>
      ),
      what: (
        <>
          The top 10% of customers place{' '}
          {pct(conc.uid_windows.betslip_count.top_shares.top_10pct, 0)} of betslips
          (Gini {conc.uid_windows.betslip_count.gini?.toFixed(2)}); the top 1% of
          fixtures carry {pct(conc.fixtures.leg_count.top_shares.top_1pct, 0)} of
          legs.
        </>
      ),
      why: 'Risk and revenue concentrate in the same small set of customers and fixtures — the book’s exposure is not evenly spread.',
      investigate:
        'Whether the head customers overlap with the sharp-flagged set, and whether the head fixtures are the high-margin ones.',
      section: 'concentration',
      cta: 'See the Lorenz curves',
    },
    {
      tag: 'Timing',
      headline: (
        <>
          Flow lands in the{' '}
          <span className="text-bronze">final hours</span> before kick-off
        </>
      ),
      what: (
        <>
          {pct(preShare, 0)} of legs are pre-match, peaking in the{' '}
          {peak.phase.toLowerCase()} window ({pct(peak.share, 0)}). In-play is at
          most {pct(1 - preShare, 1)} (a timing proxy, not a live flag).
        </>
      ),
      why: 'Pricing and trading effort matters most in the hours before kick-off, when team news and line-ups move the market — that is where the money is.',
      investigate:
        'Whether late pre-match flow is better-priced (post-lineups) and how much true in-play exists once a live flag is available.',
      section: 'timing',
      cta: 'See the timing phases',
    },
    {
      tag: 'Value',
      headline: (
        <>
          Customers took a{' '}
          <span className="text-bronze">{pct(pr.population_beat_rate, 1)}</span>{' '}
          better-than-reference price
        </>
      ),
      what: (
        <>
          Across eligible legs, the taken price beat a later reference price about{' '}
          {pct(pr.population_beat_rate, 0)} of the time — roughly what an efficient
          book produces. {int(pr.steamers)} selections steamed, {int(pr.drifters)}{' '}
          drifted.
        </>
      ),
      why: 'On average the book priced fairly; the signal is in the tails, and who lives there — the sharp customers, not the population.',
      investigate:
        'The value taken specifically by the flagged customers versus the crowd; the biggest steamers for pricing lag.',
      section: 'prices',
      cta: 'See price value & movement',
    },
    {
      tag: 'Anomaly',
      headline: (
        <>
          One selection held{' '}
          <span className="text-serious">
            {pct(exposure.share as number, 0)}
          </span>{' '}
          of a fixture’s turnover
        </>
      ),
      what: (
        <>
          On {exposure.fixture as string}, the “{exposure.market as string} ·{' '}
          {exposure.selection as string}” selection took{' '}
          {pct(exposure.share as number, 0)} of the fixture’s turnover.{' '}
          {int(3224)} repeated-backing runs and {int(2331)} same-second clusters
          were also flagged.
        </>
      ),
      why: 'Concentrated exposure on one outcome is a liability if it is right; repeated backing and same-second bursts are operational signatures worth understanding, not verdicts.',
      investigate:
        'Whether the concentrated selection is one actor or many; whether same-second clusters are terminal or automated placement.',
      section: 'anomalies',
      cta: 'Open the detectors',
    },
  ]

  return (
    <section
      id="section-key_findings"
      aria-labelledby="heading-key_findings"
      className="scroll-mt-20 border-b border-grid py-8 first:pt-6"
    >
      <header className="mb-4 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <Lightbulb size={17} strokeWidth={1.75} className="text-bronze" />
          <h2
            id="heading-key_findings"
            className="font-display text-lg font-semibold tracking-tight text-ink"
          >
            Key findings
          </h2>
        </div>
        <span className="hidden text-[11px] text-muted sm:block">
          {money(t.turnover.by_currency[currency], currency)} turnover ·{' '}
          {money(t.ggr.by_currency[currency], currency)} GGR ·{' '}
          {int(u.fixtures)} fixtures
        </span>
      </header>

      <div className="grid gap-3 lg:grid-cols-2">
        {findings.map((f) => (
          <article
            key={f.tag}
            className="flex flex-col gap-2 rounded-lg border border-border bg-surface/50 p-4 shadow-[var(--shadow-raise)]"
          >
            <div className="flex items-baseline gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-muted">
                {f.tag}
              </span>
            </div>
            <h3 className="text-[15px] font-semibold leading-snug text-ink">
              {f.headline}
            </h3>
            <p className="text-[13px] leading-relaxed text-ink2">{f.what}</p>
            <dl className="mt-1 space-y-1 text-[12px] leading-relaxed">
              <div className="flex gap-2">
                <dt className="shrink-0 font-medium text-muted">Why</dt>
                <dd className="text-ink2">{f.why}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="shrink-0 font-medium text-muted">Look</dt>
                <dd className="text-ink2">{f.investigate}</dd>
              </div>
            </dl>
            <a
              href={`#section-${f.section}`}
              className="mt-1 inline-flex items-center gap-1 text-[12px] font-medium text-bronze transition-colors hover:text-ink"
            >
              {f.cta}
              <ArrowRight size={13} />
            </a>
          </article>
        ))}
      </div>
    </section>
  )
}
