import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { formatApiError } from '../api/client'
import {
  addUnavailability,
  fetchAffectedBookings,
  OTHER_UNAVAILABILITY_REASON,
  UNAVAILABILITY_REASON_NAMES,
  type AffectedBooking,
  type UnavailabilityReason,
} from '../api/venues'
import { Chip } from '../components/Chip'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { StatusBadge } from '../components/StatusBadge'
import { bookingRequestPath } from '../routes'
import { formatDateTime, inputToInstant } from '../shared/format'

export interface VenueUnavailabilitySectionProps {
  venueId: string
  venueName: string
  /** Called once a closure is saved, so the page loads its calendar again. */
  onSaved: () => void
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
 * Story 9.4 AC1/AC2/AC5/AC9: Venue Staff mark the venue unavailable from its page. The form takes a
 * start, an end, a reason and a description, which Other requires. Once both ends make a period,
 * the pending and approved bookings it would affect - setup and teardown included - are listed
 * before Save; saving is allowed with some, after one confirmation that names them. A refusal,
 * such as an end not after the start or an Other without a description, shows the backend's
 * sentence and nothing is saved. The page only shows this to a role holding the manage permission;
 * the backend refuses everyone else.
 */
export function VenueUnavailabilitySection({
  venueId,
  venueName,
  onSaved,
}: VenueUnavailabilitySectionProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [starts, setStarts] = useState('')
  const [ends, setEnds] = useState('')
  const [reason, setReason] = useState<UnavailabilityReason>(DEFAULT_REASON)
  const [description, setDescription] = useState('')
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [isConfirming, setIsConfirming] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

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
  const isOther = reason === OTHER_UNAVAILABILITY_REASON

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
  }

  async function save() {
    if (period === null) return
    setIsSaving(true)
    setSaveError(null)
    try {
      await addUnavailability(venueId, venueName, {
        starts_at: period.startsAt,
        ends_at: period.endsAt,
        reason,
        description: description.trim() === '' ? null : description.trim(),
      })
      close()
      onSaved()
    } catch (err) {
      setSaveError(formatApiError(err))
      setIsConfirming(false)
    } finally {
      setIsSaving(false)
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
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
          Mark unavailable
        </button>
      </div>
    )
  }

  return (
    <>
      <form className="stack" onSubmit={handleSubmit} noValidate aria-label="Mark unavailable">
        <div className="form-grid">
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
            Description
            {isOther && (
              <>
                {' '}
                <span className="req" aria-hidden="true">
                  *
                </span>
              </>
            )}
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
          <button type="submit" className="brand" disabled={isSaving || period === null}>
            Save closure
          </button>
          <button type="button" className="secondary" onClick={close} disabled={isSaving}>
            Cancel
          </button>
        </div>
      </form>

      {isConfirming && (
        <ConfirmDialog
          title={`Mark ${venueName} unavailable?`}
          confirmLabel="Mark unavailable"
          tone="primary"
          isBusy={isSaving}
          error={saveError}
          onConfirm={save}
          onCancel={cancelConfirm}
        >
          <p>
            These bookings fall in that period. They are kept for reference, and each event goes
            back to Planning for its coordinator to find another venue.
          </p>
          <ul>
            {affected.map((booking) => (
              <li key={booking.booking_id}>{booking.event_name}</li>
            ))}
          </ul>
        </ConfirmDialog>
      )}
    </>
  )
}
