/* Data quality, stated up front as its own section rather than buried in
 * footnotes. The brief asks explicitly for assumptions, limitations and
 * data-quality notes; this section is where the dataset's known imperfections
 * are laid out in the open — how rows were deduplicated, how many market labels
 * never resolved, how many betslips carry no currency, how player names were
 * recovered, and the ceiling on in-play share. A reader should be able to
 * discount any figure in the report by the caveats collected here, without
 * having to reverse-engineer them. */

import { ClipboardCheck } from 'lucide-react'
import { payload } from '../lib/payload'
import { Section } from '../components/Section'
import { InfoTip } from '../components/InfoTip'
import { Funnel, type FunnelStep } from '../charts/Funnel'
import { int, pct } from '../lib/format'

export function DataQuality() {
  const dq = payload.data_quality
  const dedup = dq.dedup
  const player = dq.player_resolution

  // `rows_raw` and `exact_dups_removed` ship per source file ({file: count});
  // the funnel wants the total across both exports.
  const sumByFile = (block: unknown): number =>
    Object.values((block ?? {}) as Record<string, number>).reduce(
      (a, b) => a + b,
      0,
    )
  const rawTotal = sumByFile(dedup.rows_raw)
  const exactDupsTotal = sumByFile(dedup.exact_dups_removed)

  const dedupSteps: FunnelStep[] = [
    { label: 'Raw rows across both exports', count: rawTotal },
    {
      label: 'After exact-duplicate removal',
      count: rawTotal - exactDupsTotal,
      note: 'exact duplicate rows',
    },
    {
      label: 'After cross-file de-overlap',
      count: dedup.legs as number,
      note: 'rows present in both exports',
      terminal: true,
    },
  ]

  return (
    <Section
      id="data_quality"
      title="Data quality & assumptions"
      icon={ClipboardCheck}
    >
      <div className="mb-8">
        <h3 className="mb-3 flex items-center gap-1.5 text-[13px] font-semibold uppercase tracking-wide text-muted">
          Deduplication funnel
          <InfoTip notes={dedup.notes[0] as string} />
        </h3>
        <Funnel steps={dedupSteps} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <QualityCard
          title="Player resolution"
          headline={pct(player.coverage as number, 2)}
          sub={`of player-centric legs resolved to ${int(player.distinct_players as number)} distinct players`}
          note={player.notes[0] as string}
        />
        <QualityCard
          title="Unresolved market templates"
          headline={pct(dq.placeholders.share as number, 1)}
          sub={`${int(dq.placeholders.legs_with_placeholder as number)} legs still carry a template placeholder`}
          note={dq.placeholders.notes[0] as string}
        />
        <QualityCard
          title="Betslips without a currency"
          headline={int(dq.currency_unresolved.betslips as number)}
          sub={`${int(dq.currency_unresolved.legs as number)} legs — never folded into a currency total`}
          note={dq.currency_unresolved.notes[0] as string}
        />
        <QualityCard
          title="In-play share (upper bound)"
          headline={pct(dq.inplay_bound.share as number, 2)}
          sub="inferred from placement time, not a live flag"
          note={dq.inplay_bound.notes[0] as string}
        />
        <QualityCard
          title="Betslip identity"
          headline={int(dq.betslip_key.collision_legs as number)}
          sub="legs where the identity key collided and was split"
          note={dq.betslip_key.notes[0] as string}
        />
        <QualityCard
          title="Cross-file overlap"
          headline={int(dedup.cross_file_overlap as number)}
          sub="rows found in both exports before de-overlap"
          note="The two exports are partially disjoint, not one a copy of the other."
        />
      </div>
    </Section>
  )
}

function QualityCard({
  title,
  headline,
  sub,
  note,
}: {
  title: string
  headline: string
  sub: string
  note: string
}) {
  return (
    <div className="rounded-xl border border-grid bg-surface/50 p-4">
      <div className="text-[12px] font-medium uppercase tracking-wide text-muted">
        {title}
      </div>
      <div className="tnum mt-1.5 text-2xl font-semibold text-ink">{headline}</div>
      <div className="mt-1 text-[13px] leading-snug text-ink2">{sub}</div>
      <div className="mt-3 border-t border-grid pt-3 text-[12px] leading-relaxed text-muted">
        {note}
      </div>
    </div>
  )
}
