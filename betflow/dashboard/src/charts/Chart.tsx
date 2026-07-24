/* The single seam between ECharts and the rest of the app.
 *
 * Every ECharts-backed chart renders through this wrapper, which does three
 * things and nothing else: bind the registered `srisk` theme, keep the canvas
 * sized to its container, and hold a stable height so the page doesn't reflow
 * while the ~380 KB payload hydrates. Chart components pass an `option`; they
 * never touch the ECharts instance, the renderer, or the theme name. */

import {
  useCallback,
  useMemo,
  type ComponentType,
  type CSSProperties,
} from 'react'
import * as ReactEChartsCoreModule from 'echarts-for-react/lib/core'
import type { EChartsOption } from 'echarts'
import { echarts, THEME } from '../theme/echarts'

/* echarts-for-react ships CommonJS. Vite 8 / Rolldown's interop can nest the
 * default one level deep (`{ default: { default: Component } }`), so unwrap
 * defensively rather than trusting a single `default`. */
interface EChartsInstance {
  resize: () => void
}
interface CoreProps {
  echarts: unknown
  option: EChartsOption
  theme?: string
  opts?: Record<string, unknown>
  notMerge?: boolean
  lazyUpdate?: boolean
  style?: CSSProperties
  onChartReady?: (instance: EChartsInstance) => void
}
const mod = ReactEChartsCoreModule as unknown as {
  default?: ComponentType<CoreProps> & { default?: ComponentType<CoreProps> }
}
const ReactEChartsCore: ComponentType<CoreProps> =
  (mod.default?.default ?? mod.default) as ComponentType<CoreProps>

const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

interface ChartProps {
  option: EChartsOption
  /** Fixed CSS height. Charts declare their own aspect; the grid never guesses. */
  height: number
  /** Screen-reader label — the chart canvas is otherwise opaque to assistive tech. */
  ariaLabel: string
  className?: string
}

export function Chart({ option, height, ariaLabel, className }: ChartProps) {
  // ECharts mutates the option object it is handed; memoising by identity keeps
  // React from re-initialising the chart on every parent render.
  const opts = useMemo(() => ({ renderer: 'canvas' as const }), [])

  // Reduced-motion is honoured explicitly: the canvas ignores the CSS motion
  // kill-switch, so animation is disabled at the option level instead.
  const themed = useMemo<EChartsOption>(
    () => (prefersReducedMotion() ? { ...option, animation: false } : option),
    [option],
  )

  // ECharts rasterises text when it paints; if a chart draws before the woff2
  // arrives, its axis labels freeze in the fallback font. Resize once fonts are
  // ready so the real JetBrains Mono / Albert Sans get laid down.
  const onReady = useCallback((instance: EChartsInstance) => {
    if (typeof document !== 'undefined' && 'fonts' in document) {
      document.fonts.ready.then(() => instance.resize()).catch(() => {})
    }
  }, [])

  return (
    <div role="img" aria-label={ariaLabel} className={className} style={{ height }}>
      <ReactEChartsCore
        echarts={echarts}
        option={themed}
        theme={THEME}
        opts={opts}
        notMerge
        lazyUpdate
        onChartReady={onReady}
        style={{ height: '100%', width: '100%' }}
      />
    </div>
  )
}
