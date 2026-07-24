/* The sharp scatter — the report's signature chart, and the one place the
 * statistics are made visible rather than tabulated.
 *
 * Every point is a customer window (a Uid). x is how many priced selections we
 * could test it on — the weight of evidence; y is the share of those it beat
 * the reference price on — the beat rate. The horizontal rule is the population
 * baseline (~44%): where a window with no edge would sit. The chart's whole
 * argument is in the geometry: a high beat rate on the left (few units) is
 * noise and sits near the baseline's confidence spread; a high beat rate that
 * holds as you move right (many units) is the signal, and those are the windows
 * the significance test flags. Flagged windows are ringed; everything else is a
 * quiet dot. Hovering snaps to the nearest window and shows the counts behind
 * its position, so a reader can read a single dot back to its arithmetic.
 *
 * Hand-built in SVG on purpose. A stock scatter would draw the dots but not
 * this reading — the baseline, the flag ring, the nearest-point snap and the
 * verify halo are the parts that turn a cloud of points into an argument, and
 * they are easier to control as plain SVG than to coax out of a chart library.
 * x uses a log scale because units span 20–245 and the interesting structure is
 * in the low counts. */

import { useMemo, useRef, useState } from 'react'
import type { WindowRow } from '../lib/payload'
import { useVerify } from '../components/verify'
import { int, pct } from '../lib/format'

interface SharpScatterProps {
  /** Every scored, flag-eligible window. */
  windows: WindowRow[]
  /** Population beat rate — the "no edge" line. */
  baseline: number
  /** Section id these windows live under, for verify-target matching. */
  sectionId: string
  height?: number
}

const PAD = { top: 16, right: 18, bottom: 44, left: 48 }

export function SharpScatter({
  windows,
  baseline,
  sectionId,
  height = 380,
}: SharpScatterProps) {
  const ref = useRef<SVGSVGElement>(null)
  const [width, setWidth] = useState(760)
  const [hover, setHover] = useState<number | null>(null)
  const { isTarget } = useVerify()

  // Measure the container so the SVG is crisp at any width without a chart lib.
  const measure = (el: SVGSVGElement | null) => {
    if (el && el.clientWidth && el.clientWidth !== width) setWidth(el.clientWidth)
  }

  const plot = {
    x0: PAD.left,
    x1: width - PAD.right,
    y0: PAD.top,
    y1: height - PAD.bottom,
  }

  const geom = useMemo(() => {
    const unitVals = windows.map((w) => w.priced_units)
    const minU = Math.max(1, Math.min(...unitVals))
    const maxU = Math.max(...unitVals)
    const logMin = Math.log10(minU)
    const logMax = Math.log10(maxU)

    const sx = (u: number) =>
      plot.x0 +
      ((Math.log10(u) - logMin) / (logMax - logMin || 1)) * (plot.x1 - plot.x0)
    const sy = (rate: number) => plot.y1 - rate * (plot.y1 - plot.y0)

    const points = windows.map((w) => ({
      w,
      cx: sx(w.priced_units),
      cy: sy(w.beat_rate),
    }))

    // x ticks at powers/round units within the observed range.
    const ticks = [20, 30, 50, 100, 200].filter((t) => t >= minU && t <= maxU)
    return { sx, sy, points, ticks, minU, maxU }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windows, width, height])

  const nearest =
    hover === null
      ? null
      : geom.points.reduce((best, p, i) => {
          const d = (p.cx - hover) ** 2
          return d < best.d ? { i, d } : best
        }, { i: 0, d: Infinity }).i

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = ref.current?.getBoundingClientRect()
    if (!rect) return
    setHover(e.clientX - rect.left)
  }

  return (
    <div className="w-full">
      <svg
        ref={(el) => {
          ref.current = el
          measure(el)
        }}
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        role="img"
        aria-label={`Scatter of ${windows.length} customer windows by evidence weight and beat rate, with ${
          windows.filter((w) => w.flagged).length
        } flagged as statistically sharp.`}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        className="touch-none select-none"
      >
        {/* baseline: where a window with no edge sits */}
        <line
          x1={plot.x0}
          x2={plot.x1}
          y1={geom.sy(baseline)}
          y2={geom.sy(baseline)}
          stroke="#6b6963"
          strokeWidth={1}
          strokeDasharray="4 4"
        />
        <text
          x={plot.x1}
          y={geom.sy(baseline) - 6}
          textAnchor="end"
          className="fill-muted"
          style={{ font: '11px "JetBrains Mono Variable", ui-monospace, monospace' }}
        >
          baseline {pct(baseline, 0)}
        </text>

        {/* y grid + labels at 0/25/50/75/100% */}
        {[0, 0.25, 0.5, 0.75, 1].map((r) => (
          <g key={r}>
            <line
              x1={plot.x0}
              x2={plot.x1}
              y1={geom.sy(r)}
              y2={geom.sy(r)}
              stroke="#e3e0d7"
              strokeWidth={1}
            />
            <text
              x={plot.x0 - 8}
              y={geom.sy(r) + 3}
              textAnchor="end"
              className="fill-muted"
              style={{ font: '10px "JetBrains Mono Variable", ui-monospace, monospace' }}
            >
              {Math.round(r * 100)}
            </text>
          </g>
        ))}

        {/* x ticks (log) */}
        {geom.ticks.map((t) => (
          <text
            key={t}
            x={geom.sx(t)}
            y={plot.y1 + 16}
            textAnchor="middle"
            className="fill-muted"
            style={{ font: '10px "JetBrains Mono Variable", ui-monospace, monospace' }}
          >
            {t}
          </text>
        ))}

        {/* axis titles */}
        <text
          x={(plot.x0 + plot.x1) / 2}
          y={height - 6}
          textAnchor="middle"
          className="fill-ink2"
          style={{ font: '11px "Albert Sans", sans-serif' }}
        >
          Priced selections in window (log)
        </text>
        <text
          transform={`translate(12 ${(plot.y0 + plot.y1) / 2}) rotate(-90)`}
          textAnchor="middle"
          className="fill-ink2"
          style={{ font: '11px "Albert Sans", sans-serif' }}
        >
          Beat rate (%)
        </text>

        {/* points: quiet dots, ringed flags, verify halo on the active target */}
        {geom.points.map(({ w, cx, cy }, i) => {
          const flagged = w.flagged
          const target = isTarget(sectionId, w as unknown as Record<string, unknown>)
          const active = i === nearest
          return (
            <g key={w.Uid}>
              {target && (
                <circle cx={cx} cy={cy} r={11} fill="none" stroke="#8a6845" strokeWidth={2} />
              )}
              <circle
                cx={cx}
                cy={cy}
                r={flagged ? 5 : 3.2}
                fill={flagged ? '#c24a1a' : '#2f74cc'}
                fillOpacity={flagged ? 0.95 : 0.55}
                stroke={active ? '#1a2129' : 'none'}
                strokeWidth={active ? 1.5 : 0}
              />
              {flagged && (
                <circle cx={cx} cy={cy} r={8} fill="none" stroke="#c24a1a" strokeWidth={1} strokeOpacity={0.5} />
              )}
            </g>
          )
        })}

        {/* hover guide */}
        {nearest !== null && (
          <line
            x1={geom.points[nearest].cx}
            x2={geom.points[nearest].cx}
            y1={plot.y0}
            y2={plot.y1}
            stroke="#bdb9ad"
            strokeWidth={1}
          />
        )}
      </svg>

      {nearest !== null && <HoverCard w={geom.points[nearest].w} />}
      <Legend flaggedCount={windows.filter((w) => w.flagged).length} />
    </div>
  )
}

