/* The report, assembled. A left rail indexes the sections; the sections run
 * down the main column in the order a trader would read them — establish what
 * the book is, then where the flow goes, when it arrives, how it was priced,
 * how concentrated it is, what the detectors flagged, who is sharp, and finally
 * the data-quality ledger that qualifies all of it.
 *
 * The whole page reads from one artifact (payload.json) produced by the Python
 * pipeline. Nothing here computes a reported number; the footer carries the
 * dataset fingerprint and payload hash so any figure on the page can be tied
 * back to the exact pipeline run that produced it. */

import { VerifyProvider } from './components/verify'
import { CurrencyProvider } from './components/currency'
import { TooltipProvider } from './components/ui/tooltip'
import { Topbar } from './components/Topbar'
import { AlertStrip, AlertsPanel } from './components/Alerts'
import { Shell, type NavItem } from './components/Shell'
import { KeyFindings } from './sections/KeyFindings'
import { Overview } from './sections/Overview'
import { Flow } from './sections/Flow'
import { Timing } from './sections/Timing'
import { Prices } from './sections/Prices'
import { Concentration } from './sections/Concentration'
import { Anomalies } from './sections/Anomalies'
import { Sharp } from './sections/Sharp'
import { DataQuality } from './sections/DataQuality'
import {
  Lightbulb,
  BookOpen,
  Waypoints,
  Clock,
  TrendingUp,
  Layers,
  Radar,
  Crosshair,
  ClipboardCheck,
} from 'lucide-react'
import { payload } from './lib/payload'
import { dateTime } from './lib/format'

const NAV: NavItem[] = [
  { id: 'key_findings', label: 'Key findings', icon: Lightbulb },
  { id: 'overview', label: 'The book at a glance', icon: BookOpen },
  { id: 'flow', label: 'Flow by dimension', icon: Waypoints },
  { id: 'timing', label: 'Timing', icon: Clock },
  { id: 'prices', label: 'Price value & movement', icon: TrendingUp },
  { id: 'concentration', label: 'Concentration', icon: Layers },
  { id: 'anomalies', label: 'Anomaly detectors', icon: Radar },
  { id: 'sharp', label: 'Sharp behaviour', icon: Crosshair },
  { id: 'data_quality', label: 'Data quality', icon: ClipboardCheck },
]

export default function App() {
  return (
    <TooltipProvider>
      <CurrencyProvider>
        <VerifyProvider>
          <Topbar />
          <Shell nav={NAV}>
            <div className="space-y-3 pt-5">
              <AlertStrip />
              <AlertsPanel />
            </div>
            <KeyFindings />
            <Overview />
            <Flow />
            <Timing />
            <Prices />
            <Concentration />
            <Anomalies />
            <Sharp />
            <DataQuality />
            <Footer />
          </Shell>
        </VerifyProvider>
      </CurrencyProvider>
    </TooltipProvider>
  )
}

function Footer() {
  const m = payload.meta
  return (
    <footer className="py-12 text-[12px] leading-relaxed text-muted">
      <p className="max-w-[70ch]">
        Every figure on this page is read from a single artifact produced by the
        analysis pipeline — the dashboard performs no arithmetic of its own. The
        identifiers below tie this page to the exact run that generated it:
        re-running the pipeline on the same inputs reproduces the same hash.
      </p>
      <dl className="mt-4 grid max-w-md grid-cols-[auto_1fr] gap-x-6 gap-y-1">
        <dt>Generated</dt>
        <dd className="tnum text-ink2">{dateTime(m.generated_at)}</dd>
        <dt>Dataset fingerprint</dt>
        <dd className="tnum truncate text-ink2" title={m.dataset_fingerprint}>
          {m.dataset_fingerprint}
        </dd>
        <dt>Payload hash</dt>
        <dd className="tnum truncate text-ink2" title={m.payload_hash}>
          {m.payload_hash}
        </dd>
        <dt>Schema</dt>
        <dd className="tnum text-ink2">v{m.schema_version}</dd>
      </dl>
      <p className="mt-6 flex items-center gap-1.5 text-muted">
        <span className="font-display font-semibold text-ink2">
          Bet<span className="text-bronze">flow</span>
        </span>
        <span>— a Sporting Risk product · Task 1</span>
      </p>
    </footer>
  )
}
