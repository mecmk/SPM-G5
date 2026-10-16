import { useState } from 'react'
import { ApiError, formatApiError } from '../api/client'
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
  const [isGone, setIsGone] = useState(false)

  // The clock as of when this row appeared decides which buttons it shows. The page keys this on
  // the closure's start and end, so a closure that changes gets a fresh one.
  const [shownAt] = useState(() => Date.now())
  const hasEnded = Date.parse(closure.endsAt) <= shownAt
  const hasStarted = Date.parse(closure.startsAt) < shownAt
  if (hasEnded) return null

  /** What a press does is decided by the clock at the press, not by when the row appeared: a
   *  closure that started since is ended, one still ahead is removed. The backend decides again. */
  function askToEndOrRemove() {
    setError(null)
    setPending(Date.parse(closure.startsAt) < Date.now() ? 'end' : 'remove')
  }

  function cancel() {
    setPending(null)
    if (isGone) onChanged()
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
      if (err instanceof ApiError && err.code === 'UNAVAILABILITY_NOT_FOUND') {
        // The closure is already gone: the day list is loaded again once the dialog, which keeps
        // the sentence, is closed.
        setIsGone(true)
      } else if (err instanceof ApiError && err.status === 409) {
        // The closure is no longer what the row showed (ended, or started): load it again.
        onChanged()
      }
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
        <button type="button" className="secondary button-sm" onClick={askToEndOrRemove}>
          End now
        </button>
      ) : (
        <button type="button" className="secondary button-sm" onClick={askToEndOrRemove}>
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