function HoverCard({ w }: { w: WindowRow }) {
  return (
    <div className="mt-3 flex flex-wrap items-baseline gap-x-5 gap-y-1 rounded-lg border border-grid bg-raised px-4 py-2.5 text-[13px]">
      <span className="font-medium text-ink">Uid {w.Uid}</span>
      <Field label="beat" value={`${w.beats}/${w.priced_units}`} />
      <Field label="rate" value={pct(w.beat_rate, 1)} />
      <Field label="Wilson LB" value={pct(w.wilson_lb, 1)} />
      <Field
        label="p"
        value={w.p_value === null ? 'n/a' : w.p_value < 0.001 ? w.p_value.toExponential(1) : w.p_value.toFixed(4)}
      />
      <span
        className={`ml-auto rounded px-2 py-0.5 text-[11px] font-medium ${
          w.flagged ? 'bg-s2/20 text-s2' : 'bg-raised text-muted'
        }`}
      >
        {w.flagged ? 'flagged (FDR-controlled)' : 'not flagged'}
      </span>
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <span className="text-ink2">
      <span className="text-muted">{label} </span>
      <span className="tnum text-ink">{value}</span>
    </span>
  )
}

function Legend({ flaggedCount }: { flaggedCount: number }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] text-muted">
      <span className="flex items-center gap-1.5">
        <span className="size-2 rounded-full bg-s1/60" /> tested window
      </span>
      <span className="flex items-center gap-1.5">
        <span className="size-2.5 rounded-full bg-s2 ring-1 ring-s2/50" /> flagged sharp
        ({int(flaggedCount)})
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-0 w-4 border-t border-dashed border-muted" />{' '}
        no-edge baseline
      </span>
    </div>
  )
}
