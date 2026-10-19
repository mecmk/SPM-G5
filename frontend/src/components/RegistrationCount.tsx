import { Chip } from './Chip'

/** Stories 18.1 AC3 and 18.3 AC3: what an event that has reached its capacity is called. */
export const FULL_LABEL = 'Full'

export interface RegistrationCountProps {
  activeCount: number
  capacity: number
  isFull: boolean
}

/** Story 18.3 AC1/AC3: an event's active registrations against its capacity, and Full once they
 *  reach it - on the event page's Registration card and on the registrations report. */
export function RegistrationCount({ activeCount, capacity, isFull }: RegistrationCountProps) {
  return (
    <div>
      <p className="eyebrow">Registered</p>
      <p className="cluster">
        {activeCount} / {capacity}
        {isFull && <Chip label={FULL_LABEL} tone="warning" />}
      </p>
    </div>
  )
}
