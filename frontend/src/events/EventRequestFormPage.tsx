import { useEffect, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import { formatApiError } from '../api/client'
import {
  createEvent,
  fetchEventReferenceData,
  getEvent,
  submitEvent,
  updateEvent,
  type EventDetail,
  type EventReferenceData,
} from '../api/events'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { ERROR_REGISTRY } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import { HOME_PATH, eventEditPath } from '../routes'
import { formatDateTime } from '../shared/format'
import {
  EMPTY_EVENT_FORM,
  EMPTY_FACILITY,
  EMPTY_NOTE,
  eventInputFrom,
  formFromEvent,
  newEquipmentDraft,
  toggleEntry,
  validateEventForm,
  type EquipmentDraft,
  type EventFormState,
  type FacilityDraft,
  type NoteDraft,
} from './eventRequestForm'

const NO_LAYOUT_PREFERENCE = ''
const NO_EQUIPMENT_CHOSEN = ''

/** Marks something a request needs before it can be submitted (story 2.1 AC10). */
function RequiredMark() {
  return (
    <span className="req" aria-hidden="true">
      *
    </span>
  )
}

/** The message a refused submission leaves for the edit page it lands on after saving. */
function noticeFrom(state: unknown): string | null {
  if (state && typeof state === 'object' && 'notice' in state && typeof state.notice === 'string') {
    return state.notice
  }
  return null
}

/**
 * Story 2.1 - an Event Organiser records a request and sends it for review.
 * AC1: name, purpose, description, proposed start and end, expected attendance. All of them are
 * needed to submit (AC10), and so is an answer to each of venue requirements and accessibility.
 * AC2/AC3: dates and whole numbers are checked here before anything is sent; the backend checks
 * them again.
 * AC4: venue requirements: a room layout, facilities (each optionally how many) and other
 * requirements, or "No venue requirements". Expected attendance doubles as the capacity the
 * venue must have.
 * AC5: accessibility needs, or "No accessibility needs". Either "none" box clears the other
 * choices in its section, so a request never says both. Left untouched, a draft is "not yet
 * specified".
 * AC6/AC7: any number of equipment items, each added, edited or removed until submission.
 * AC9-AC11: a request is submitted from this page, new or saved; the details are saved first, so
 * a refused submission never loses them. Once submitted the request is read-only.
 * Serves /events/new (creates a draft) and /events/:eventId/edit (edits it).
 */
export function EventRequestFormPage() {
  const { eventId } = useParams()
  const isEditing = eventId !== undefined
  const navigate = useNavigate()
  const location = useLocation()
  const [reference, setReference] = useState<EventReferenceData | null>(null)
  const [event, setEvent] = useState<EventDetail | null>(null)
  const [form, setForm] = useState<EventFormState | null>(isEditing ? null : EMPTY_EVENT_FORM)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(noticeFrom(location.state))
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    const eventRequest = eventId ? getEvent(eventId) : Promise.resolve(null)
    Promise.all([fetchEventReferenceData(), eventRequest])
      .then(([referenceData, loaded]) => {
        if (cancelled) return
        setReference(referenceData)
        if (loaded) {
          setEvent(loaded)
          setForm(formFromEvent(loaded))
        }
      })
      .catch((err) => {
        if (!cancelled) setLoadError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [eventId])

  const isReadOnly = event !== null && event.status !== 'DRAFT'

  function updateField<K extends keyof EventFormState>(key: K, value: EventFormState[K]) {
    setForm((current) => current && { ...current, [key]: value })
  }

  /** Choosing "no venue requirements" clears the other venue choices, so they never disagree. */
  function toggleNoVenueRequirements(isChecked: boolean) {
    setForm(
      (current) =>
        current && {
          ...current,
          hasNoVenueRequirements: isChecked,
          layoutCode: isChecked ? NO_LAYOUT_PREFERENCE : current.layoutCode,
          facilities: isChecked ? {} : current.facilities,
          venueNotes: isChecked ? '' : current.venueNotes,
        },
    )
  }

  function updateLayout(code: string) {
    setForm(
      (current) =>
        current && {
          ...current,
          layoutCode: code,
          hasNoVenueRequirements:
            code !== NO_LAYOUT_PREFERENCE ? false : current.hasNoVenueRequirements,
        },
    )
  }

  function toggleFacility(code: string) {
    setForm(
      (current) =>
        current && {
          ...current,
          hasNoVenueRequirements: false,
          facilities: toggleEntry(current.facilities, code, EMPTY_FACILITY),
        },
    )
  }

  function updateFacility(code: string, change: Partial<FacilityDraft>) {
    setForm(
      (current) =>
        current && {
          ...current,
          facilities: { ...current.facilities, [code]: { ...current.facilities[code], ...change } },
        },
    )
  }

  function updateVenueNotes(text: string) {
    setForm(
      (current) =>
        current && {
          ...current,
          venueNotes: text,
          hasNoVenueRequirements: text.trim() ? false : current.hasNoVenueRequirements,
        },
    )
  }

  /** Choosing "no accessibility needs" clears any needs, so the two can never disagree. */
  function toggleNoAccessibilityNeeds(isChecked: boolean) {
    setForm(
      (current) =>
        current && {
          ...current,
          hasNoAccessibilityNeeds: isChecked,
          accessibility: isChecked ? {} : current.accessibility,
          accessibilityNotes: isChecked ? '' : current.accessibilityNotes,
        },
    )
  }

  function toggleAccessibility(code: string) {
    setForm(
      (current) =>
        current && {
          ...current,
          hasNoAccessibilityNeeds: false,
          accessibility: toggleEntry(current.accessibility, code, EMPTY_NOTE),
        },
    )
  }

  function updateAccessibilityNotes(code: string, notes: string) {
    setForm(
      (current) =>
        current && { ...current, accessibility: { ...current.accessibility, [code]: { notes } } },
    )
  }

  function updateAccessibilityDescription(text: string) {
    setForm(
      (current) =>
        current && {
          ...current,
          accessibilityNotes: text,
          hasNoAccessibilityNeeds: text.trim() ? false : current.hasNoAccessibilityNeeds,
        },
    )
  }

  function addEquipment() {
    setForm(
      (current) =>
        current && { ...current, equipment: [...current.equipment, newEquipmentDraft()] },
    )
  }

  function updateEquipment(key: number, change: Partial<EquipmentDraft>) {
    setForm(
      (current) =>
        current && {
          ...current,
          equipment: current.equipment.map((line) =>
            line.key === key ? { ...line, ...change } : line,
          ),
        },
    )
  }

  function removeEquipment(key: number) {
    setForm(
      (current) =>
        current && { ...current, equipment: current.equipment.filter((line) => line.key !== key) },
    )
  }

  /** Validate, then create the draft or save the edits. Null when nothing was saved. */
  async function saveDraft(): Promise<EventDetail | null> {
    if (!form) return null
    const problem = validateEventForm(form, event)
    if (problem) {
      setSaveError(ERROR_REGISTRY[problem].message)
      return null
    }
    setSaveError(null)
    const input = eventInputFrom(form)
    return eventId ? updateEvent(eventId, input) : createEvent(input)
  }

  async function handleSaveDraft(submission: FormEvent<HTMLFormElement>) {
    submission.preventDefault()
    setIsSaving(true)
    try {
      const saved = await saveDraft()
      if (!saved) return
      if (isEditing) {
        setEvent(saved)
        setForm(formFromEvent(saved))
      } else {
        navigate(eventEditPath(saved.id), { replace: true })
      }
    } catch (err) {
      setSaveError(formatApiError(err))
    } finally {
      setIsSaving(false)
    }
  }

  /**
   * AC9-AC11: save the details, then submit them. If the backend refuses the submission (it names
   * whatever is missing), the details stay saved as a draft, and the message is shown on the
   * draft's edit page.
   */
  async function handleSubmitRequest() {
    setIsSaving(true)
    try {
      const saved = await saveDraft()
      if (!saved) return
      try {
        const submitted = await submitEvent(saved.id, saved.name)
        if (isEditing) {
          setEvent(submitted)
          setForm(formFromEvent(submitted))
        } else {
          navigate(eventEditPath(saved.id), { replace: true })
        }
      } catch (err) {
        if (isEditing) {
          setEvent(saved)
          setForm(formFromEvent(saved))
          setSaveError(formatApiError(err))
        } else {
          navigate(eventEditPath(saved.id), {
            replace: true,
            state: { notice: formatApiError(err) },
          })
        }
      }
    } catch (err) {
      setSaveError(formatApiError(err))
    } finally {
      setIsSaving(false)
    }
  }

  const title = isEditing ? (event?.name ?? 'Event request') : 'New event request'
  const subtitle =
    event && isReadOnly ? (
      <>
        <StatusBadge status={event.status} />{' '}
        {event.submitted_at && <span>Submitted on {formatDateTime(event.submitted_at)}</span>}
      </>
    ) : (
      <>
        {event && <StatusBadge status={event.status} />}{' '}
        <span>
          Fields marked * and an answer to venue requirements and accessibility are needed to
          submit. Only the event name is needed to save a draft.
        </span>
      </>
    )

  return (
    <div className="page">
      <PageHeader backTo={HOME_PATH} backLabel="Main page" title={title} subtitle={subtitle} />

      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      {!loadError && (!form || !reference) && <LoadingState label="Loading request…" />}

      {form && reference && (
        <form className="stack venue-form" onSubmit={handleSaveDraft} noValidate>
          <fieldset className="card" disabled={isReadOnly}>
            <legend>Event details</legend>
            <div className="form-grid">
              <label className="span-2">
                Event name <RequiredMark />
                <input
                  required
                  value={form.name}
                  onChange={(e) => updateField('name', e.target.value)}
                />
              </label>
              <label>
                Expected attendance <RequiredMark />
                <input
                  type="number"
                  inputMode="numeric"
                  min={1}
                  step={1}
                  value={form.attendance}
                  onChange={(e) => updateField('attendance', e.target.value)}
                />
              </label>
              <label className="span-all">
                Purpose <RequiredMark />
                <input
                  placeholder="Why the event is being held"
                  value={form.purpose}
                  onChange={(e) => updateField('purpose', e.target.value)}
                />
              </label>
              <label className="span-all">
                Description <RequiredMark />
                <textarea
                  rows={3}
                  value={form.description}
                  onChange={(e) => updateField('description', e.target.value)}
                />
              </label>
              <label className="span-2">
                Proposed start <RequiredMark />
                <input
                  type="datetime-local"
                  value={form.startsAt}
                  onChange={(e) => updateField('startsAt', e.target.value)}
                />
              </label>
              <label>
                Proposed end <RequiredMark />
                <input
                  type="datetime-local"
                  value={form.endsAt}
                  onChange={(e) => updateField('endsAt', e.target.value)}
                />
              </label>
            </div>
            <p className="form-hint">All times are Singapore time.</p>
          </fieldset>

          <fieldset className="card" disabled={isReadOnly}>
            <legend>
              Venue requirements <RequiredMark />
            </legend>
            <p className="form-hint">
              Choose what the venue needs, or tick &ldquo;No venue requirements&rdquo;. We match
              venues to your expected attendance, so there is no separate capacity to enter.
            </p>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.hasNoVenueRequirements}
                onChange={(e) => toggleNoVenueRequirements(e.target.checked)}
              />
              No venue requirements
            </label>
            <div className="form-grid">
              <label className="span-2">
                Room layout
                <select value={form.layoutCode} onChange={(e) => updateLayout(e.target.value)}>
                  <option value={NO_LAYOUT_PREFERENCE}>No preference</option>
                  {reference.layouts.map((layout) => (
                    <option key={layout.code} value={layout.code}>
                      {layout.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <ul className="check-list">
              {reference.facilities.map((item) => {
                const selected: FacilityDraft | undefined = form.facilities[item.code]
                return (
                  <li key={item.code}>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={selected !== undefined}
                        onChange={() => toggleFacility(item.code)}
                      />
                      {item.name}
                    </label>
                    {selected && (
                      <div className="inline-fields">
                        <input
                          type="number"
                          inputMode="numeric"
                          min={1}
                          step={1}
                          className="inline-number"
                          placeholder="How many"
                          aria-label={`${item.name} quantity`}
                          value={selected.quantity}
                          onChange={(e) => updateFacility(item.code, { quantity: e.target.value })}
                        />
                        <input
                          placeholder="Notes"
                          aria-label={`${item.name} notes`}
                          value={selected.notes}
                          onChange={(e) => updateFacility(item.code, { notes: e.target.value })}
                        />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
            <label>
              Other venue requirements
              <textarea
                rows={2}
                value={form.venueNotes}
                onChange={(e) => updateVenueNotes(e.target.value)}
              />
            </label>
          </fieldset>

          <fieldset className="card" disabled={isReadOnly}>
            <legend>
              Accessibility <RequiredMark />
            </legend>
            <p className="form-hint">
              Choose what attendees need, or tick &ldquo;No accessibility needs&rdquo;.
            </p>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.hasNoAccessibilityNeeds}
                onChange={(e) => toggleNoAccessibilityNeeds(e.target.checked)}
              />
              No accessibility needs
            </label>
            <ul className="check-list">
              {reference.accessibility_features.map((item) => {
                const selected: NoteDraft | undefined = form.accessibility[item.code]
                return (
                  <li key={item.code}>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={selected !== undefined}
                        onChange={() => toggleAccessibility(item.code)}
                      />
                      {item.name}
                    </label>
                    {selected && (
                      <div className="inline-fields">
                        <input
                          placeholder="Notes"
                          aria-label={`${item.name} notes`}
                          value={selected.notes}
                          onChange={(e) => updateAccessibilityNotes(item.code, e.target.value)}
                        />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
            <label>
              Accessibility notes
              <textarea
                rows={2}
                placeholder="Anything else we should know"
                value={form.accessibilityNotes}
                onChange={(e) => updateAccessibilityDescription(e.target.value)}
              />
            </label>
          </fieldset>

          <fieldset className="card" disabled={isReadOnly}>
            <legend>Equipment</legend>
            {form.equipment.length === 0 && (
              <p className="form-hint">No equipment requested. Add each item you need.</p>
            )}
            {form.equipment.map((line, index) => (
              <fieldset key={line.key} className="equipment-item">
                <legend>{`Equipment item ${index + 1}`}</legend>
                <div className="form-grid">
                  <label className="span-2">
                    Equipment type
                    <select
                      value={line.typeCode}
                      onChange={(e) => updateEquipment(line.key, { typeCode: e.target.value })}
                    >
                      <option value={NO_EQUIPMENT_CHOSEN}>Choose equipment…</option>
                      {line.typeCode !== NO_EQUIPMENT_CHOSEN &&
                        !reference.equipment_types.some((type) => type.code === line.typeCode) && (
                          <option value={line.typeCode}>{line.typeName}</option>
                        )}
                      {reference.equipment_types.map((type) => (
                        <option key={type.code} value={type.code}>
                          {type.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Quantity
                    <input
                      type="number"
                      inputMode="numeric"
                      min={1}
                      step={1}
                      value={line.quantity}
                      onChange={(e) => updateEquipment(line.key, { quantity: e.target.value })}
                    />
                  </label>
                  <label className="span-all">
                    Technical notes
                    <input
                      value={line.notes}
                      onChange={(e) => updateEquipment(line.key, { notes: e.target.value })}
                    />
                  </label>
                </div>
                <button
                  type="button"
                  className="secondary button-sm"
                  onClick={() => removeEquipment(line.key)}
                >
                  Remove
                </button>
              </fieldset>
            ))}
            <button type="button" className="secondary" onClick={addEquipment}>
              Add equipment
            </button>
          </fieldset>

          {!isReadOnly && (
            <div className="form-actions">
              {saveError && (
                <p role="alert" className="error">
                  {saveError}
                </p>
              )}
              <Link to={HOME_PATH} className="button secondary">
                Cancel
              </Link>
              <button type="submit" className="secondary" disabled={isSaving}>
                Save draft
              </button>
              <button type="button" disabled={isSaving} onClick={handleSubmitRequest}>
                {isSaving && <span className="spinner button-spinner" aria-hidden="true" />}
                Submit request
              </button>
            </div>
          )}
        </form>
      )}
    </div>
  )
}
