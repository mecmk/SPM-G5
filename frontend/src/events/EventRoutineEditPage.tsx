import { useEffect, useState, type FormEvent } from 'react'
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
import { LoadingState } from '../layout/LoadingState'
import { eventPath } from '../routes'

const TERMINAL_STATUSES: readonly string[] = ['COMPLETED', 'CANCELLED', 'REJECTED']

interface RoutineForm {
  description: string
  contact_name: string
  contact_email: string
  contact_phone: string
  internal_notes: string
}

function formFromEvent(event: EventDetail): RoutineForm {
  return {
    description: event.description ?? '',
    contact_name: event.contact_name ?? '',
    contact_email: event.contact_email ?? '',
    contact_phone: event.contact_phone ?? '',
    internal_notes: event.internal_notes ?? '',
  }
}

function inputFromForm(form: RoutineForm): EventRoutineInput {
  return {
    description: form.description.trim() || null,
    contact_name: form.contact_name.trim() || null,
    contact_email: form.contact_email.trim() || null,
    contact_phone: form.contact_phone.trim() || null,
    internal_notes: form.internal_notes.trim() || null,
  }
}

function isUnchanged(form: RoutineForm, saved: RoutineForm): boolean {
  return (
    form.description === saved.description &&
    form.contact_name === saved.contact_name &&
    form.contact_email === saved.contact_email &&
    form.contact_phone === saved.contact_phone &&
    form.internal_notes === saved.internal_notes
  )
}

/**
 * Story 7.2 AC1-AC3: the Event Coordinator assigned to this event edits its routine information
 * (description, contact details, internal notes) directly. Reached from 7.1's event details page;
 * every field that is not routine lives there only, read-only, never here.
 */
export function EventRoutineEditPage() {
  const { eventId = '' } = useParams()
  const { user } = useAuth()
  const [event, setEvent] = useState<EventDetail | null>(null)
  const [saved, setSaved] = useState<RoutineForm | null>(null)
  const [form, setForm] = useState<RoutineForm | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    getEvent(eventId)
      .then((data) => {
        if (cancelled) return
        setEvent(data)
        setSaved(formFromEvent(data))
        setForm(formFromEvent(data))
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [eventId])

  function updateField<K extends keyof RoutineForm>(key: K, value: RoutineForm[K]) {
    setForm((current) => current && { ...current, [key]: value })
  }

  function handleDiscard() {
    if (saved) setForm(saved)
    setSaveError(null)
  }

  async function handleSubmit(submitEvent: FormEvent<HTMLFormElement>) {
    submitEvent.preventDefault()
    if (!form) return
    setSaveError(null)
    setIsSaving(true)
    try {
      const updated = await updateEventRoutineInformation(eventId, inputFromForm(form))
      setEvent(updated)
      const nextSaved = formFromEvent(updated)
      setSaved(nextSaved)
      setForm(nextSaved)
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
              Description
              <textarea
                rows={4}
                value={form.description}
                onChange={(e) => updateField('description', e.target.value)}
              />
            </label>
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

        <fieldset className="card">
          <legend>Contact details</legend>
          <div className="form-grid">
            <label>
              Contact name
              <input
                maxLength={200}
                value={form.contact_name}
                onChange={(e) => updateField('contact_name', e.target.value)}
              />
            </label>
            <label>
              Contact email
              <input
                type="email"
                maxLength={254}
                value={form.contact_email}
                onChange={(e) => updateField('contact_email', e.target.value)}
              />
            </label>
            <label>
              Contact phone
              <input
                maxLength={50}
                value={form.contact_phone}
                onChange={(e) => updateField('contact_phone', e.target.value)}
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
