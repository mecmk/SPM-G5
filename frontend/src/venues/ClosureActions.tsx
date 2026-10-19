import { useEffect, useState } from 'react'
import { ApiError, formatApiError } from '../api/client'
import { endUnavailabilityNow, removeUnavailability } from '../api/venues'
import { ConfirmDialog } from '../components/ConfirmDialog'
import type { DayClosure } from '../components/venueCalendarDays'
import { END_CLOSURE_HINT, REMOVE_CLOSURE_HINT } from './blockOffLabels'

export interface ClosureActionsProps {
  venueId: string
  closure: DayClosure
  /** Edit was pressed: the page opens its form on this closure. */
  onEdit: (closure: DayClosure) => void
  /** The closure was ended or removed, so the page loads its calendar again. */
  onChanged: () => void
}

type PendingAction = 'end' | 'remove'

/** How often a row looks at the clock again. */
const CLOCK_TICK_MS = 60_000

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

  // The row's own clock, moved on every minute, so a row left open across a closure's start
  // switches from Remove to End now, and one left open across its end loses its buttons, without
  // a reload. The backend decides again on the press.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_TICK_MS)
    return () => clearInterval(timer)
  }, [])
  const hasEnded = Date.parse(closure.endsAt) <= now
  const hasStarted = Date.parse(closure.startsAt) < now
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
      // The closure is gone (404) or no longer what the row showed (409): the day list is out of
      // date, and is loaded again once the dialog, which keeps the backend's sentence, is closed.
      if (
        err instanceof ApiError &&
        (err.code === 'UNAVAILABILITY_NOT_FOUND' || err.status === 409)
      ) {
        setIsGone(true)
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
      <span className="closure-action">
        <button type="button" className="secondary button-sm" onClick={askToEndOrRemove}>
          {hasStarted ? 'End now' : 'Remove'}
        </button>
        <span className="small muted">{hasStarted ? END_CLOSURE_HINT : REMOVE_CLOSURE_HINT}</span>
      </span>
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
