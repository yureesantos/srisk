/* The anomaly detectors, each as its own panel. The brief lists the patterns to
 * look for — turnover spikes, repeated backing of one selection, sharp price
 * movement, abnormal exposure — and each is a distinct detector with its own
 * grain, its own threshold, and its own confidence. They are kept separate
 * rather than merged into one "risk score" because merging would hide which
 * signal fired and why. Each panel states its detector's rule in its notes, and
 * several deliberately flag their own limitations (the spike detector is low
 * confidence by construction on a 23-day book; same-second clusters are an
 * operational signature, not fraud). Honesty about what a detector can and
 * cannot see is the point. */

import { useState, type ReactNode } from 'react'
import { Radar } from 'lucide-react'
import { payload, type TableSection } from '../lib/payload'
import { Section, GrainBadge } from '../components/Section'
import { InfoTip } from '../components/InfoTip'
import { Tabs, TabsList, TabsTrigger } from '../components/ui/tabs'
import { Table, type Column } from '../components/Table'
import { VerifyButton } from '../components/VerifyButton'
import { int, pct, price, money, dateTime, date, signedPct } from '../lib/format'

type Row = Record<string, unknown>
type Sev = 'critical' | 'serious' | 'warning' | 'signal'

const SEV_DOT: Record<Sev, string> = {
  critical: 'bg-critical',
  serious: 'bg-serious',
  warning: 'bg-warning',
  signal: 'bg-muted',
}

interface Panel {
  key: string
  section: TableSection<Row>
  blurb: string
  severity: Sev
  columns: Column<Row>[]
}

export function Anomalies() {
  const a = payload.anomalies

  const panels: Panel[] = [
    {
      key: 'repeat_backing',
      section: a.repeat_backing as TableSection<Row>,
      severity: 'signal',
      blurb:
        'One customer window backing the same selection three or more times — deliberate repetition, which can be conviction or a signal worth a second look.',
      columns: [
        col('Uid', (r) => <span className="text-ink">{r.Uid as string}</span>),
        col('Fixture', (r) => r.fixture as string),
        col('Selection', (r) => `${r.market_normalised} · ${r.Option}`),
        num('Betslips', (r) => int(r.betslips as number)),
        num('Value', (r) => signedPct(r.mean_price_value as number)),
        col('', (r) => (r.verify_ref ? <VerifyButton refTo={r.verify_ref as never} /> : null)),
      ],
    },
    {
      key: 'abnormal_exposure',
      section: a.abnormal_exposure as TableSection<Row>,
      severity: 'serious',
      blurb:
        'A single selection holding half or more of a busy fixture’s turnover — a concentration of exposure on one outcome.',
      columns: [
        col('Fixture', (r) => <span className="text-ink">{r.fixture as string}</span>),
        col('Selection', (r) => `${r.market} · ${r.selection}`),
        num('Share', (r) => pct(r.share as number, 1)),
        num('Turnover', (r) => money(r.selection_turnover as number, r.currency as string)),
        num('Uids', (r) => int(r.distinct_uids as number)),
        col('', (r) => (r.verify_ref ? <VerifyButton refTo={r.verify_ref as never} /> : null)),
      ],
    },
    {
      key: 'sharp_moves',
      section: a.sharp_moves as TableSection<Row>,
      severity: 'warning',
      blurb:
        'Selections whose price moved sharply between first and last sight with real backing behind them — where the market, or a set of customers, formed a strong view.',
      columns: [
        col('Fixture', (r) => <span className="text-ink">{r.fixture as string}</span>),
        col('Selection', (r) => `${r.market_normalised} · ${r.Option}`),
        num('First', (r) => price(r.first_price as number)),
        num('Last', (r) => price(r.last_price as number)),
        num('Implied Δ', (r) => signedPct(r.implied_prob_move as number)),
        num('Uids', (r) => int(r.distinct_uids as number)),
      ],
    },
    {
      key: 'turnover_spikes',
      section: a.turnover_spikes as TableSection<Row>,
      severity: 'warning',
      blurb:
        'Days whose turnover ran far above the operating-period baseline in their own currency. Low confidence by construction — 23 trading days is thin history.',
      columns: [
        col('Day', (r) => <span className="text-ink">{date(r.date as string)}</span>),
        col('Currency', (r) => r.currency as string),
        num('Turnover', (r) => money(r.turnover as number, r.currency as string)),
        num('Threshold', (r) => money(r.threshold as number, r.currency as string)),
        num('× over', (r) => `${(r.excess_ratio as number).toFixed(2)}×`),
        col('', (r) => (r.verify_ref ? <VerifyButton refTo={r.verify_ref as never} /> : null)),
      ],
    },
    {
      key: 'same_second_clusters',
      section: a.same_second_clusters as TableSection<Row>,
      severity: 'signal',
      blurb:
        'Bursts of legs placed within the same second — an operational signature of terminal or automated placement, not a fraud finding (ADR-0003).',
      columns: [
        col('Uid', (r) => <span className="text-ink">{r.Uid as string}</span>),
        num('Cluster', (r) => int(r.cluster_size as number)),
        num('Legs', (r) => int(r.legs as number)),
        num('Fixtures', (r) => int(r.fixtures as number)),
        num('Stake', (r) => money(r.stake as number, r.currency as string)),
        col('Placed', (r) => dateTime(r.placed_at as string)),
      ],
    },
  ]

  const [active, setActive] = useState(panels[0].key)
  const panel = panels.find((p) => p.key === active) ?? panels[0]
  const count = (p: Panel) => p.section.truncation?.total_rows ?? p.section.rows.length

  return (
    <Section
      id="anomalies"
      title="Anomaly detectors"
      icon={Radar}
      info="Five independent detectors. None is a verdict — each flags a pattern against a stated threshold and reports how much to trust it. A detector that would over-promise on this dataset says so in its own rule."
    >
      <Tabs value={active} onValueChange={setActive} className="gap-4">
        <TabsList>
          {panels.map((p) => (
            <TabsTrigger key={p.key} value={p.key}>
              <span className={`size-1.5 rounded-full ${SEV_DOT[p.severity]}`} aria-hidden />
              {p.section.title}
              <span className="tnum text-[11px] text-muted">{int(count(p))}</span>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className="mt-4">
        <div className="mb-2 flex items-start justify-between gap-4">
          <p className="max-w-[80ch] text-[13px] leading-relaxed text-ink2">{panel.blurb}</p>
          <div className="flex shrink-0 items-center gap-2 pt-0.5">
            <GrainBadge grain={panel.section.grain} />
            <InfoTip notes={panel.section.notes} label="Rule & confidence" />
          </div>
        </div>
        <Table
          sectionId={`anomalies.${panel.key}`}
          columns={panel.columns}
          rows={panel.section.rows}
          truncation={panel.section.truncation}
          rowKey={(_, i) => `${panel.key}-${i}`}
          caption={panel.section.title}
        />
      </div>
    </Section>
  )
}

/* Column builders keep the panel definitions above readable. */
function col(header: string, render: (r: Row) => ReactNode): Column<Row> {
  return { key: header || 'action', header, render }
}
function num(header: string, render: (r: Row) => ReactNode): Column<Row> {
  return { key: header, header, numeric: true, render }
}
