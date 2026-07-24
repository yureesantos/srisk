/* Distribution of price value — did the customer take a better or worse price
 * than the reference the market later settled around?
 *
 * Each bar is a band of price value (the signed gap between the taken price and
 * the reference price, in implied-probability terms). Bars left of zero are
 * legs taken at a worse price than the reference; bars right of zero, better.
 * The centre line at zero is where the two meet. Colouring the two sides with
 * the drift and steam series (not red/green) keeps "better/worse for the
 * customer" from being misread as "good/bad for the book" — the same move
 * can be either depending on which side of the counter you sit.
 *
 * Bins have unequal widths in the payload (fine bands near zero, coarse in the
 * tails), so the x-axis is categorical over band labels rather than a
 * continuous scale that would distort the bar widths. */

import type { EChartsOption } from 'echarts'
import { Chart } from './Chart'
import type { TableSection } from '../lib/payload'
import { SERIES } from '../theme/echarts'

interface Bin {
  lower: number
  upper: number
  legs: number
}

export function ValueHistogram({
  section,
  height = 300,
}: {
  section: TableSection<Bin>
  height?: number
}) {
  const rows = section.rows
  const labels = rows.map((b) => `${fmt(b.lower)}…${fmt(b.upper)}`)
  const data = rows.map((b) => ({
    value: b.legs,
    // A band sits on the "worse" side when its whole span is below zero.
    itemStyle: { color: b.upper <= 0 ? SERIES[1] : SERIES[0] },
  }))

  const option: EChartsOption = {
    grid: { left: 56, right: 16, top: 16, bottom: 56 },
    xAxis: {
      type: 'category',
      data: labels,
      name: 'Price value band (implied prob.)',
      nameLocation: 'middle',
      nameGap: 40,
      axisLabel: { rotate: 45, fontSize: 10, interval: 0 },
    },
    yAxis: {
      type: 'value',
      name: 'Legs',
      nameLocation: 'middle',
      nameGap: 42,
    },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = Array.isArray(params) ? params[0] : params
        const bin = rows[p.dataIndex]
        const side = bin.upper <= 0 ? 'worse than reference' : 'better than reference'
        return (
          `<div style="font-size:12px">` +
          `Value ${fmt(bin.lower)} to ${fmt(bin.upper)} — <b>${side}</b><br/>` +
          `<b>${bin.legs.toLocaleString('en-GB')}</b> legs</div>`
        )
      },
    },
    series: [
      {
        type: 'bar',
        data,
        barCategoryGap: '20%',
      },
    ],
  }

  return (
    <Chart
      option={option}
      height={height}
      ariaLabel="Histogram of price value: legs taken at a better or worse price than the reference, centred at zero."
    />
  )
}

const fmt = (v: number) => (v > 0 ? `+${v}` : `${v}`)
