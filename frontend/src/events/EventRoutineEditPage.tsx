import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router'
import { formatApiError } from '../api/client'
import {
  getEvent,
  updateEventRoutineInformation,
  type EventDetail,
  type EventRoutineInput,
} from '../api/events'
import { useAuth } from '../auth/authContext'
import { PageHeader } from '../components/PageHeader'
import { TERMINAL_STATUSES } from './eventStatus'
import { LoadingState } from '../layout/LoadingState'
import { eventPath } from '../routes'
import { useLoaded } from '../shared/useLoaded'

interface RoutineForm {
  internal_notes: string
}

function formFromEvent(event: EventDetail): RoutineForm {
  return { internal_notes: event.internal_notes ?? '' }
}

/** Only the fields that differ from `saved`, so a save with nothing changed sends an empty body
 * and the backend skips the write and the audit entry. */
function dirtyFieldsInput(form: RoutineForm, saved: RoutineForm): EventRoutineInput {
  const input: EventRoutineInput = {}
  if (form.internal_notes !== saved.internal_notes) {
    input.internal_notes = form.internal_notes.trim() || null
  }
  return input
}

function isUnchanged(form: RoutineForm, saved: RoutineForm): boolean {
  return form.internal_notes === saved.internal_notes
}

/**
 * Story 7.2 AC1-AC3: the Event Coordinator assigned to this event edits its internal notes, the
 * only routine field, directly. Reached from 7.1's event details page; every other field,
 * including the description and contact details, lives there only, read-only, never here.
 */
export function EventRoutineEditPage() {
  const { eventId = '' } = useParams()
  const { user } = useAuth()
  const loadEvent = useCallback(() => getEvent(eventId), [eventId])
  const { data, error: loadError, setData } = useLoaded(loadEvent)
  // `data` can still be the previous event while a changed `eventId` is loading (useLoaded keeps
  // the last good value); gating on `id` hides it instead of letting a stale form save onto the
  // new event.
  const event = data && data.id === eventId ? data : null
  const [saved, setSaved] = useState<RoutineForm | null>(null)
  const [form, setForm] = useState<RoutineForm | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    if (!event) return
    const next = formFromEvent(event)
    setSaved(next)
    setForm(next)
  }, [event])

  function updateField<K extends keyof RoutineForm>(key: K, value: RoutineForm[K]) {
    setForm((current) => current && { ...current, [key]: value })
  }

  function handleDiscard() {
    if (saved) setForm(saved)
    setSaveError(null)
  }

  async function handleSubmit(submitEvent: FormEvent<HTMLFormElement>) {
    submitEvent.preventDefault()
    if (!form || !saved) return
    setSaveError(null)
    setIsSaving(true)
    try {
      const updated = await updateEventRoutineInformation(eventId, dirtyFieldsInput(form, saved))
      setData(updated)
    } catch (err) {
      setSaveError(formatApiError(err))
    } finally {
      setIsSaving(false)
    }
  }

  if (loadError) {
    return (
      <div className="page">
        <p role="alert" className="error">
          {loadError}
        </p>
      </div>
    )
  }
  if (!event || !form || !saved) return <LoadingState label="Loading the event…" />

  const isAssignedCoordinator = event.assigned_coordinator_id === user?.id
  const isTerminal = TERMINAL_STATUSES.includes(event.status)
  const backTo = eventPath(event.id)

  if (!isAssignedCoordinator || isTerminal) {
    return (
      <div className="page page-wide event-routine-edit-page">
        <PageHeader backTo={backTo} backLabel={event.name} title="Edit routine information" />
        <p className="muted">
          {isTerminal
            ? 'This event is completed, cancelled or rejected, so its routine information can no longer be edited.'
            : 'Only the Event Coordinator assigned to this event can edit its routine information.'}
        </p>
      </div>
    )
  }

  return (
    <div className="page page-wide event-routine-edit-page">
      <PageHeader
        backTo={backTo}
        backLabel={event.name}
        title="Edit routine information"
        subtitle="Small corrections are applied immediately."
      />

      <form className="stack" onSubmit={handleSubmit} noValidate>
        <fieldset className="card">
          <legend>Event information</legend>
          <div className="form-grid">
            <label className="span-all">
              Internal notes
              <textarea
                rows={3}
                placeholder="Coordinator-only; never shown to the organiser."
                value={form.internal_notes}
                onChange={(e) => updateField('internal_notes', e.target.value)}
              />
            </label>
          </div>
        </fieldset>

        <div className="form-actions">
          {saveError && (
            <p role="alert" className="error">
              {saveError}
            </p>
          )}
          <button
            type="button"
            className="secondary"
            disabled={isSaving || isUnchanged(form, saved)}
            onClick={handleDiscard}
          >
            Discard changes
          </button>
          <button type="submit" disabled={isSaving || isUnchanged(form, saved)}>
            {isSaving && <span className="spinner button-spinner" aria-hidden="true" />}
            Save changes
          </button>
        </div>
      </form>
    </div>
  )
}
