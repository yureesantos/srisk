/* The artifact contract, typed.
 *
 * Shapes here mirror what `src/pipeline.py` emits. The dashboard performs no
 * business arithmetic: every figure below is already computed and already
 * rounded upstream, and this layer only reads it. A number that needs
 * calculating is a pipeline bug, not a component feature. */

import raw from '../data/payload.json'

/** Money never crosses a currency, so it never arrives as a bare total. */
export interface MoneyBlock {
  by_currency: Record<string, number>
  unresolved_rows: number
  unresolved_units: number
}

export interface Truncation {
  total_rows: number
  shipped_rows: number
  ranked_by: string
  /** Optional detail: some tables ship counts only, others describe the
   *  omitted range and the stake it carried. */
  omitted?: {
    rows: number
    range?: [number, number]
    described_by?: string
    stake?: MoneyBlock
  }
  full_table: string
}

/** Every table declares the grain its numbers were aggregated at. */
export type Grain = 'betslip' | 'leg'

export interface TableSection<Row = Record<string, unknown>> {
  id: string
  title: string
  grain: Grain
  rows: Row[]
  notes: string[]
  truncation: Truncation | null
}

export interface VerifyRef {
  section: string
  select: Record<string, string | number | null>
  note: string
}

export interface BreakdownRow {
  key: string
  label: string
  legs?: number
  betslips: number
  share: number
  turnover: MoneyBlock
}

export interface PhaseRow {
  phase: string
  is_pre_match: boolean
  legs: number
  share: number
  betslips: number
  turnover: MoneyBlock
}

export interface DailyRow {
  date: string
  betslips: number
  legs: number
  turnover: MoneyBlock
  in_operating_period: boolean
}

export interface GiniBlock {
  gini: number | null
  lorenz: [number, number][]
  top_shares: Record<string, number>
  n_units: number
  note?: string
}

export interface MovementRow {
  fixture: string
  market_normalised: string
  Player: string
  Option: string
  first_price: number
  last_price: number
  implied_prob_move: number
  legs: number
  distinct_uids: number
  turnover_within: number | null
  currency: string | null
  turnover_is_mixed_currency: boolean
}

export interface WindowRow {
  Uid: string
  uid_format: string
  region?: string
  betslips?: number
  legs?: number
  span_days?: number
  priced_units: number
  beats: number
  beat_rate: number
  wilson_lb: number
  p_value: number | null
  fdr_pass: boolean
  flagged: boolean
  dominant_currency: string | null
  stake_weighted_price_value: number | null
  mean_price_value?: number
  distinct_fixtures?: number
  distinct_markets?: number
  top_market?: string
  late_share?: number
  inplay_share?: number
  simple_share?: number
  has_same_second_clusters?: boolean
  verify_ref?: VerifyRef
}

export interface Payload {
  meta: {
    artifact: string
    schema_version: number
    generated_at: string
    dataset_fingerprint: string
    payload_hash: string
    environment: Record<string, string>
    sections: Record<
      string,
      { artifact: string; path: string[]; grain: Grain | null; title: string }
    >
  }
  overview: {
    universe: {
      id: string
      title: string
      rows_raw_total: number
      legs: number
      betslips: number
      fixtures: number
      competitions: number
      date_min: string
      date_max: string
      notes: string[]
    }
    turnover: {
      id: string
      title: string
      grain: Grain
      turnover: MoneyBlock
      ggr: MoneyBlock
      inflation_leg_vs_betslip: Record<string, number>
      notes: string[]
    }
    monthly_betslips: {
      id: string
      title: string
      grain: Grain
      rows: { month: string; betslips: number }[]
      notes: string[]
    }
  }
  data_quality: Record<
    string,
    { id: string; title: string; notes: string[] } & Record<string, unknown>
  >
  flow: {
    by_market: TableSection<BreakdownRow>
    by_competition: TableSection<BreakdownRow>
    by_fixture: TableSection<BreakdownRow>
    by_region: TableSection<BreakdownRow>
    by_bet_type: TableSection<BreakdownRow>
    by_selection: TableSection<BreakdownRow>
    by_player: TableSection<BreakdownRow>
  }
  timing: {
    phases: TableSection<PhaseRow>
    daily: TableSection<DailyRow>
  }
  prices: {
    report: {
      pre_match_legs: number
      inplay_legs_excluded: number
      eligible_legs: number
      eligible_share_of_all: number
      no_later_observation: number
      reference_from_other_uid: number
      reference_from_same_uid: number
      groups_total: number
      groups_with_variation: number
      groups_for_movement: number
      steamers: number
      drifters: number
      population_beat_rate: number
      notes: string[]
    }
    movement: {
      id: string
      title: string
      grain: Grain
      steamers: MovementRow[]
      drifters: MovementRow[]
      truncation: Truncation
      notes: string[]
    }
    value_histogram: TableSection<{ lower: number; upper: number; legs: number }>
  }
  concentration: {
    uid_windows: {
      turnover: Record<string, GiniBlock>
      betslip_count: GiniBlock
    }
    fixtures: {
      leg_count: GiniBlock
      turnover_leg_grain: Record<string, GiniBlock>
    }
    notes: string[]
  }
  anomalies: Record<string, TableSection<Record<string, never>>>
  sharp: {
    report: {
      scored_windows: number
      flag_eligible_windows: number
      flagged_windows: number
      windows_below_betslip_threshold: number
      scoring_units_total: number
      legs_in_scope: number
      own_reference_legs_excluded: number
      baseline_beat_rate_unit_grain: number
      baseline_beat_rate_leg_grain: number
      median_units_per_window: number
      fdr_q: number
      expected_false_discoveries: number
      flags_under_raw_alpha: number
      flags_under_top_decile: number
      turnover_of_scored_windows: MoneyBlock
      multi_currency_windows: number
      notes: string[]
    }
    flagged_windows: TableSection<WindowRow>
    eligible_windows: TableSection<WindowRow>
  }
}

export const payload = raw as unknown as Payload

/** Mirrors `pipeline.resolve_ref`: string equality on every select pair. */
export function resolveRef(ref: VerifyRef): {
  section: TableSection | null
  matches: Record<string, unknown>[]
} {
  const entry = payload.meta.sections[ref.section]
  if (!entry) return { section: null, matches: [] }

  let node: unknown = payload
  for (const step of entry.path) {
    node = (node as Record<string, unknown>)?.[step]
  }

  const section = node as TableSection | null
  const rows = section?.rows ?? []
  const matches = rows.filter((row) =>
    Object.entries(ref.select).every(
      ([key, value]) => String((row as Record<string, unknown>)[key]) === String(value),
    ),
  )
  return { section: section ?? null, matches }
}

export function sectionTitle(id: string): string {
  return payload.meta.sections[id]?.title ?? id
}
