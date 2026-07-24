/* The cockpit's alert model: one adapter that turns the anomaly detectors and
 * sharp flags the pipeline already emitted into a ranked list of "what needs
 * attention now". Everything here is a read of existing payload fields — no
 * detection, no scoring, no math. It is the single source the alert strip, the
 * alerts panel, the rail badges and the topbar chip all draw from, so the
 * counts never disagree.
 *
 * Severity maps to the DESIGN.md status ramp. `signature` is a deliberate
 * fourth class for operational signatures that are NOT verdicts (same-second
 * clusters, repeated backing — ADR-0003): they are surfaced, but in neutral
 * ink, never a red/amber that would imply wrongdoing. */

import { payload, type VerifyRef } from './payload'

export type Severity = 'critical' | 'serious' | 'warning' | 'signature'

export interface Alert {
  id: string
  severity: Severity
  /** Section id this alert belongs to (drives the anchor + rail badge). */
  section: string
  /** One-line label for the panel row. */
  label: string
  /** Compact key/value cells shown after the label. */
  cells: { k: string; v: string }[]
  verifyRef?: VerifyRef
}

/** An aggregate line (e.g. "262 sharp moves") that links to a section rather
 *  than enumerating rows. */
export interface AlertAggregate {
  severity: Severity
  section: string
  count: number
  label: string
}

const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0,
  serious: 1,
  warning: 2,
  signature: 3,
}

/** Total rows behind a section, honouring truncation (shipped ≠ total). */
function totalRows(section: { rows: unknown[]; truncation?: { total_rows: number } | null }) {
  return section.truncation?.total_rows ?? section.rows.length
}

/** Individually-listed alerts (the ones worth a row each), severity-sorted. */
export function buildAlerts(): Alert[] {
  const alerts: Alert[] = []

  // Sharp flagged windows → critical. Sorted by p-value ascending downstream.
  for (const w of payload.sharp.flagged_windows.rows) {
    alerts.push({
      id: `sharp-${w.Uid}`,
      severity: 'critical',
      section: 'sharp',
      label: `Sharp customer · Uid ${w.Uid}`,
      cells: [
        ...(w.region ? [{ k: 'region', v: w.region }] : []),
        { k: 'beats', v: `${w.beats}/${w.priced_units}` },
        { k: 'rate', v: `${(w.beat_rate * 100).toFixed(1)}%` },
        {
          k: 'p',
          v:
            w.p_value === null
              ? 'n/a'
              : w.p_value < 0.001
                ? w.p_value.toExponential(1)
                : w.p_value.toFixed(4),
        },
      ],
      verifyRef: w.verify_ref,
    })
  }

  // Abnormal exposure → serious.
  for (const [i, r] of payload.anomalies.abnormal_exposure.rows.entries()) {
    const row = r as Record<string, unknown>
    alerts.push({
      id: `exposure-${i}`,
      severity: 'serious',
      section: 'anomalies',
      label: `Abnormal exposure · ${row.fixture as string}`,
      cells: [
        { k: 'selection', v: `${row.market} · ${row.selection}` },
        { k: 'share', v: `${((row.share as number) * 100).toFixed(1)}%` },
        { k: 'uids', v: `${row.distinct_uids}` },
      ],
      verifyRef: row.verify_ref as VerifyRef | undefined,
    })
  }

  // Turnover spikes → warning (low confidence by construction on a 23-day book).
  for (const [i, r] of payload.anomalies.turnover_spikes.rows.entries()) {
    const row = r as Record<string, unknown>
    alerts.push({
      id: `spike-${i}`,
      severity: 'warning',
      section: 'anomalies',
      label: `Turnover spike · ${String(row.date).slice(0, 10)}`,
      cells: [
        { k: 'currency', v: row.currency as string },
        { k: 'over', v: `${(row.excess_ratio as number).toFixed(2)}×` },
        { k: 'confidence', v: 'low' },
      ],
      verifyRef: row.verify_ref as VerifyRef | undefined,
    })
  }

  return alerts.sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])
}

/** Aggregate lines — high-count detectors surfaced as one line, not N rows. */
export function buildAggregates(): AlertAggregate[] {
  const a = payload.anomalies
  return [
    {
      severity: 'warning',
      section: 'prices',
      count: a.sharp_moves.rows.length,
      label: 'sharp price moves',
    },
    {
      severity: 'signature',
      section: 'anomalies',
      count: totalRows(a.repeat_backing),
      label: 'repeated backing',
    },
    {
      severity: 'signature',
      section: 'anomalies',
      count: totalRows(a.same_second_clusters),
      label: 'same-second clusters',
    },
  ]
}

/** Per-section counts for the rail badges (individual + aggregate). */
export function alertsBySection(): Record<string, { count: number; severity: Severity }> {
  const out: Record<string, { count: number; severity: Severity }> = {}
  const bump = (section: string, count: number, severity: Severity) => {
    const cur = out[section]
    if (!cur) out[section] = { count, severity }
    else
      out[section] = {
        count: cur.count + count,
        severity:
          SEVERITY_ORDER[severity] < SEVERITY_ORDER[cur.severity] ? severity : cur.severity,
      }
  }
  for (const al of buildAlerts()) bump(al.section, 1, al.severity)
  for (const ag of buildAggregates()) bump(ag.section, ag.count, ag.severity)
  return out
}

/** Severity summary for the strip and topbar chip. */
export function severityCounts(): Record<Severity, number> {
  const counts: Record<Severity, number> = {
    critical: 0,
    serious: 0,
    warning: 0,
    signature: 0,
  }
  for (const a of buildAlerts()) counts[a.severity] += 1
  return counts
}

export const SEVERITY_COLOR: Record<Severity, string> = {
  critical: 'var(--color-critical)',
  serious: 'var(--color-serious)',
  warning: 'var(--color-warning)',
  signature: 'var(--color-muted)',
}

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: 'Critical',
  serious: 'Serious',
  warning: 'Warning',
  signature: 'Signal',
}
