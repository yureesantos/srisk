/* When the flow arrives. Two views of the same clock: the phase split relative
 * to kick-off (how much money comes in a week out vs the last five minutes vs
 * in-play), and the day-level series already shown in the overview is not
 * repeated here — timing here is about position within a match, not the
 * calendar. The in-play phases are a timing-based upper bound, not a live flag,
 * and are labelled as such so they aren't over-read. */

import { payload } from '../lib/payload'
import { Section, GrainBadge } from '../components/Section'
import { TimingPhases } from '../charts/TimingPhases'
import { Clock } from 'lucide-react'

export function Timing() {
  const phases = payload.timing.phases

  return (
    <Section
      id="timing"
      title="Timing relative to kick-off"
      icon={Clock}
      info={phases.notes}
      aside={<GrainBadge grain={phases.grain} />}
    >
      <TimingPhases rows={phases.rows} />
    </Section>
  )
}
