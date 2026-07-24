/* One ECharts theme, registered once, shared by every chart.
 *
 * The point of this file is that no chart component sets a colour, a font, a
 * grid line or an axis style of its own. They describe data; this describes how
 * the product looks. That separation is also why the charts don't read as a
 * stock ECharts dashboard — the defaults ECharts ships (its blue-purple ramp,
 * its boxed tooltips, its heavy axis lines) are all replaced here in one place.
 *
 * Values are the DESIGN.md tokens, hard-coded rather than read from CSS custom
 * properties: ECharts renders to <canvas>, which cannot resolve `var(--…)`, so
 * a canvas theme has to carry literal hex. The single source of truth stays
 * DESIGN.md; this file and index.css are two renderings of it, kept in step by
 * the comments that name each token. */

import * as echarts from 'echarts/core'
import { BarChart, LineChart, ScatterChart, CustomChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  MarkLineComponent,
  MarkAreaComponent,
  DatasetComponent,
  GraphicComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  LineChart,
  ScatterChart,
  CustomChart,
  GridComponent,
  TooltipComponent,
  MarkLineComponent,
  MarkAreaComponent,
  DatasetComponent,
  GraphicComponent,
  CanvasRenderer,
])

// DESIGN.md palette (light theme). Literal hex, kept in lock-step with the
// index.css tokens because the canvas can't read CSS custom properties. The
// series are the light-ground values (stepped darker from the dark theme so
// they clear contrast on a light surface).
const SURFACE = '#f9f8f4'
const INK = '#1a2129'
const INK2 = '#47505b'
const MUTED = '#6b6963'
const GRID = '#e3e0d7'
const AXIS = '#bdb9ad'

const SERIES = ['#2f74cc', '#c24a1a', '#178a62', '#a06e00']

// The same three type roles as the DOM (DESIGN.md), as literal strings because
// the canvas cannot resolve CSS custom properties. Kept in step with index.css.
const SANS =
  '"Albert Sans", ui-sans-serif, -apple-system, "Segoe UI", sans-serif'
const MONO =
  '"JetBrains Mono Variable", ui-monospace, "SF Mono", Menlo, monospace'
const DISPLAY = '"Space Grotesk Variable", "Albert Sans", sans-serif'

export const THEME = 'srisk'

/* An axis with a hairline base, no tick marks, muted mono labels. ECharts draws
 * a solid dark axis line and serifed default ticks out of the box; both read as
 * chart-junk against a dark surface, so both are turned off here. */
const axisCommon = {
  axisLine: { show: true, lineStyle: { color: AXIS, width: 1 } },
  axisTick: { show: false },
  axisLabel: { color: MUTED, fontFamily: MONO, fontSize: 11 },
  splitLine: { show: false },
  nameTextStyle: { color: INK2, fontFamily: SANS, fontSize: 11, fontWeight: 500 },
}

echarts.registerTheme(THEME, {
  color: SERIES,
  backgroundColor: 'transparent',
  textStyle: { fontFamily: SANS, color: INK2 },

  // State-conveying, not decorative: a short cubic-out settle, no load
  // choreography (product register). Charts that must not animate at all pass
  // `animation: false` per-instance (reduced-motion, handled in Chart.tsx).
  animationDuration: 300,
  animationEasing: 'cubicOut',

  title: {
    textStyle: { color: INK, fontFamily: DISPLAY, fontWeight: 600, fontSize: 14 },
    subtextStyle: { color: MUTED, fontFamily: SANS, fontSize: 12 },
  },

  // Value axes get a single hairline split; category axes get none. Assigned
  // per-chart via `xAxis`/`yAxis` type, but the shared defaults live here.
  categoryAxis: axisCommon,
  valueAxis: {
    ...axisCommon,
    axisLine: { show: false },
    splitLine: { show: true, lineStyle: { color: GRID, width: 1, type: 'solid' } },
  },
  logAxis: axisCommon,
  timeAxis: axisCommon,

  bar: {
    itemStyle: { borderRadius: [2, 2, 0, 0] },
    barMaxWidth: 44,
  },
  line: {
    symbol: 'none',
    lineStyle: { width: 2 },
    emphasis: { lineStyle: { width: 2 } },
  },
  scatter: {
    symbolSize: 7,
    itemStyle: { opacity: 0.85 },
  },

  // The tooltip is the one place ECharts' default styling most gives itself
  // away (white box, drop shadow, arrow). Replaced with a raised-surface card
  // that matches the rest of the UI.
  tooltip: {
    backgroundColor: '#ffffff',
    borderColor: GRID,
    borderWidth: 1,
    padding: [8, 10],
    textStyle: { color: INK, fontFamily: SANS, fontSize: 12 },
    extraCssText:
      'border-radius:6px;box-shadow:0 6px 22px rgba(26,33,41,0.16);backdrop-filter:none;',
    axisPointer: {
      type: 'line',
      lineStyle: { color: AXIS, width: 1, type: 'dashed' },
      crossStyle: { color: AXIS, width: 1 },
      label: { backgroundColor: SURFACE, color: INK2, fontFamily: MONO },
    },
  },
})

export { echarts, SERIES, INK, INK2, MUTED, GRID, AXIS, SANS, MONO, DISPLAY }
