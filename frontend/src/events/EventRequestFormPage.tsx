import { useEffect, useState, type ChangeEvent, type DragEvent, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import { formatApiError, mediaUrl } from '../api/client'
import {
  createEvent,
  fetchEquipmentAvailability,
  fetchEventReferenceData,
  getEvent,
  removeCoverImage,
  submitEvent,
  updateEvent,
  uploadCoverImage,
  type EventDetail,
  type EventReferenceData,
} from '../api/events'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { ERROR_REGISTRY, type ErrorCode } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import { HOME_PATH, eventEditPath } from '../routes'
import { formatDateTime, inputToInstant, nowAsInput } from '../shared/format'
import {
  CONTACT_EMAIL_MAX_LENGTH,
  CONTACT_NAME_MAX_LENGTH,
  CONTACT_PHONE_MAX_LENGTH,
  COVER_IMAGE_TYPES,
  EMPTY_EVENT_FORM,
  EMPTY_FACILITY,
  EMPTY_NOTE,
  FIELD_ID,
  MAX_EVENT_DAYS,
  MAX_LEAD_YEARS,
  eventInputFrom,
  formFromEvent,
  getEquipmentQuantityId,
  getEquipmentTypeId,
  getFacilityQuantityId,
  getLatestEndInput,
  getLatestStartInput,
  getLiveProblems,
  getMissingForSubmission,
  isEquipmentTypeTaken,
  newEquipmentDraft,
  toggleEntry,
  validateCoverImage,
  validateDates,
  validateEventForm,
  type EquipmentDraft,
  type EventFormState,
  type FacilityDraft,
  type FormProblem,
  type NoteDraft,
} from './eventRequestForm'
import { readBackState } from './backState'

const NO_LAYOUT_PREFERENCE = ''
const NO_EQUIPMENT_CHOSEN = ''

/** Story 2.1 AC14: a picture the organiser has chosen and that is not uploaded yet. */
interface ChosenPicture {
  file: File
  /** An object URL for the preview, revoked when the picture is replaced or the page closes. */
  previewUrl: string
}

/** What saving a draft leaves: the draft as saved, and why its picture was not (if it was not). */
interface SavedDraft {
  event: EventDetail
  pictureProblem: string | null
}

/**
 * A date field the person started typing but did not finish (say, no AM or PM). The browser then
 * reports an empty value, which the form would otherwise read as "no date".
 */
function findIncompleteDateField(): string | null {
  for (const id of [FIELD_ID.startsAt, FIELD_ID.endsAt]) {
    const input = document.getElementById(id)
    if (input instanceof HTMLInputElement && input.validity.badInput) return id
  }
  return null
}

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
  // Story 2.6: the back link goes to wherever the person came from, and the saves below keep that
  // across the move from /events/new to the saved request's own address.
  const backState = readBackState(location.state)
  const [reference, setReference] = useState<EventReferenceData | null>(null)
  const [event, setEvent] = useState<EventDetail | null>(null)
  const [form, setForm] = useState<EventFormState | null>(isEditing ? null : EMPTY_EVENT_FORM)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(noticeFrom(location.state))
  const [isSaving, setIsSaving] = useState(false)
  // Story 2.1 AC14: the picture is uploaded along with the details, when they are saved.
  const [picture, setPicture] = useState<ChosenPicture | null>(null)
  const [isPictureRemoved, setIsPictureRemoved] = useState(false)
  const [pictureProblem, setPictureProblem] = useState<ErrorCode | null>(null)
  const [isDraggingPicture, setIsDraggingPicture] = useState(false)
  // The name is only called empty once the person has been in the field and left it.
  const [isNameTouched, setIsNameTouched] = useState(false)
  // How many of each equipment type are free for the dates in the form, tagged with the dates it
  // was fetched for so an old answer is never shown against other dates.
  const [availability, setAvailability] = useState<{
    key: string
    byType: Record<string, number>
  } | null>(null)
  const [availabilityRefresh, setAvailabilityRefresh] = useState(0)
  // The field a refused save is about, tied to the form as it was then, so any edit clears it.
  // A date field left half-typed, noticed as the person types or leaves it.
  const [incompleteDateId, setIncompleteDateId] = useState<string | null>(null)
  const [invalidField, setInvalidField] = useState<{ id: string; form: EventFormState } | null>(
    null,
  )

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

  useEffect(() => {
    return () => {
      if (picture) URL.revokeObjectURL(picture.previewUrl)
    }
  }, [picture])

  const isReadOnly = event !== null && event.status !== 'DRAFT'
  const savedPictureUrl = isPictureRemoved ? null : mediaUrl(event?.cover_image_url ?? null)
  const shownPictureUrl = picture ? picture.previewUrl : savedPictureUrl

  /** The problem with the dates as they stand now, said under them without waiting for a save. */
  const dateProblem: FormProblem | null = incompleteDateId
    ? { code: 'EVENT_DATE_INCOMPLETE', fieldId: incompleteDateId }
    : form
      ? validateDates(form, event)
      : null

  function noteIncompleteDate() {
    setIncompleteDateId(findIncompleteDateField())
  }

  function updateDate(key: 'startsAt' | 'endsAt', value: string) {
    updateField(key, value)
    noteIncompleteDate()
  }

  // Availability is asked for once both dates are usable, and again after a refused submission.
  const datesKey =
    form && form.startsAt && form.endsAt && !dateProblem && !isReadOnly
      ? `${form.startsAt}|${form.endsAt}|${availabilityRefresh}`
      : null
  const availabilityByType =
    availability !== null && availability.key === datesKey ? availability.byType : null

  useEffect(() => {
    if (datesKey === null) return
    const [startsAt, endsAt] = datesKey.split('|')
    let cancelled = false
    fetchEquipmentAvailability(inputToInstant(startsAt), inputToInstant(endsAt))
      .then((rows) => {
        if (cancelled) return
        const byType = Object.fromEntries(rows.map((r) => [r.equipment_type_code, r.available]))
        setAvailability({ key: datesKey, byType })
      })
      .catch(() => {
        // Availability is a help while filling in; saving and submitting check it again.
      })
    return () => {
      cancelled = true
    }
  }, [datesKey])

  // Problems with the name and the numbers, said next to each field as it is typed.
  const liveProblems: Record<string, ErrorCode> = {
    ...(form ? getLiveProblems(form, availabilityByType) : {}),
    ...(form && isNameTouched && !form.name.trim()
      ? { [FIELD_ID.name]: 'EVENT_NAME_REQUIRED' as ErrorCode }
      : {}),
  }
  const missingForSubmission = form ? getMissingForSubmission(form) : []

  /** What the row says about stock: how many are free. */
  function equipmentAvailabilityNote(line: EquipmentDraft) {
    if (isReadOnly || line.typeCode === NO_EQUIPMENT_CHOSEN) return null
    if (datesKey === null) {
      return <p className="form-hint">Choose the start and end to see how many are available.</p>
    }
    if (availabilityByType === null) return <p className="form-hint">Checking availability…</p>
    const available = availabilityByType[line.typeCode]
    if (available === undefined) return null
    return <p className="form-hint">{available} available for these dates</p>
  }

  /** The id, and the invalid mark when the last save was refused because of this field. */
  function fieldProps(id: string) {
    const isInvalid =
      (invalidField !== null && invalidField.form === form && invalidField.id === id) ||
      dateProblem?.fieldId === id ||
      id in liveProblems
    return { id, 'aria-invalid': isInvalid ? true : undefined }
  }

  /** What is wrong with a field's value right now, said next to it. */
  function renderProblem(id: string) {
    const code = liveProblems[id]
    return code ? <span className="field-error">{ERROR_REGISTRY[code].message}</span> : null
  }

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

  /** Take a file the person chose or dropped, unless it is certain to be refused. */
  function choosePicture(file: File | undefined) {
    if (file === undefined || isReadOnly) return
    const problem = validateCoverImage(file)
    setPictureProblem(problem)
    if (problem !== null) return
    setPicture({ file, previewUrl: URL.createObjectURL(file) })
    setIsPictureRemoved(false)
  }

  function handlePictureInput(change: ChangeEvent<HTMLInputElement>) {
    choosePicture(change.target.files?.[0])
    // So choosing the same file again still counts as a change.
    change.target.value = ''
  }

  function handlePictureDragOver(drag: DragEvent<HTMLDivElement>) {
    drag.preventDefault()
    if (!isReadOnly) setIsDraggingPicture(true)
  }

  function handlePictureDragLeave() {
    setIsDraggingPicture(false)
  }

  function handlePictureDrop(drag: DragEvent<HTMLDivElement>) {
    drag.preventDefault()
    setIsDraggingPicture(false)
    choosePicture(drag.dataTransfer.files[0])
  }

  function removePicture() {
    setPicture(null)
    setPictureProblem(null)
    setIsPictureRemoved(true)
  }

  /** Upload the chosen picture, or remove the one the person took off. */
  async function applyPicture(saved: EventDetail, shouldNotify: boolean): Promise<EventDetail> {
    if (picture) return uploadCoverImage(saved.id, picture.file, { shouldNotify })
    if (isPictureRemoved && saved.cover_image_url !== null) {
      return removeCoverImage(saved.id, { shouldNotify })
    }
    return saved
  }

  /**
   * Validate, then create the draft or save the edits, then its picture. Null when nothing was
   * saved. A picture that fails leaves the draft saved, and says so, rather than losing the draft.
   * `shouldNotify` is false when submitting, which says only that the request was submitted.
   */
  async function saveDraft(shouldNotify: boolean): Promise<SavedDraft | null> {
    if (!form) return null
    const incompleteFieldId = findIncompleteDateField()
    const problem: FormProblem | null = incompleteFieldId
      ? { code: 'EVENT_DATE_INCOMPLETE', fieldId: incompleteFieldId }
      : validateEventForm(form, event, availabilityByType)
    if (problem) {
      setSaveError(ERROR_REGISTRY[problem.code].message)
      setInvalidField({ id: problem.fieldId, form })
      document.getElementById(problem.fieldId)?.focus()
      return null
    }
    setSaveError(null)
    const input = eventInputFrom(form)
    const saved = eventId
      ? await updateEvent(eventId, input, { shouldNotify })
      : await createEvent(input, { shouldNotify })
    try {
      const withPicture = await applyPicture(saved, shouldNotify)
      setPicture(null)
      setIsPictureRemoved(false)
      return { event: withPicture, pictureProblem: null }
    } catch (err) {
      return { event: saved, pictureProblem: formatApiError(err) }
    }
  }

  /** Show a draft that has just been saved: in place when editing, else on its own address. */
  function showSavedDraft(saved: EventDetail, problem: string | null) {
    if (isEditing) {
      setEvent(saved)
      setForm(formFromEvent(saved))
      setSaveError(problem)
      return
    }
    navigate(eventEditPath(saved.id), {
      replace: true,
      state: problem === null ? backState : { ...backState, notice: problem },
    })
  }

  async function handleSaveDraft(submission: FormEvent<HTMLFormElement>) {
    submission.preventDefault()
    setIsSaving(true)
    try {
      const result = await saveDraft(true)
      if (!result) return
      showSavedDraft(result.event, result.pictureProblem)
    } catch (err) {
      setSaveError(formatApiError(err))
      // The stock may be why it failed, so ask again how many are free.
      setAvailabilityRefresh((count) => count + 1)
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
      const result = await saveDraft(false)
      if (!result) return
      const saved = result.event
      if (result.pictureProblem !== null) {
        // The picture was wanted, so the request is not sent without it.
        showSavedDraft(saved, result.pictureProblem)
        return
      }
      try {
        const submitted = await submitEvent(saved.id, saved.name)
        if (isEditing) {
          setEvent(submitted)
          setForm(formFromEvent(submitted))
        } else {
          navigate(eventEditPath(saved.id), { replace: true, state: backState })
        }
      } catch (err) {
        if (isEditing) {
          setEvent(saved)
          setForm(formFromEvent(saved))
          setSaveError(formatApiError(err))
          setAvailabilityRefresh((count) => count + 1)
        } else {
          navigate(eventEditPath(saved.id), {
            replace: true,
            state: { ...backState, notice: formatApiError(err) },
          })
        }
      }
    } catch (err) {
      setSaveError(formatApiError(err))
      // The stock may be why it failed, so ask again how many are free.
      setAvailabilityRefresh((count) => count + 1)
    } finally {
      setIsSaving(false)
    }
  }

  // A type can be on a request once, so there is nothing to add when a line exists for each type.
  const hasEveryEquipmentType =
    reference !== null &&
    form !== null &&
    reference.equipment_types.length > 0 &&
    form.equipment.length >= reference.equipment_types.length

  const title = isEditing ? (event?.name ?? 'Event request') : 'New event request'
  const subtitle =
    event && isReadOnly ? (
      <>
        <EventStatusBadge status={event.status} />{' '}
        {event.submitted_at && <span>Submitted on {formatDateTime(event.submitted_at)}</span>}
      </>
    ) : (
      <>
        {event && <EventStatusBadge status={event.status} />}{' '}
        <span>
          Fields marked * and an answer to venue requirements and accessibility are needed to
          submit. Only the event name is needed to save a draft.
        </span>
      </>
    )

  return (
    <div className="page">
      <PageHeader
        backTo={backState?.from ?? HOME_PATH}
        backLabel={backState?.fromLabel ?? 'Main page'}
        title={title}
        subtitle={subtitle}
      />

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
                  {...fieldProps(FIELD_ID.name)}
                  value={form.name}
                  onChange={(e) => updateField('name', e.target.value)}
                  onBlur={() => setIsNameTouched(true)}
                />
                {renderProblem(FIELD_ID.name)}
              </label>
              <label>
                Expected attendance <RequiredMark />
                <input
                  type="number"
                  inputMode="numeric"
                  min={1}
                  step={1}
                  {...fieldProps(FIELD_ID.attendance)}
                  value={form.attendance}
                  onChange={(e) => updateField('attendance', e.target.value)}
                />
                {renderProblem(FIELD_ID.attendance)}
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
                  min={nowAsInput()}
                  max={getLatestStartInput()}
                  {...fieldProps(FIELD_ID.startsAt)}
                  value={form.startsAt}
                  onChange={(e) => updateDate('startsAt', e.target.value)}
                  onBlur={noteIncompleteDate}
                />
              </label>
              <label>
                Proposed end <RequiredMark />
                <input
                  type="datetime-local"
                  min={form.startsAt > nowAsInput() ? form.startsAt : nowAsInput()}
                  max={getLatestEndInput(form.startsAt)}
                  {...fieldProps(FIELD_ID.endsAt)}
                  value={form.endsAt}
                  onChange={(e) => updateDate('endsAt', e.target.value)}
                  onBlur={noteIncompleteDate}
                />
              </label>
            </div>
            {dateProblem && (
              <p className="field-error">{ERROR_REGISTRY[dateProblem.code].message}</p>
            )}
            <p className="form-hint">
              All times are Singapore time. An event can start up to {MAX_LEAD_YEARS} years from now
              and run for up to {MAX_EVENT_DAYS} days.
            </p>
          </fieldset>

          <fieldset className="card" disabled={isReadOnly}>
            <legend>
              Point of contact <RequiredMark />
            </legend>
            <p className="form-hint">Who ConnectSphere should reach about this event.</p>
            <div className="form-grid">
              <label className="span-2">
                Contact name <RequiredMark />
                <input
                  autoComplete="name"
                  maxLength={CONTACT_NAME_MAX_LENGTH}
                  {...fieldProps(FIELD_ID.contactName)}
                  value={form.contactName}
                  onChange={(e) => updateField('contactName', e.target.value)}
                />
              </label>
              <label>
                Contact phone number <RequiredMark />
                <input
                  type="tel"
                  autoComplete="tel"
                  maxLength={CONTACT_PHONE_MAX_LENGTH}
                  {...fieldProps(FIELD_ID.contactPhone)}
                  value={form.contactPhone}
                  onChange={(e) => updateField('contactPhone', e.target.value)}
                />
                {renderProblem(FIELD_ID.contactPhone)}
              </label>
              <label className="span-all">
                Contact email <RequiredMark />
                <input
                  type="email"
                  autoComplete="email"
                  maxLength={CONTACT_EMAIL_MAX_LENGTH}
                  {...fieldProps(FIELD_ID.contactEmail)}
                  value={form.contactEmail}
                  onChange={(e) => updateField('contactEmail', e.target.value)}
                />
                {renderProblem(FIELD_ID.contactEmail)}
              </label>
            </div>
          </fieldset>

          <fieldset className="card" disabled={isReadOnly}>
            <legend>Cover picture</legend>
            <p className="form-hint">
              Optional. JPEG, PNG or WebP, up to 5 MB. It shows on the event's card.
            </p>
            <div
              role="group"
              aria-label="Cover picture drop area"
              className={isDraggingPicture ? 'picture-drop is-dragging' : 'picture-drop'}
              onDragEnter={handlePictureDragOver}
              onDragOver={handlePictureDragOver}
              onDragLeave={handlePictureDragLeave}
              onDrop={handlePictureDrop}
            >
              {shownPictureUrl ? (
                <img
                  className="picture-drop-preview"
                  src={shownPictureUrl}
                  alt="Cover picture preview"
                />
              ) : (
                <span className="picture-drop-icon" aria-hidden="true">
                  <Icon name="image" size={32} />
                </span>
              )}
              <p className="picture-drop-hint">
                {isDraggingPicture ? 'Drop the picture here' : 'Drag a picture here, or'}
              </p>
              <div className="picture-drop-actions">
                <label className="button secondary">
                  {shownPictureUrl ? 'Replace picture' : 'Choose picture'}
                  <input
                    type="file"
                    className="visually-hidden"
                    accept={COVER_IMAGE_TYPES.join(',')}
                    aria-label="Choose cover picture"
                    onChange={handlePictureInput}
                  />
                </label>
                {shownPictureUrl && !isReadOnly && (
                  <button type="button" className="secondary" onClick={removePicture}>
                    Remove picture
                  </button>
                )}
              </div>
            </div>
            {pictureProblem && (
              <span className="field-error">{ERROR_REGISTRY[pictureProblem].message}</span>
            )}
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
                          {...fieldProps(getFacilityQuantityId(item.code))}
                          value={selected.quantity}
                          onChange={(e) => updateFacility(item.code, { quantity: e.target.value })}
                        />
                        <input
                          placeholder="Notes"
                          aria-label={`${item.name} notes`}
                          value={selected.notes}
                          onChange={(e) => updateFacility(item.code, { notes: e.target.value })}
                        />
                        {renderProblem(getFacilityQuantityId(item.code))}
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
                      {...fieldProps(getEquipmentTypeId(line.key))}
                      value={line.typeCode}
                      onChange={(e) => updateEquipment(line.key, { typeCode: e.target.value })}
                    >
                      <option value={NO_EQUIPMENT_CHOSEN}>Choose equipment…</option>
                      {line.typeCode !== NO_EQUIPMENT_CHOSEN &&
                        !reference.equipment_types.some((type) => type.code === line.typeCode) && (
                          <option value={line.typeCode}>{line.typeName}</option>
                        )}
                      {reference.equipment_types.map((type) => {
                        const isTaken = isEquipmentTypeTaken(form.equipment, line.key, type.code)
                        const isNoneLeft = availabilityByType?.[type.code] === 0
                        const note = isTaken
                          ? ' (already added)'
                          : isNoneLeft
                            ? ' (none available)'
                            : ''
                        return (
                          <option
                            key={type.code}
                            value={type.code}
                            disabled={isTaken || isNoneLeft}
                          >
                            {`${type.name}${note}`}
                          </option>
                        )
                      })}
                    </select>
                  </label>
                  <label>
                    Quantity
                    <input
                      type="number"
                      inputMode="numeric"
                      min={1}
                      step={1}
                      {...fieldProps(getEquipmentQuantityId(line.key))}
                      value={line.quantity}
                      onChange={(e) => updateEquipment(line.key, { quantity: e.target.value })}
                    />
                    {renderProblem(getEquipmentQuantityId(line.key))}
                  </label>
                  <label className="span-all">
                    Technical notes
                    <input
                      value={line.notes}
                      onChange={(e) => updateEquipment(line.key, { notes: e.target.value })}
                    />
                  </label>
                </div>
                {equipmentAvailabilityNote(line)}
                <button
                  type="button"
                  className="secondary button-sm"
                  onClick={() => removeEquipment(line.key)}
                >
                  Remove
                </button>
              </fieldset>
            ))}
            <button
              type="button"
              className="secondary"
              disabled={hasEveryEquipmentType}
              onClick={addEquipment}
            >
              Add equipment
            </button>
            {hasEveryEquipmentType && (
              <p className="form-hint">Every equipment type is already on this request.</p>
            )}
          </fieldset>

          {!isReadOnly && (
            <div className="form-actions">
              {missingForSubmission.length > 0 && (
                <p className="form-hint">
                  To submit, still needed: {missingForSubmission.join(', ')}.
                </p>
              )}
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
