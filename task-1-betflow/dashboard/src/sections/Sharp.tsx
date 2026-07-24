/* Sharp behaviour — the report's analytical core, and the one it is most
 * careful about. The question a trader actually wants answered is "which
 * customers are consistently beating our prices?", and the honest answer
 * requires resisting the obvious mistake: rank everyone by beat rate and call
 * the top decile sharp. That flags 10% of any population, including pure noise.
 *
 * Instead each customer window is a hypothesis test. Under the null (no edge)
 * the number of times a window beats the reference is binomial around the
 * population rate; a window is flagged only if its beat count is too high to be
 * chance, AND survives a Benjamini-Hochberg correction for having tested
 * hundreds of windows (ADR-0006). The scatter shows why this matters — the
 * flagged points are the ones whose edge holds up as the evidence grows, not
 * the lucky short windows near the top-left. Every flagged window links back to
 * the exact counts behind its test. */

import { Crosshair } from 'lucide-react'
import { payload, type WindowRow } from '../lib/payload'
import { Section, GrainBadge } from '../components/Section'
import { Subhead } from '../components/Prose'
import { Stat, StatRow } from '../components/Stat'
import { SharpScatter } from '../charts/SharpScatter'
import { Funnel, type FunnelStep } from '../charts/Funnel'
import { Table, type Column } from '../components/Table'
import { VerifyButton } from '../components/VerifyButton'
import { int, pct, pValue, days } from '../lib/format'

export function Sharp() {
  const r = payload.sharp.report
  const flagged = payload.sharp.flagged_windows
  const eligible = payload.sharp.eligible_windows

  const funnel: FunnelStep[] = [
    { label: 'Windows scored', count: r.scored_windows },
    { label: 'Flag-eligible (≥ 20 priced units)', count: r.flag_eligible_windows, note: 'too few priced units to test' },
    { label: 'Flagged sharp (FDR-controlled)', count: r.flagged_windows, note: 'edge within chance', terminal: true },
  ]

  const cols: Column<WindowRow>[] = [
    { key: 'uid', header: 'Customer', render: (w) => (
      <span className="text-ink">Uid {w.Uid}{w.region ? <span className="text-muted"> · {w.region}</span> : null}</span>
    ) },
    { key: 'beat', header: 'Beats / units', numeric: true, render: (w) => `${w.beats}/${w.priced_units}` },
    { key: 'rate', header: 'Beat rate', numeric: true, render: (w) => pct(w.beat_rate, 1) },
    { key: 'wilson', header: 'Wilson LB', numeric: true, render: (w) => pct(w.wilson_lb, 1) },
    { key: 'p', header: 'p-value', numeric: true, render: (w) => pValue(w.p_value) },
    { key: 'span', header: 'Span', numeric: true, render: (w) => days(w.span_days) },
    { key: 'market', header: 'Top market', render: (w) => <span className="text-ink2">{w.top_market ?? '—'}</span> },
    { key: 'verify', header: '', render: (w) => (w.verify_ref ? <VerifyButton refTo={w.verify_ref} /> : null) },
  ]

  return (
    <Section
      id="sharp"
      title="Sharp behaviour"
      icon={Crosshair}
      info={r.notes}
      aside={<GrainBadge grain="betslip" />}
    >
      <StatRow>
        <Stat label="Windows tested" value={int(r.flag_eligible_windows)} sub={`of ${int(r.scored_windows)} scored`} />
        <Stat label="Flagged sharp" value={int(r.flagged_windows)} sub={`FDR q = ${pct(r.fdr_q, 0)}`} emphasis />
        <Stat label="Expected false flags" value={r.expected_false_discoveries.toFixed(1)} sub="built into the threshold" />
        <Stat label="Baseline beat rate" value={pct(r.baseline_beat_rate_unit_grain, 1)} sub="the no-edge null" />
      </StatRow>

      <Subhead>Evidence weight vs beat rate</Subhead>
      <SharpScatter
        windows={eligible.rows}
        baseline={r.baseline_beat_rate_unit_grain}
        sectionId="sharp.eligible_windows"
      />

      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] lg:items-start">
        <div>
          <Subhead>How the population narrows to a flag</Subhead>
          <Funnel steps={funnel} />
        </div>
        <div>
          <Subhead>Flagged windows</Subhead>
          <Table
            sectionId="sharp.flagged_windows"
            columns={cols}
            rows={flagged.rows}
            truncation={flagged.truncation}
            rowKey={(w) => w.Uid}
            caption="Customer windows flagged as statistically sharp"
          />
        </div>
      </div>
    </Section>
  )
}
