import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import { formatApiError, mediaUrl } from '../api/client'
import {
  addVenueImage,
  createVenue,
  fetchVenueReferenceData,
  getVenue,
  removeVenueImage,
  updateVenue,
  type Venue,
  type VenueImage,
  type VenueReferenceData,
  type VenueStatus,
} from '../api/venues'
import { PageHeader } from '../components/PageHeader'
import { ERROR_REGISTRY, type ErrorCode } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import { VENUE_CATALOGUE_PATH, venueEditPath } from '../routes'
import {
  chooseVenueImages,
  EMPTY_ACCESSIBILITY,
  EMPTY_FACILITY,
  EMPTY_LAYOUT,
  EMPTY_VENUE_FORM,
  formFromVenue,
  toggleEntry,
  validateVenueForm,
  venueInputFrom,
  type AccessibilityDraft,
  type FacilityDraft,
  type LayoutDraft,
  type VenueFormState,
} from './venueForm'
import { VenuePicturesField, type PictureTile } from './VenuePicturesField'

/** Story 8.3 AC5: a picture chosen on this form and not uploaded yet. */
interface NewPicture {
  key: string
  file: File
  /** An object URL for the preview, revoked when the picture is removed or the page closes. */
  previewUrl: string
}

/** What saving the pictures left: the venue as last saved, and the first refusal's message. */
interface SavedPictures {
  venue: Venue
  problem: string | null
}

let lastPictureKey = 0

/** A key for a chosen picture. A saved picture's key is its id, a UUID, so the two never meet. */
function newPictureKey(): string {
  lastPictureKey += 1
  return `new-${lastPictureKey}`
}

function revokePreviews(pictures: NewPicture[]) {
  pictures.forEach((picture) => URL.revokeObjectURL(picture.previewUrl))
}

/** Story 8.3 AC8: why a new venue's pictures were not all saved, passed to its edit page. */
function noticeFrom(state: unknown): string | null {
  if (state && typeof state === 'object' && 'notice' in state && typeof state.notice === 'string') {
    return state.notice
  }
  return null
}

/**
 * Story 8.3 AC1/AC2: create (/venues/new) or edit (/venues/:venueId/edit) a venue record.
 * AC5 (bug f8.3.2): the venue's pictures are chosen here too and saved after its details, in the
 * order shown. AC8: if the details save but a picture is refused, the venue stays saved and its
 * edit page says why - a new venue's edit page opens, so trying again cannot create it twice.
 */
