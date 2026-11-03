import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { ApiError, formatApiError } from '../api/client'
import {
  addUnavailability,
  bookingsInRefusal,
  editUnavailability,
  fetchAffectedBookings,
  UNAVAILABILITY_REASON_NAMES,
  type AffectedBooking,
  type UnavailabilityInput,
  type UnavailabilityReason,
} from '../api/venues'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { StatusBadge } from '../components/StatusBadge'
import type { DayClosure } from '../components/venueCalendarDays'
import { ERROR_REGISTRY } from '../errors/registry'
import { bookingRequestPath } from '../routes'
import { CANCEL, formatDateTime, instantToInput, inputToInstant } from '../shared/format'
import {
  BLOCK_OFF_LABEL,
  EDIT_BLOCK_OFF_LABEL,
  END_BOOKINGS_CANCEL_LABEL,
  END_BOOKINGS_LABEL,
  END_BOOKINGS_WARNING,
  blockOffTitle,
} from './blockOffLabels'

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

/** What the form held when it opened on a closure, as the form holds it: the inputs' own strings. */
interface OpenedForm {
  starts: string
  ends: string
  reason: string
  description: string
}

/**
 * The fields of `input` the person changed since the form opened. The form's own strings are
 * compared, not instants: a closure made through the API may start at a second the form's minutes
 * cannot show, and an instant rebuilt from them would look like a move of its start.
 */
