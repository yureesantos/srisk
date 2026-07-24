/* Betslips per day across the whole export.
 *
 * The shape of this series is the single most important framing fact in the
 * dataset: 132 betslips trickle in across 38 days from March to May, then
 * ~77,300 land in a 16-day burst in June. Everything else in the report is
 * really a description of that June book. The operating period — days carrying
 * at least 1% of the busiest day — is shaded so the burst and the long quiet
 * tail read as what they are, and so no later chart is mistaken for describing
 * a steady-state operation.
 *
 * A single band (markArea) marks the operating window rather than colouring
 * every bar, so the eye sees one region, not sixty individually-classified
 * days. */

import type { EChartsOption } from 'echarts'
import { Chart } from './Chart'
import type { DailyRow } from '../lib/payload'
import { SERIES, MUTED } from '../theme/echarts'

export function DailyActivity({
  rows,
  height = 300,
}: {
  rows: DailyRow[]
  height?: number
}) {
  const dates = rows.map((r) => r.date)
  const betslips = rows.map((r) => r.betslips)

  const operating = rows.filter((r) => r.in_operating_period)
  const bandStart = operating[0]?.date
  const bandEnd = operating[operating.length - 1]?.date

  const option: EChartsOption = {
    grid: { left: 56, right: 20, top: 24, bottom: 40 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: {
        formatter: (v: string) => v.slice(5), // MM-DD
        fontSize: 10,
        interval: (i: number) => i % 5 === 0,
      },
    },
    yAxis: {
      type: 'value',
      name: 'Betslips / day',
      nameLocation: 'middle',
      nameGap: 42,
    },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = Array.isArray(params) ? params[0] : params
        const row = rows[p.dataIndex]
        return (
          `<div style="font-size:12px">${row.date}<br/>` +
          `<b>${row.betslips.toLocaleString('en-GB')}</b> betslips · ` +
          `${row.legs.toLocaleString('en-GB')} legs<br/>` +
          `${row.in_operating_period ? 'Operating period' : 'Pre-launch tail'}</div>`
        )
      },
    },
    series: [
      {
        type: 'bar',
        data: betslips,
        itemStyle: { color: SERIES[0] },
        barMaxWidth: 14,
        markArea:
          bandStart && bandEnd
            ? {
                silent: true,
                itemStyle: { color: SERIES[0], opacity: 0.07 },
                label: {
                  show: true,
                  position: 'insideTop',
                  color: MUTED,
                  fontSize: 10,
                  formatter: 'operating period',
                },
                data: [[{ xAxis: bandStart }, { xAxis: bandEnd }]],
              }
            : undefined,
      },
    ],
  }

  return (
    <Chart
      option={option}
      height={height}
      ariaLabel="Betslips placed per day, with the June operating period shaded against the quiet pre-launch tail."
    />
  )
}
