import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { ApiError, formatApiError } from '../api/client'
import {
  addUnavailability,
  editUnavailability,
  fetchAffectedBookings,
  UNAVAILABILITY_REASON_NAMES,
  type AffectedBooking,
  type UnavailabilityInput,
  type UnavailabilityReason,
} from '../api/venues'
import { Chip } from '../components/Chip'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { StatusBadge } from '../components/StatusBadge'
import type { DayClosure } from '../components/venueCalendarDays'
import { ERROR_REGISTRY } from '../errors/registry'
import { bookingRequestPath } from '../routes'
import { formatDateTime, instantToInput, inputToInstant } from '../shared/format'

export interface VenueUnavailabilitySectionProps {
  venueId: string
  venueName: string
  /** Called once a closure is saved, so the page loads its calendar again. */
  onSaved: () => void
  /** The closure being edited, with the form open on it; null to add one. The page keys this
   *  section on the closure, so the form starts from it. */
  editing?: DayClosure | null
  /** Called when an edit is saved or abandoned, so the page stops editing. */
  onEditFinished?: () => void
}

/** The fields of `input` that differ from the closure being edited. */
function changedFields(
  closure: DayClosure,
  input: UnavailabilityInput,
): Partial<UnavailabilityInput> {
  const changes: Partial<UnavailabilityInput> = {}
  if (Date.parse(input.starts_at) !== Date.parse(closure.startsAt)) {
    changes.starts_at = input.starts_at
  }
  if (Date.parse(input.ends_at) !== Date.parse(closure.endsAt)) changes.ends_at = input.ends_at
  if (input.reason !== closure.reason) changes.reason = input.reason
  if (input.description !== (closure.description ?? null)) changes.description = input.description
  return changes
}

const REASON_CODES = Object.keys(UNAVAILABILITY_REASON_NAMES) as UnavailabilityReason[]
const DEFAULT_REASON: UnavailabilityReason = 'MAINTENANCE'

/** What the preview last answered, for the period it was asked about. */
interface PreviewResult {
  key: string
  bookings: AffectedBooking[] | null
  error: string | null
}

/**
 * Story 9.4 AC1/AC2/AC5/AC9: Venue Staff block off time at the venue from its page. The form takes a
 * start, an end, a reason and a description, which every reason needs. An end that is not after
 * the start is refused in the form, beside the fields, before anything is sent. Once both ends
 * make a period, the pending and approved bookings it would affect - setup and teardown included -
 * are listed before Save; saving is allowed with some, after one confirmation that names them. A
 * refusal from the server, such as a missing description, shows the backend's own sentence and
 * nothing is saved. The page only shows this to a role holding the manage permission; the backend
 * refuses everyone else.
 *
 * Story 9.4 AC6: the same form edits a closure - its start, end, reason and description - opened
 * from the closure's row. The bookings its new period would affect are listed the same way, those
 * already flagged marked as such, and only bookings it would newly flag ask for a confirmation.
 */
