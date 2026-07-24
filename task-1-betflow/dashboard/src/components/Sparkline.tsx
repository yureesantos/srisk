/* A tiny inline trend line for a KPI tile. Hand-built SVG — same approach as
 * the sharp scatter, no charting library for a 28px sparkline. It plots an
 * array the payload already ships (a daily series), optionally shading the
 * operating-period band so the June burst reads even at this size, and marks
 * the last point so the eye lands on "now".
 *
 * Presentation only: it plots values, it never computes them. The stroke is
 * always the primary series colour — no rainbow sparklines (colour encodes
 * category elsewhere, not here). */

interface SparklineProps {
  values: number[]
  /** [startIndex, endIndex] inclusive — shaded as the operating window. */
  band?: [number, number]
  height?: number
  /** Accessible summary; the SVG itself is aria-hidden. */
  ariaLabel?: string
}

export function Sparkline({ values, band, height = 30, ariaLabel }: SparklineProps) {
  const W = 100 // viewBox width; the SVG scales to its container
  const H = height
  const pad = 2

  if (values.length < 2) return <div style={{ height: H }} aria-hidden />

  const max = Math.max(...values)
  const min = Math.min(...values)
  const span = max - min || 1
  const stepX = (W - pad * 2) / (values.length - 1)

  const x = (i: number) => pad + i * stepX
  const y = (v: number) => pad + (1 - (v - min) / span) * (H - pad * 2)

  const points = values.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(' ')
  const last = values.length - 1

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height={H}
      preserveAspectRatio="none"
      role="img"
      aria-label={ariaLabel}
      className="block"
    >
      {band && (
        <rect
          x={x(band[0])}
          y={0}
          width={x(band[1]) - x(band[0])}
          height={H}
          fill="var(--color-s1)"
          fillOpacity={0.1}
        />
      )}
      <polyline
        points={points}
        fill="none"
        stroke="var(--color-s1)"
        strokeWidth={1.25}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle cx={x(last)} cy={y(values[last])} r={1.6} fill="var(--color-s1)" />
    </svg>
  )
}
