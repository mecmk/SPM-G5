import { useState } from 'react'
import { formatApiError } from '../api/client'
import { endUnavailabilityNow, removeUnavailability } from '../api/venues'
import { ConfirmDialog } from '../components/ConfirmDialog'
import type { DayClosure } from '../components/venueCalendarDays'

export interface ClosureActionsProps {
  venueId: string
  closure: DayClosure
  /** Edit was pressed: the page opens its form on this closure. */
  onEdit: (closure: DayClosure) => void
  /** The closure was ended or removed, so the page loads its calendar again. */
  onChanged: () => void
}

type PendingAction = 'end' | 'remove'

/**
 * Story 9.4 AC6: what Venue Staff can do to a closure from its row in the day list. One not yet
 * started can be edited or removed; one in force can be edited or ended now, and the calendar
 * keeps it as history; one that has ended has nothing - Venue Staff add a new closure instead.
 * Each of ending and removing asks first. The page decides from its own clock, and the backend
 * decides again, so a press that races the boundary shows the backend's sentence in the dialog.
 */
export function ClosureActions({ venueId, closure, onEdit, onChanged }: ClosureActionsProps) {
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [isBusy, setIsBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // The clock as of when this row appeared: the calendar loads its rows again after every change,
  // and the backend decides again on the press, so a row open for hours is still safe.
  const [now] = useState(() => Date.now())
  const hasEnded = Date.parse(closure.endsAt) <= now
  const hasStarted = Date.parse(closure.startsAt) < now
  if (hasEnded) return null

  function askToEnd() {
    setError(null)
    setPending('end')
  }

  function askToRemove() {
    setError(null)
    setPending('remove')
  }

  function cancel() {
    setPending(null)
  }

  function handleEdit() {
    onEdit(closure)
  }

  async function confirm() {
    setIsBusy(true)
    setError(null)
    try {
      if (pending === 'end') await endUnavailabilityNow(venueId, closure.id)
      else await removeUnavailability(venueId, closure.id)
      setPending(null)
      onChanged()
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <>
      <button type="button" className="secondary button-sm" onClick={handleEdit}>
        Edit
      </button>
      {hasStarted ? (
        <button type="button" className="secondary button-sm" onClick={askToEnd}>
          End now
        </button>
      ) : (
        <button type="button" className="secondary button-sm" onClick={askToRemove}>
          Remove
        </button>
      )}
      {pending === 'end' && (
        <ConfirmDialog
          title="End this closure now?"
          confirmLabel="End now"
          tone="primary"
          isBusy={isBusy}
          error={error}
          onConfirm={confirm}
          onCancel={cancel}
        >
          <p>
            The venue is available again from now. The closure stays on the calendar up to this
            moment, and bookings it no longer overlaps stop being flagged.
          </p>
        </ConfirmDialog>
      )}
      {pending === 'remove' && (
        <ConfirmDialog
          title="Remove this closure?"
          confirmLabel="Remove"
          isBusy={isBusy}
          error={error}
          onConfirm={confirm}
          onCancel={cancel}
        >
          <p>
            This closure has not started, so it is removed from the calendar, and bookings it no
            longer overlaps stop being flagged.
          </p>
        </ConfirmDialog>
      )}
    </>
  )
}
