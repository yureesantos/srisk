/* Betflow's own identity, endorsed by Sporting Risk.
 *
 * Betflow is the product; Sporting Risk is the house. The wordmark is built, not
 * imported — a monospace-rooted glyph mark (a flow of stacked bars reading left
 * to right, the shape of the very analysis this tool presents) plus the name set
 * in the display face, with "flow" carried in the Sporting Risk bronze so the
 * two brands are tied by a single colour rather than by borrowing a logo.
 *
 * The bronze is the one identity accent in the whole product (DESIGN.md): it
 * lives here, on focus rings, on verify highlights, and nowhere on the data. */

/** The glyph: four bars of rising height — a betting-flow sparkline abstracted
 *  into a mark. Bronze on the tallest bar ties it to the wordmark. */
export function BetflowMark({
  size = 28,
  className,
}: {
  size?: number
  className?: string
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      role="img"
      aria-label="Betflow"
    >
      <rect x="2" y="2" width="28" height="28" rx="7" fill="#1a2129" />
      <rect x="2.5" y="2.5" width="27" height="27" rx="6.5" stroke="#ffffff" strokeOpacity="0.10" />
      {/* rising flow bars */}
      <rect x="7" y="19" width="3.4" height="6" rx="1" fill="#3987e5" />
      <rect x="12.3" y="15" width="3.4" height="10" rx="1" fill="#3987e5" fillOpacity="0.8" />
      <rect x="17.6" y="11" width="3.4" height="14" rx="1" fill="#199e70" fillOpacity="0.85" />
      <rect x="22.9" y="7" width="3.4" height="18" rx="1" fill="#9b7755" />
    </svg>
  )
}

/** The full lockup: mark + "Betflow" wordmark, "flow" in bronze. `subtitle`
 *  renders the product descriptor line beneath. */
export function BetflowWordmark({
  size = 'md',
  subtitle,
}: {
  size?: 'sm' | 'md'
  subtitle?: string
}) {
  const markSize = size === 'sm' ? 24 : 30
  const nameClass =
    size === 'sm' ? 'text-[15px]' : 'text-[18px]'

  return (
    <div className="flex items-center gap-2.5">
      <BetflowMark size={markSize} className="shrink-0" />
      <div className="min-w-0 leading-none">
        <div
          className={`font-display font-semibold tracking-tight text-ink ${nameClass}`}
        >
          Bet<span className="text-bronze">flow</span>
        </div>
        {subtitle && (
          <div className="mt-1 text-[11px] font-medium leading-none text-muted">
            {subtitle}
          </div>
        )}
      </div>
    </div>
  )
}
