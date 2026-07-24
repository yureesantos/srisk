/* The product header. A dashboard is an instrument, and an instrument names
 * itself and states its calibration up front: on the left, the Betflow brand;
 * on the right, the live provenance — which dataset this is, its window, and
 * the hash that pins every figure below to one pipeline run. The Sporting Risk
 * endorsement sits here too, small, because Betflow is the product and Sporting
 * Risk is the house behind it.
 *
 * It reads only from `payload.meta` and `payload.overview` — display, no math. */

import { ShieldCheck } from 'lucide-react'
import { payload } from '../lib/payload'
import { severityCounts } from '../lib/alerts'
import { BetflowWordmark } from './brand'
import { CurrencySelect } from './CurrencySelect'
import { Separator } from './ui/separator'
import { Tooltip, TooltipTrigger, TooltipContent } from './ui/tooltip'
import mark from '../assets/LOGO-Sport.svg'
import { date } from '../lib/format'

export function Topbar() {
  const u = payload.overview.universe
  const m = payload.meta
  const shortHash = m.payload_hash.replace(/^sha256:/, '').slice(0, 10)

  return (
    <header
      className="
        sticky top-0 z-sticky flex items-center justify-between gap-4
        border-b border-border bg-page/85 px-5 py-3 backdrop-blur
        sm:px-8
      "
    >
      <div className="flex items-center gap-4">
        <BetflowWordmark subtitle="Betting flow analytics" />
        <a
          href="#section-overview"
          className="hidden items-center gap-1.5 rounded-full border border-critical/40 bg-critical/10 px-2.5 py-1 text-[11px] font-medium text-critical transition-colors hover:bg-critical/20 sm:flex"
        >
          <span className="size-1.5 rounded-full bg-critical" aria-hidden />
          {severityCounts().critical} sharp
        </a>
      </div>

      <div className="flex items-center gap-4">
        {/* Dataset provenance — the instrument's calibration plate. */}
        <div className="hidden items-center gap-4 text-right md:flex">
          <Field label="Window">
            {date(u.date_min)} → {date(u.date_max)}
          </Field>
          <Separator orientation="vertical" className="h-8" />
          <Field label="Betslips">{u.betslips.toLocaleString('en-GB')}</Field>
          <Separator orientation="vertical" className="h-8" />
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="text-right focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm"
              >
                <Field label="Build">
                  <span className="text-bronze">{shortHash}</span>
                </Field>
              </button>
            </TooltipTrigger>
            <TooltipContent>
              <div className="space-y-1">
                <div className="tnum">{m.payload_hash}</div>
                <div className="text-muted">
                  Dataset {m.dataset_fingerprint}
                </div>
              </div>
            </TooltipContent>
          </Tooltip>
        </div>

        {/* The one currency control — every money figure follows it. */}
        <CurrencySelect />

        {/* Sporting Risk endorsement — the house behind the product. */}
        <Tooltip>
          <TooltipTrigger asChild>
            <a
              href="https://sportingrisk.com/"
              target="_blank"
              rel="noreferrer noopener"
              className="
                flex items-center gap-2 rounded-full border border-border
                bg-raised py-1 pl-1 pr-3 transition-colors hover:border-bronze/50
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring
              "
            >
              {/* The badge is a light disc with a dark S + bronze R, designed
                  for Sporting Risk's own dark site. On the light topbar it sits
                  in a small dark chip so its disc reads — the parent brand's
                  dark ground preserved, matching the Betflow mark's chip. */}
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-ink">
                <img src={mark} alt="" width={18} height={20} />
              </span>
              <span className="hidden text-[11px] font-medium text-ink2 sm:inline">
                Sporting&nbsp;Risk
              </span>
            </a>
          </TooltipTrigger>
          <TooltipContent>
            <span className="inline-flex items-center gap-1.5">
              <ShieldCheck className="size-3 text-bronze" />A Sporting Risk product ·
              sportingrisk.com
            </span>
          </TooltipContent>
        </Tooltip>
      </div>
    </header>
  )
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="leading-tight">
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted">
        {label}
      </div>
      <div className="tnum text-[13px] text-ink">{children}</div>
    </div>
  )
}