export function VenueUnavailabilitySection({
  venueId,
  venueName,
  onSaved,
  editing = null,
  onEditFinished,
}: VenueUnavailabilitySectionProps) {
  const [isOpen, setIsOpen] = useState(editing !== null)
  const [starts, setStarts] = useState(editing === null ? '' : instantToInput(editing.startsAt))
  const [ends, setEnds] = useState(editing === null ? '' : instantToInput(editing.endsAt))
  const [reason, setReason] = useState<UnavailabilityReason>(
    editing === null ? DEFAULT_REASON : (editing.reason as UnavailabilityReason),
  )
  const [description, setDescription] = useState(editing?.description ?? '')
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [isConfirming, setIsConfirming] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const formRef = useRef<HTMLFormElement>(null)

  // An edit opens from a closure's row in the calendar above, so bring the form into view.
  useEffect(() => {
    if (editing !== null) formRef.current?.scrollIntoView({ block: 'nearest' })
  }, [editing])

  /** The period the form describes, once both ends are given and the end is after the start. */
  const period = useMemo(() => {
    if (starts === '' || ends === '') return null
    const startsAt = inputToInstant(starts)
    const endsAt = inputToInstant(ends)
    return Date.parse(endsAt) > Date.parse(startsAt) ? { startsAt, endsAt } : null
  }, [starts, ends])
  const previewKey = period === null ? null : `${period.startsAt}|${period.endsAt}`

  useEffect(() => {
    if (period === null || previewKey === null) return
    let cancelled = false
    fetchAffectedBookings(venueId, period.startsAt, period.endsAt)
      .then((bookings) => {
        if (!cancelled) setPreview({ key: previewKey, bookings, error: null })
      })
      .catch((err) => {
        if (!cancelled) setPreview({ key: previewKey, bookings: null, error: formatApiError(err) })
      })
    return () => {
      cancelled = true
    }
  }, [venueId, period, previewKey])

  const isPreviewCurrent = preview !== null && preview.key === previewKey
  const affected = isPreviewCurrent ? (preview.bookings ?? []) : []
  const newlyAffected = affected.filter((booking) => !booking.already_marked)
  /** Story 9.4 AC2: the form saves only once the list for these very dates has answered. */
  const canSave = period !== null && isPreviewCurrent && preview.error === null
  /** Story 9.4 AC5: both ends given and the end not after the start. */
  const isEndBeforeStart =
    starts !== '' &&
    ends !== '' &&
    Date.parse(inputToInstant(ends)) <= Date.parse(inputToInstant(starts))

  function resetForm() {
    setStarts('')
    setEnds('')
    setReason(DEFAULT_REASON)
    setDescription('')
    setPreview(null)
    setIsConfirming(false)
    setSaveError(null)
  }

  function open() {
    resetForm()
    setIsOpen(true)
  }

  function close() {
    resetForm()
    setIsOpen(false)
    if (editing !== null) onEditFinished?.()
  }

  async function save() {
    if (period === null) return
    setIsSaving(true)
    setSaveError(null)
    try {
      const input = {
        starts_at: period.startsAt,
        ends_at: period.endsAt,
        reason,
        description: description.trim() === '' ? null : description.trim(),
      }
      if (editing === null) {
        await addUnavailability(venueId, venueName, input)
      } else {
        // Only what changed is sent, so an edit never overwrites a field someone else changed.
        const changes = changedFields(editing, input)
        if (Object.keys(changes).length > 0) {
          await editUnavailability(venueId, editing.id, changes)
        }
      }
      close()
      onSaved()
    } catch (err) {
      setSaveError(formatApiError(err))
      setIsConfirming(false)
      // The closure is gone - removed or ended elsewhere - so the page's calendar is out of date.
      if (err instanceof ApiError && err.code === 'UNAVAILABILITY_NOT_FOUND') onSaved()
    } finally {
      setIsSaving(false)
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSave) return
    if (newlyAffected.length > 0) {
      setSaveError(null)
      setIsConfirming(true)
      return
    }
    void save()
  }

  function cancelConfirm() {
    setIsConfirming(false)
  }

  if (!isOpen) {
    return (
      <div className="cluster">
        <button type="button" className="secondary button-sm" onClick={open}>
          Block off time
        </button>
      </div>
    )
  }

  return (
    <>
      <form
        ref={formRef}
        className="stack"
        onSubmit={handleSubmit}
        noValidate
        aria-label={editing === null ? `Block off time at ${venueName}` : 'Edit blocked-off time'}
      >
        <div className="form-grid form-grid-2">
          <label>
            Starts
            <input
              type="datetime-local"
              value={starts}
              onChange={(event) => setStarts(event.target.value)}
              disabled={isSaving}
            />
          </label>
          <label>
            Ends
            <input
              type="datetime-local"
              value={ends}
              onChange={(event) => setEnds(event.target.value)}
              disabled={isSaving}
            />
          </label>
        </div>
        {isEndBeforeStart && (
          <p role="alert" className="error">
            {ERROR_REGISTRY.UNAVAILABILITY_END_BEFORE_START.message}
          </p>
        )}
        <div className="form-grid">
          <label>
            Reason
            <select
              value={reason}
              onChange={(event) => setReason(event.target.value as UnavailabilityReason)}
              disabled={isSaving}
            >
              {REASON_CODES.map((code) => (
                <option key={code} value={code}>
                  {UNAVAILABILITY_REASON_NAMES[code]}
                </option>
              ))}
            </select>
          </label>
          <label className="span-2">
            Description{' '}
            <span className="req" aria-hidden="true">
              *
            </span>
            <textarea
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              disabled={isSaving}
            />
          </label>
        </div>

        {period !== null && (
          <section className="stack" aria-labelledby="affected-bookings-heading">
            <h3 id="affected-bookings-heading" className="eyebrow">
              Affected bookings
            </h3>
            {!isPreviewCurrent && <p className="muted">Checking the venue&apos;s bookings…</p>}
            {isPreviewCurrent && preview.error !== null && (
              <p role="alert" className="error">
                {preview.error}
              </p>
            )}
            {isPreviewCurrent && preview.error === null && affected.length === 0 && (
              <p className="muted">No bookings are affected.</p>
            )}
            {affected.length > 0 && (
              <ul className="check-list">
                {affected.map((booking) => (
                  <li key={booking.booking_id}>
                    <span className="grow-text">
                      <Link to={bookingRequestPath(booking.booking_id)}>{booking.event_name}</Link>
                      <span className="muted small">
                        {' '}
                        {formatDateTime(booking.held_from)} – {formatDateTime(booking.held_until)}
                      </span>
                    </span>
                    <StatusBadge status={booking.status} />
                    {booking.already_marked && <Chip tone="warning" label="Already marked" />}
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {saveError && !isConfirming && (
          <p role="alert" className="error">
            {saveError}
          </p>
        )}

        <div className="cluster">
          <button type="submit" className="brand" disabled={isSaving || !canSave}>
            {editing === null ? 'Save closure' : 'Save changes'}
          </button>
          <button type="button" className="secondary" onClick={close} disabled={isSaving}>
            Cancel
          </button>
        </div>
        {period !== null && !isPreviewCurrent && (
          <p className="muted small">Save is available once the affected bookings have loaded.</p>
        )}
        {isPreviewCurrent && preview.error !== null && (
          <p className="muted small">
            Save is unavailable until the affected bookings can be checked.
          </p>
        )}
      </form>

      {isConfirming && (
        <ConfirmDialog
          title={`Block off time at ${venueName}`}
          confirmLabel="Block off time"
          tone="primary"
          isBusy={isSaving}
          error={saveError}
          onConfirm={save}
          onCancel={cancelConfirm}
        >
          <p>
            These bookings fall in that period. They are kept for reference. Events that were
            Confirmed or awaiting their safety check go back to Planning for their coordinators to
            find another venue; the others stay as they are.
          </p>
          <ul>
            {newlyAffected.map((booking) => (
              <li key={booking.booking_id}>{booking.event_name}</li>
            ))}
          </ul>
        </ConfirmDialog>
      )}
    </>
  )
}
