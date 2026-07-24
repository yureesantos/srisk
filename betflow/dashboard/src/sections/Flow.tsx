/* Where the flow goes. The brief's central question — betting flow by fixture,
 * market, team, player, selection, bet type, region — answered as one section
 * with a dimension switcher rather than seven scattered charts. The switcher
 * keeps the comparison honest: the same visual and the same columns, so moving
 * between "by market" and "by competition" compares like with like.
 *
 * Each dimension renders the flow bar-table (shape at a glance) followed by the
 * full ranked table (exact figures, every row a verify target). Grain differs
 * by dimension — some breakdowns are naturally per-selection (a market appears
 * on many legs of one betslip), others per-betslip (a region is a property of
 * the betslip) — so each states its own grain rather than pretending to a
 * single one. */

import { useState } from 'react'
import { Waypoints } from 'lucide-react'
import { payload, type BreakdownRow, type TableSection } from '../lib/payload'
import { Section, GrainBadge } from '../components/Section'
import { Tabs, TabsList, TabsTrigger } from '../components/ui/tabs'
import { FlowBars } from '../charts/FlowBars'
import { Table, type Column } from '../components/Table'
import { MoneyCell, ShareBar } from '../components/cells'
import { useCurrency } from '../components/currency'
import { int } from '../lib/format'

interface Dim {
  id: string
  label: string
  sectionId: string
  section: TableSection<BreakdownRow>
}

const DIMS: Dim[] = [
  { id: 'market', label: 'Market', sectionId: 'flow.by_market', section: payload.flow.by_market },
  { id: 'competition', label: 'Competition', sectionId: 'flow.by_competition', section: payload.flow.by_competition },
  { id: 'fixture', label: 'Fixture', sectionId: 'flow.by_fixture', section: payload.flow.by_fixture },
  { id: 'selection', label: 'Selection', sectionId: 'flow.by_selection', section: payload.flow.by_selection },
  { id: 'player', label: 'Player / team', sectionId: 'flow.by_player', section: payload.flow.by_player },
  { id: 'region', label: 'Region', sectionId: 'flow.by_region', section: payload.flow.by_region },
  { id: 'bet_type', label: 'Bet type', sectionId: 'flow.by_bet_type', section: payload.flow.by_bet_type },
]

export function Flow() {
  const [active, setActive] = useState(DIMS[0].id)
  const dim = DIMS.find((d) => d.id === active) ?? DIMS[0]
  const { section } = dim
  const { currency } = useCurrency()

  const columns: Column<BreakdownRow>[] = [
    {
      key: 'label',
      header: dim.label,
      render: (r) => <span className="text-ink">{r.label}</span>,
      filterValue: (r) => r.label,
    },
    ...(section.grain === 'leg'
      ? [
          {
            key: 'legs',
            header: 'Legs',
            numeric: true,
            render: (r: BreakdownRow) => int(r.legs),
            sortValue: (r: BreakdownRow) => r.legs ?? 0,
          } as Column<BreakdownRow>,
        ]
      : []),
    {
      key: 'betslips',
      header: 'Betslips',
      numeric: true,
      render: (r) => int(r.betslips),
      sortValue: (r) => r.betslips,
    },
    {
      key: 'share',
      header: 'Share',
      numeric: true,
      render: (r) => <ShareBar share={r.share} />,
      sortValue: (r) => r.share,
    },
    {
      key: 'turnover',
      header: 'Turnover',
      numeric: true,
      render: (r) => <MoneyCell block={r.turnover} />,
      sortValue: (r) => r.turnover.by_currency[currency] ?? -1,
    },
  ]

  return (
    <Section
      id="flow"
      title="Flow by dimension"
      icon={Waypoints}
      info={section.notes}
      aside={<GrainBadge grain={section.grain} />}
    >
      <Tabs value={active} onValueChange={setActive} className="gap-4">
        <TabsList>
          {DIMS.map((d) => (
            <TabsTrigger key={d.id} value={d.id}>
              {d.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <FlowBars sectionId={dim.sectionId} rows={section.rows} dimensionLabel={dim.label} />
        <Table
          sectionId={dim.sectionId}
          columns={columns}
          rows={section.rows}
          truncation={section.truncation}
          rowKey={(r) => r.key}
          caption={`Flow by ${dim.label.toLowerCase()}`}
        />
      </div>
    </Section>
  )
}
