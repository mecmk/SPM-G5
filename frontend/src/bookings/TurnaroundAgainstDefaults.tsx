import { formatMinutesDuration } from '../shared/bookingStatus'
import { venueDefaultNote } from './turnaround'

interface TurnaroundAgainstDefaultsProps {
  setupMinutes: number
  teardownMinutes: number
  setupDefault: number
  teardownDefault: number
  /** The class of each fact's box: `subtle-block` on the queue card, none on the request page. */
  blockClassName?: string
}

/**
 * f12.1.3 (story 12.1 AC19): a request's setup and teardown, each with how it stands against the
 * venue's default, on Venue Staff's queue card and the request's page, so they take a changed
 * figure into account when approving (13.2).
 */
export function TurnaroundAgainstDefaults({
  setupMinutes,
  teardownMinutes,
  setupDefault,
  teardownDefault,
  blockClassName,
}: TurnaroundAgainstDefaultsProps) {
  const facts = [
    { label: 'Setup', minutes: setupMinutes, defaultMinutes: setupDefault },
    { label: 'Teardown', minutes: teardownMinutes, defaultMinutes: teardownDefault },
  ]
  return facts.map(({ label, minutes, defaultMinutes }) => (
    <div key={label} className={blockClassName}>
      <p className="fact-label">{label}</p>
      <p className="fact-value">{formatMinutesDuration(minutes)}</p>
      <p className={minutes === defaultMinutes ? 'small muted' : 'small'}>
        {venueDefaultNote(minutes, defaultMinutes)}
      </p>
    </div>
  ))
}