export function VenueFormPage() {
  const { venueId } = useParams()
  const isEditing = venueId !== undefined
  const navigate = useNavigate()
  const location = useLocation()
  const [reference, setReference] = useState<VenueReferenceData | null>(null)
  const [form, setForm] = useState<VenueFormState | null>(isEditing ? null : EMPTY_VENUE_FORM)
  const [savedName, setSavedName] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(noticeFrom(location.state))
  const [isSaving, setIsSaving] = useState(false)
  // Story 8.3 AC5: the venue's saved pictures it keeps, those taken off, and those chosen here.
  // Nothing is sent until the form is saved.
  const [keptImages, setKeptImages] = useState<VenueImage[]>([])
  const [removedImageIds, setRemovedImageIds] = useState<string[]>([])
  const [newPictures, setNewPictures] = useState<NewPicture[]>([])
  const [pictureProblem, setPictureProblem] = useState<ErrorCode | null>(null)
  const newPicturesRef = useRef(newPictures)

  useEffect(() => {
    let cancelled = false
    const venueRequest = venueId ? getVenue(venueId) : Promise.resolve(null)
    Promise.all([fetchVenueReferenceData(), venueRequest])
      .then(([referenceData, venue]) => {
        if (cancelled) return
        setReference(referenceData)
        if (venue) {
          setForm(formFromVenue(venue))
          setSavedName(venue.name)
          setKeptImages(venue.images)
        }
      })
      .catch((err) => {
        if (!cancelled) setLoadError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [venueId])

  // Chosen pictures' previews are freed when the page closes, and each as soon as it is removed.
  useEffect(() => {
    newPicturesRef.current = newPictures
  }, [newPictures])
  useEffect(() => () => revokePreviews(newPicturesRef.current), [])

  function updateField<K extends keyof VenueFormState>(key: K, value: VenueFormState[K]) {
    setForm((current) => current && { ...current, [key]: value })
  }

  function toggleFacility(code: string) {
    setForm(
      (current) =>
        current && {
          ...current,
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

  function toggleLayout(code: string) {
    setForm(
      (current) =>
        current && { ...current, layouts: toggleEntry(current.layouts, code, EMPTY_LAYOUT) },
    )
  }

  function updateLayout(code: string, change: Partial<LayoutDraft>) {
    setForm(
      (current) =>
        current && {
          ...current,
          layouts: { ...current.layouts, [code]: { ...current.layouts[code], ...change } },
        },
    )
  }

  function toggleAccessibility(code: string) {
    setForm(
      (current) =>
        current && {
          ...current,
          accessibility: toggleEntry(current.accessibility, code, EMPTY_ACCESSIBILITY),
        },
    )
  }

  function updateAccessibility(code: string, change: Partial<AccessibilityDraft>) {
    setForm(
      (current) =>
        current && {
          ...current,
          accessibility: {
            ...current.accessibility,
            [code]: { ...current.accessibility[code], ...change },
          },
        },
    )
  }

  /** Story 8.3 AC5/AC7: take the chosen or dropped files the venue can still hold. */
  function addPictures(files: File[]) {
    const { accepted, problem } = chooseVenueImages(files, keptImages.length + newPictures.length)
    setPictureProblem(problem)
    if (accepted.length === 0) return
    const chosen = accepted.map((file) => ({
      key: newPictureKey(),
      file,
      previewUrl: URL.createObjectURL(file),
    }))
    setNewPictures((current) => [...current, ...chosen])
  }

  /** Story 8.3 AC5: drop a chosen picture, or mark a saved one to be taken off on save. */
  function removePicture(key: string) {
    setPictureProblem(null)
    const chosen = newPictures.find((picture) => picture.key === key)
    if (chosen) {
      revokePreviews([chosen])
      setNewPictures((current) => current.filter((picture) => picture.key !== key))
      return
    }
    setKeptImages((current) => current.filter((image) => image.id !== key))
    setRemovedImageIds((current) => [...current, key])
  }

  /**
   * Story 8.3 AC5/AC8: apply the picture changes to the saved venue - the removals, then the new
   * pictures in the order shown, so they keep that order. Each is tried even after one is refused,
   * so every picture the venue can take is kept.
   */
  async function savePictures(saved: Venue): Promise<SavedPictures> {
    let venue = saved
    let problem: string | null = null
    for (const imageId of removedImageIds) {
      try {
        venue = await removeVenueImage(saved.id, imageId)
      } catch (err) {
        problem ??= formatApiError(err)
      }
    }
    for (const picture of newPictures) {
      try {
        venue = await addVenueImage(saved.id, picture.file)
      } catch (err) {
        problem ??= formatApiError(err)
      }
    }
    return { venue, problem }
  }

  /** Story 8.3 AC8: show the venue as it was saved, and why not all of its pictures were. */
  function showSavedWithProblem(venue: Venue, problem: string) {
    revokePreviews(newPictures)
    setNewPictures([])
    setRemovedImageIds([])
    setKeptImages(venue.images)
    setForm(formFromVenue(venue))
    setSavedName(venue.name)
    setSaveError(problem)
    setIsSaving(false)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!form) return
    const problem = validateVenueForm(form)
    if (problem) {
      setSaveError(ERROR_REGISTRY[problem].message)
      return
    }
    setSaveError(null)
    setIsSaving(true)
    let saved: Venue
    try {
      const input = venueInputFrom(form, isEditing)
      saved = venueId ? await updateVenue(venueId, input) : await createVenue(input)
    } catch (err) {
      setSaveError(formatApiError(err))
      setIsSaving(false)
      return
    }
    const pictures = await savePictures(saved)
    if (pictures.problem === null) {
      navigate(VENUE_CATALOGUE_PATH)
      return
    }
    if (isEditing) {
      showSavedWithProblem(pictures.venue, pictures.problem)
      return
    }
    navigate(venueEditPath(saved.id), { replace: true, state: { notice: pictures.problem } })
  }

  const pictureTiles: PictureTile[] = [
    ...keptImages.map((image) => ({ key: image.id, src: mediaUrl(image.url) ?? '' })),
    ...newPictures.map((picture) => ({ key: picture.key, src: picture.previewUrl })),
  ]
  const title = isEditing ? `Edit ${savedName ?? 'venue'}` : 'New venue'

  return (
    <div className="page">
      <PageHeader
        backTo={VENUE_CATALOGUE_PATH}
        backLabel="Venue catalogue"
        title={title}
        subtitle="Name, location and capacity are required. Anything left empty shows as not recorded."
      />

      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      {!loadError && (!form || !reference) && <LoadingState label="Loading venue…" />}

      {form && reference && (
        <form className="stack venue-form" onSubmit={handleSubmit} noValidate>
          <fieldset className="card">
            <legend>Basics</legend>
            <div className="form-grid">
              <label className="span-2">
                Venue name{' '}
                <span className="req" aria-hidden="true">
                  *
                </span>
                <input
                  required
                  maxLength={200}
                  value={form.name}
                  onChange={(e) => updateField('name', e.target.value)}
                />
              </label>
              <label>
                Maximum capacity{' '}
                <span className="req" aria-hidden="true">
                  *
                </span>
                <input
                  type="number"
                  inputMode="numeric"
                  min={1}
                  step={1}
                  required
                  value={form.capacity}
                  onChange={(e) => updateField('capacity', e.target.value)}
                />
              </label>
              <label className="span-2">
                Location{' '}
                <span className="req" aria-hidden="true">
                  *
                </span>
                <input
                  required
                  maxLength={500}
                  placeholder="Building, level and room"
                  value={form.location}
                  onChange={(e) => updateField('location', e.target.value)}
                />
              </label>
              <label>
                Floor area (m²)
                <input
                  type="number"
                  min={0}
                  step="0.01"
                  value={form.floorAreaSqm}
                  onChange={(e) => updateField('floorAreaSqm', e.target.value)}
                />
              </label>
              {isEditing && (
                <label>
                  Status
                  <select
                    value={form.status}
                    onChange={(e) => updateField('status', e.target.value as VenueStatus)}
                  >
                    <option value="ACTIVE">In service</option>
                    <option value="WITHDRAWN">Withdrawn from service</option>
                  </select>
                </label>
              )}
              <label className="span-all">
                Description
                <textarea
                  rows={3}
                  value={form.description}
                  onChange={(e) => updateField('description', e.target.value)}
                />
              </label>
            </div>
          </fieldset>

          <VenuePicturesField
            pictures={pictureTiles}
            problem={pictureProblem}
            isDisabled={isSaving}
            onAdd={addPictures}
            onRemove={removePicture}
          />

          <fieldset className="card">
            <legend>Operating information</legend>
            <div className="form-grid form-grid-4">
              <label>
                Opens
                <input
                  type="time"
                  value={form.opensAt}
                  onChange={(e) => updateField('opensAt', e.target.value)}
                />
              </label>
              <label>
                Closes
                <input
                  type="time"
                  value={form.closesAt}
                  onChange={(e) => updateField('closesAt', e.target.value)}
                />
              </label>
              <label>
                Setup (minutes)
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={form.setupMinutes}
                  onChange={(e) => updateField('setupMinutes', e.target.value)}
                />
              </label>
              <label>
                Teardown (minutes)
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={form.teardownMinutes}
                  onChange={(e) => updateField('teardownMinutes', e.target.value)}
                />
              </label>
              <label className="span-all">
                Operating notes
                <textarea
                  rows={2}
                  placeholder="For example, closed on public holidays"
                  value={form.operatingNotes}
                  onChange={(e) => updateField('operatingNotes', e.target.value)}
                />
              </label>
            </div>
          </fieldset>

          <fieldset className="card">
            <legend>Facilities</legend>
            <p className="form-hint">Tick what the venue offers. Quantity is optional.</p>
            <ul className="check-list">
              {reference.facilities.map((item) => {
                const selected = form.facilities[item.code]
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
                          min={1}
                          step={1}
                          className="inline-number"
                          placeholder="Qty"
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
          </fieldset>

          <fieldset className="card">
            <legend>Supported room layouts</legend>
            <p className="form-hint">
              Give a layout its own capacity only when it seats fewer than the maximum.
            </p>
            <ul className="check-list">
              {reference.layouts.map((item) => {
                const selected = form.layouts[item.code]
                return (
                  <li key={item.code}>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={selected !== undefined}
                        onChange={() => toggleLayout(item.code)}
                      />
                      {item.name}
                    </label>
                    {selected && (
                      <div className="inline-fields">
                        <input
                          type="number"
                          min={1}
                          step={1}
                          className="inline-number"
                          placeholder="Seats"
                          aria-label={`${item.name} layout seats`}
                          value={selected.layoutCapacity}
                          onChange={(e) =>
                            updateLayout(item.code, { layoutCapacity: e.target.value })
                          }
                        />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </fieldset>

          <fieldset className="card">
            <legend>Accessibility</legend>
            <ul className="check-list">
              {reference.accessibility_features.map((item) => {
                const selected = form.accessibility[item.code]
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
                          placeholder="Notes, for example lift to level 3 only"
                          aria-label={`${item.name} notes`}
                          value={selected.notes}
                          onChange={(e) =>
                            updateAccessibility(item.code, { notes: e.target.value })
                          }
                        />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </fieldset>

          <div className="form-actions">
            {saveError && (
              <p role="alert" className="error">
                {saveError}
              </p>
            )}
            <Link to={VENUE_CATALOGUE_PATH} className="button secondary">
              Cancel
            </Link>
            <button type="submit" disabled={isSaving}>
              {isSaving && <span className="spinner button-spinner" aria-hidden="true" />}
              {isEditing ? 'Save changes' : 'Create venue'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
