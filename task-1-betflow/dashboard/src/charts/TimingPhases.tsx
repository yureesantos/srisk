/* When the money comes in, relative to kick-off.
 *
 * Each bar is a time phase — from "more than 7 days before" down through the
 * hours before kick-off and into the in-play periods after it. Reading top to
 * bottom walks the clock toward the match and past it. The pre-match phases
 * carry the primary series; the in-play phases are drawn in the drift colour
 * and separated by a rule, because in-play here is an upper-bound proxy (we
 * infer it from timing, not a live flag) and shouldn't be read with the same
 * confidence as the pre-match split.
 *
 * Horizontal bars, because the phase labels are sentences — rotating them
 * vertically would make the chart unreadable, and the label is the point. */

import type { EChartsOption } from 'echarts'
import { Chart } from './Chart'
import type { PhaseRow } from '../lib/payload'
import { SERIES, MUTED } from '../theme/echarts'

export function TimingPhases({
  rows,
  height = 360,
}: {
  rows: PhaseRow[]
  height?: number
}) {
  // ECharts stacks category axes bottom-up; reverse so the earliest phase sits
  // at the top and the reading order matches the clock.
  const ordered = [...rows].reverse()
  const labels = ordered.map((r) => r.phase)
  const data = ordered.map((r) => ({
    value: r.legs,
    itemStyle: { color: r.is_pre_match ? SERIES[0] : SERIES[1] },
  }))

  // Boundary between the last pre-match phase and the first in-play one, drawn
  // as a rule so the proxy split is explicit.
  const firstInplayFromTop = rows.findIndex((r) => !r.is_pre_match)
  const boundaryIndex =
    firstInplayFromTop === -1 ? -1 : ordered.length - firstInplayFromTop - 0.5

  const option: EChartsOption = {
    grid: { left: 220, right: 56, top: 8, bottom: 32 },
    xAxis: {
      type: 'value',
      name: 'Legs',
      nameLocation: 'middle',
      nameGap: 26,
    },
    yAxis: {
      type: 'category',
      data: labels,
      axisLabel: { fontSize: 11, color: MUTED, width: 210, overflow: 'truncate' },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const p = Array.isArray(params) ? params[0] : params
        const row = ordered[p.dataIndex]
        return (
          `<div style="font-size:12px">${row.phase}<br/>` +
          `<b>${row.legs.toLocaleString('en-GB')}</b> legs · ` +
          `<b>${(row.share * 100).toFixed(1)}%</b> of pre-match+in-play<br/>` +
          `${row.is_pre_match ? 'Pre-match' : 'In-play (timing proxy)'}</div>`
        )
      },
    },
    series: [
      {
        type: 'bar',
        data,
        label: {
          show: true,
          position: 'right',
          color: MUTED,
          fontSize: 11,
          fontFamily: 'ui-monospace, monospace',
          formatter: (p) => `${((p.value as number) / 1000).toFixed(1)}k`,
        },
        markLine:
          boundaryIndex < 0
            ? undefined
            : {
                silent: true,
                symbol: 'none',
                lineStyle: { color: MUTED, type: 'dashed', width: 1 },
                label: {
                  show: true,
                  position: 'insideEndTop',
                  formatter: 'kick-off',
                  color: MUTED,
                  fontSize: 10,
                },
                data: [{ yAxis: boundaryIndex }],
              },
      },
    ],
  }

  return (
    <Chart
      option={option}
      height={height}
      ariaLabel="Betting legs by time phase relative to kick-off, pre-match phases separated from in-play."
    />
  )
}
