/* Lorenz curve — how concentrated the activity is in a few hands.
 *
 * The x-axis is the cumulative share of units (customers, or fixtures) ordered
 * smallest to largest; the y-axis is the cumulative share of the quantity they
 * account for. The straight diagonal is perfect equality — everyone the same.
 * The gap between the diagonal and the curve is inequality, and its area is the
 * Gini coefficient printed on the chart. A curve that hugs the bottom-right
 * corner means a small tail of units carries almost everything, which for a
 * book is a concentration-of-risk signal, not a curiosity.
 *
 * The equality line is drawn as data (not a markLine) so it shares the axes
 * exactly and reads as the reference it is. */

import type { EChartsOption } from 'echarts'
import { Chart } from './Chart'
import type { GiniBlock } from '../lib/payload'
import { SERIES, MUTED } from '../theme/echarts'

interface LorenzProps {
  block: GiniBlock
  /** What one unit is — "customers", "fixtures". Axis wording depends on it. */
  unitLabel: string
  /** What is being accumulated — "betslips", "turnover", "legs". */
  quantityLabel: string
  height?: number
}

export function Lorenz({
  block,
  unitLabel,
  quantityLabel,
  height = 320,
}: LorenzProps) {
  const curve = block.lorenz.map(([x, y]) => [x * 100, y * 100])
  const gini = block.gini

  const option: EChartsOption = {
    grid: { left: 52, right: 20, top: 20, bottom: 44 },
    xAxis: {
      type: 'value',
      min: 0,
      max: 100,
      name: `Cumulative share of ${unitLabel} (%)`,
      nameLocation: 'middle',
      nameGap: 28,
      axisLabel: { formatter: '{value}' },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      name: `Share of ${quantityLabel} (%)`,
      nameLocation: 'middle',
      nameGap: 38,
      axisLabel: { formatter: '{value}' },
    },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = Array.isArray(params) ? params : [params]
        const point = p.find((x) => x.seriesName === 'Lorenz') ?? p[0]
        const [x, y] = point.value as [number, number]
        return (
          `<div style="font-size:12px">` +
          `The lowest <b>${x.toFixed(0)}%</b> of ${unitLabel}<br/>` +
          `account for <b>${y.toFixed(1)}%</b> of ${quantityLabel}` +
          `</div>`
        )
      },
    },
    series: [
      {
        name: 'Equality',
        type: 'line',
        data: [
          [0, 0],
          [100, 100],
        ],
        showSymbol: false,
        lineStyle: { color: MUTED, width: 1, type: 'dashed' },
        silent: true,
        z: 1,
      },
      {
        name: 'Lorenz',
        type: 'line',
        data: curve,
        showSymbol: false,
        smooth: false,
        lineStyle: { color: SERIES[0], width: 2 },
        areaStyle: { color: SERIES[0], opacity: 0.1 },
        z: 2,
      },
    ],
    graphic:
      gini === null
        ? undefined
        : [
            {
              type: 'text',
              right: 28,
              top: 28,
              style: {
                text: `Gini ${gini.toFixed(3)}`,
                fill: SERIES[0],
                font: '600 13px Inter, sans-serif',
              },
            },
            {
              type: 'text',
              right: 28,
              top: 46,
              style: {
                text: `n = ${block.n_units.toLocaleString('en-GB')} ${unitLabel}`,
                fill: MUTED,
                font: '11px ui-monospace, monospace',
              },
            },
          ],
  }

  return (
    <Chart
      option={option}
      height={height}
      ariaLabel={`Lorenz curve of ${quantityLabel} by ${unitLabel}. Gini coefficient ${
        gini === null ? 'unavailable' : gini.toFixed(3)
      }.`}
    />
  )
}
