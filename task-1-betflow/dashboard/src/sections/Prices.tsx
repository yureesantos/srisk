/* Price value and price movement — did customers take good prices, and where
 * did the market move after they did?
 *
 * Two distinct questions the brief asks together. Price VALUE compares each
 * taken price against a reference price the same selection settled around
 * later, across the eligible population — the histogram shows whether the book
 * priced ahead of or behind its customers on average. Price MOVEMENT tracks
 * selections whose price shifted materially between first and last observation:
 * steamers shortened (backed in), drifters lengthened. The eligibility funnel
 * makes the population honest — most legs can't be priced this way (in-play, no
 * later observation, no variation), and the funnel says so rather than quietly
 * dropping them. */

import { TrendingUp } from 'lucide-react'
import { payload, type MovementRow } from '../lib/payload'
import { Section, GrainBadge } from '../components/Section'
import { Subhead } from '../components/Prose'
import { Stat, StatRow } from '../components/Stat'
import { ValueHistogram } from '../charts/ValueHistogram'
import { Funnel, type FunnelStep } from '../charts/Funnel'
import { Table, type Column } from '../components/Table'
import { Delta } from '../components/cells'
import { int, pct, price, money } from '../lib/format'

export function Prices() {
  const r = payload.prices.report
  const hist = payload.prices.value_histogram
  const mv = payload.prices.movement

  const funnel: FunnelStep[] = [
    { label: 'Pre-match legs', count: r.pre_match_legs },
    { label: 'Eligible for pricing', count: r.eligible_legs, note: 'in-play or no comparable reference' },
    { label: 'Groups with price variation', count: r.groups_with_variation, note: 'price never moved' },
    { label: 'Groups used for movement', count: r.groups_for_movement, note: 'below evidence threshold', terminal: true },
  ]

  const movementCols: Column<MovementRow>[] = [
    { key: 'fixture', header: 'Fixture', render: (m) => <span className="text-ink">{m.fixture}</span> },
    { key: 'market', header: 'Market / selection', render: (m) => (
      <span className="text-ink2">{m.market_normalised}<span className="text-muted"> · {m.Option}</span></span>
    ) },
    { key: 'first', header: 'First', numeric: true, render: (m) => price(m.first_price) },
    { key: 'last', header: 'Last', numeric: true, render: (m) => price(m.last_price) },
    { key: 'move', header: 'Implied Δ', numeric: true, render: (m) => <Delta value={m.implied_prob_move} /> },
    { key: 'legs', header: 'Legs', numeric: true, render: (m) => int(m.legs) },
    { key: 'turnover', header: 'Turnover in window', numeric: true, render: (m) =>
        m.turnover_within === null
          ? <span className="text-muted" title="mixed currency — not summed">mixed</span>
          : money(m.turnover_within, m.currency) },
  ]

  return (
    <Section
      id="prices"
      title="Price value & movement"
      icon={TrendingUp}
      info={[...r.notes, ...mv.notes]}
      aside={<GrainBadge grain="leg" />}
    >
      <StatRow>
        <Stat label="Eligible legs" value={int(r.eligible_legs)} sub={`${pct(r.eligible_share_of_all, 0)} of all legs`} emphasis />
        <Stat label="Population beat rate" value={pct(r.population_beat_rate, 1)} sub="took better than reference" />
        <Stat label="Steamers" value={int(r.steamers)} sub="price shortened materially" />
        <Stat label="Drifters" value={int(r.drifters)} sub="price lengthened materially" />
      </StatRow>

      <div className="mt-8 grid gap-8 lg:grid-cols-2">
        <div>
          <Subhead>How the pricing population narrows</Subhead>
          <Funnel steps={funnel} />
        </div>
        <div>
          <Subhead>Distribution of price value</Subhead>
          <ValueHistogram section={hist} />
        </div>
      </div>

      <Subhead>Largest price moves</Subhead>
      <Table
        sectionId="prices.movement"
        columns={movementCols}
        rows={[...mv.steamers, ...mv.drifters]}
        truncation={mv.truncation}
        rowKey={(m) => `${m.fixture}-${m.market_normalised}-${m.Option}`}
        caption="Largest price movements by implied probability"
      />
    </Section>
  )
}