function changedFields(
  opened: OpenedForm,
  form: OpenedForm,
  input: UnavailabilityInput,
): Partial<UnavailabilityInput> {
  const changes: Partial<UnavailabilityInput> = {}
  if (form.starts !== opened.starts) changes.starts_at = input.starts_at
  if (form.ends !== opened.ends) changes.ends_at = input.ends_at
  if (form.reason !== opened.reason) changes.reason = input.reason
  if (form.description.trim() !== opened.description.trim()) changes.description = input.description
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
 * Story 9.4 AC1/AC2/AC5/AC9: Venue Staff block off time at the venue from its Edit venue page. The form takes a
 * start, an end, a reason and a description, which every reason needs. An end that is not after
 * the start is refused in the form, beside the fields, before anything is sent. Once both ends
 * make a period, the pending and approved bookings it would affect - setup and teardown included -
 * are listed before Save. Story 9.5 AC1: saving rejects each pending request and cancels each
 * approved booking listed, so Save asks first, in a confirmation that lists them; the ones listed
 * are sent as confirmed (`confirmed_booking_ids`), and a booking raised since refuses the save,
 * which reopens the confirmation with the fresh list. A refusal from the server, such as a missing description, shows the backend's own sentence and
 * nothing is saved. The page only shows this to a role holding the manage permission; the backend
 * refuses everyone else.
 *
 * Story 9.4 AC6: the same form edits a closure - its start, end, reason and description - opened
 * from the closure's row. Only the bookings its change newly covers (a start moved earlier, an end
 * moved later) are listed and ask for a confirmation; a change of text lists none.
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
  /** What an edit opened with, to tell what the person changed. */
  const [opened] = useState<OpenedForm | null>(() =>
    editing === null
      ? null
      : {
          starts: instantToInput(editing.startsAt),
          ends: instantToInput(editing.endsAt),
          reason: editing.reason,
          description: editing.description ?? '',
        },
  )
  /** Counts the preview's retries, so "Check again" asks once more for the same dates. */
  const [previewAttempt, setPreviewAttempt] = useState(0)
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
  /** Story 9.5 AC1 (D22): an edit that leaves the start and the end where they were adds no time,
   *  so it covers no booking and has nothing to list. */
  const isRangeUnchanged = opened !== null && starts === opened.starts && ends === opened.ends

  useEffect(() => {
    if (period === null || previewKey === null || isRangeUnchanged) return
    let cancelled = false
    fetchAffectedBookings(venueId, period.startsAt, period.endsAt, editing?.id)
      .then((bookings) => {
        if (!cancelled) setPreview({ key: previewKey, bookings, error: null })
      })
      .catch((err) => {
        if (!cancelled) setPreview({ key: previewKey, bookings: null, error: formatApiError(err) })
      })
    return () => {
      cancelled = true
    }
  }, [venueId, editing, period, previewKey, previewAttempt, isRangeUnchanged])

  const current =
    !isRangeUnchanged && preview !== null && preview.key === previewKey ? preview : null
  const isPreviewCurrent = isRangeUnchanged || current !== null
  const previewError = current?.error ?? null
  const affected = current?.bookings ?? []
  /** Story 9.4 AC2: the form saves only once the list for these very dates has answered. */
  const canSave = period !== null && isPreviewCurrent && previewError === null
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

  function checkAgain() {
    setPreview(null)
    setPreviewAttempt((attempt) => attempt + 1)
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
      const confirmed = affected.map((booking) => booking.booking_id)
      if (editing === null || opened === null) {
        await addUnavailability(venueId, venueName, input, confirmed)
      } else {
        // Only what changed is sent, so an edit never overwrites a field someone else changed.
        const changes = changedFields(opened, { starts, ends, reason, description }, input)
        if (Object.keys(changes).length > 0) {
          await editUnavailability(venueId, editing.id, changes, confirmed)
        }
      }
      close()
      onSaved()
    } catch (err) {
      setSaveError(formatApiError(err))
      // A booking was raised since the list was shown: the refusal carries the fresh list, which
      // replaces it, and the confirmation reopens on it.
      const fresh = err instanceof ApiError ? bookingsInRefusal(err.detail) : null
      if (fresh !== null && previewKey !== null) {
        setPreview({ key: previewKey, bookings: fresh, error: null })
        setIsConfirming(true)
        return
      }
      setIsConfirming(false)
      // The closure is gone (404) or no longer what the form opened on (409), so the page's
      // calendar is out of date.
      if (
        err instanceof ApiError &&
        (err.code === 'UNAVAILABILITY_NOT_FOUND' || err.status === 409)
      ) {
        onSaved()
      }
    } finally {
      setIsSaving(false)
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSave) return
    if (affected.length > 0) {
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
          {BLOCK_OFF_LABEL}
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
        aria-label={editing === null ? blockOffTitle(false, venueName) : EDIT_BLOCK_OFF_LABEL}
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
              required
              aria-required="true"
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
            <div role="status" aria-live="polite" className="stack">
              {!isPreviewCurrent && <p className="muted">Checking the venue&apos;s bookings…</p>}
              {isPreviewCurrent && previewError === null && affected.length === 0 && (
                <p className="muted">No bookings are affected.</p>
              )}
              {isPreviewCurrent && previewError === null && affected.length > 0 && (
                <p className="muted">
                  {affected.length === 1
                    ? '1 booking is affected.'
                    : `${affected.length} bookings are affected.`}
                </p>
              )}
            </div>
            {isPreviewCurrent && previewError !== null && (
              <p role="alert" className="error">
                {previewError}{' '}
                <button type="button" className="secondary button-sm" onClick={checkAgain}>
                  Check again
                </button>
              </p>
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
            Save closure
          </button>
          <button type="button" className="secondary" onClick={close} disabled={isSaving}>
            {CANCEL}
          </button>
        </div>
        {period !== null && !isPreviewCurrent && (
          <p className="muted small">Save is available once the affected bookings have loaded.</p>
        )}
        {isPreviewCurrent && previewError !== null && (
          <p className="muted small">
            Save is unavailable until the affected bookings can be checked.
          </p>
        )}
      </form>

      {isConfirming && (
        <ConfirmDialog
          title={blockOffTitle(editing !== null, venueName)}
          confirmLabel={END_BOOKINGS_LABEL}
          cancelLabel={END_BOOKINGS_CANCEL_LABEL}
          tone="primary"
          isBusy={isSaving}
          error={saveError}
          onConfirm={save}
          onCancel={cancelConfirm}
        >
          <p>{END_BOOKINGS_WARNING}</p>
          <ul>
            {affected.map((booking) => (
              <li key={booking.booking_id}>
                {booking.event_name} <StatusBadge status={booking.status} />
              </li>
            ))}
          </ul>
        </ConfirmDialog>
      )}
    </>
  )
}
