import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { formatApiError } from '../api/client'
import {
  createVenue,
  fetchVenueReferenceData,
  getVenue,
  updateVenue,
  type VenueReferenceData,
  type VenueStatus,
} from '../api/venues'
import { PageHeader } from '../components/PageHeader'
import { ERROR_REGISTRY } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import { VENUES_MANAGE_PATH } from '../routes'
import {
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

/** Story 8.3 AC1/AC2: create (/venues/new) or edit (/venues/:venueId/edit) a venue record. */
export function VenueFormPage() {
  const { venueId } = useParams()
  const isEditing = venueId !== undefined
  const navigate = useNavigate()
  const [reference, setReference] = useState<VenueReferenceData | null>(null)
  const [form, setForm] = useState<VenueFormState | null>(isEditing ? null : EMPTY_VENUE_FORM)
  const [savedName, setSavedName] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

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
        }
      })
      .catch((err) => {
        if (!cancelled) setLoadError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [venueId])

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
    try {
      const input = venueInputFrom(form, isEditing)
      if (venueId) await updateVenue(venueId, input)
      else await createVenue(input)
      navigate(VENUES_MANAGE_PATH)
    } catch (err) {
      setSaveError(formatApiError(err))
      setIsSaving(false)
    }
  }

  const title = isEditing ? `Edit ${savedName ?? 'venue'}` : 'New venue'

  return (
    <div className="page">
      <PageHeader
        backTo={VENUES_MANAGE_PATH}
        backLabel="All venues"
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
            <Link to={VENUES_MANAGE_PATH} className="button secondary">
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
