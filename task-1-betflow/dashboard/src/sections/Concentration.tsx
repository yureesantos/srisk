/* How concentrated the book is — in customers and in fixtures. A book where a
 * handful of customers or fixtures carry most of the flow carries most of the
 * risk in the same places, so concentration is a risk lens, not a curiosity.
 * Two Lorenz curves make it visible; the Gini on each puts a single number on
 * the inequality for comparison over time. */

import { payload, type GiniBlock } from '../lib/payload'
import { Section } from '../components/Section'
import { Subhead } from '../components/Prose'
import { Stat, StatRow } from '../components/Stat'
import { Lorenz } from '../charts/Lorenz'
import { pct } from '../lib/format'
import { Layers } from 'lucide-react'

export function Concentration() {
  const c = payload.concentration
  const byCustomer = c.uid_windows.betslip_count
  const byFixture = c.fixtures.leg_count

  return (
    <Section
      id="concentration"
      title="Concentration of flow"
      icon={Layers}
      info={c.notes}
    >
      <StatRow>
        <TopShare block={byCustomer} label="Top 1% of customers" k="top_1pct" />
        <TopShare block={byCustomer} label="Top 10% of customers" k="top_10pct" />
        <TopShare block={byFixture} label="Top 1% of fixtures" k="top_1pct" />
        <TopShare block={byFixture} label="Top 10% of fixtures" k="top_10pct" />
      </StatRow>

      <div className="mt-8 grid gap-8 lg:grid-cols-2">
        <div>
          <Subhead>Betslips by customer</Subhead>
          <Lorenz block={byCustomer} unitLabel="customers" quantityLabel="betslips" />
        </div>
        <div>
          <Subhead>Legs by fixture</Subhead>
          <Lorenz block={byFixture} unitLabel="fixtures" quantityLabel="legs" />
        </div>
      </div>
    </Section>
  )
}

function TopShare({
  block,
  label,
  k,
}: {
  block: GiniBlock
  label: string
  k: 'top_1pct' | 'top_10pct'
}) {
  return <Stat label={label} value={pct(block.top_shares[k], 1)} sub="of the total" />
}
