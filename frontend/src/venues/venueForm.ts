import type { Venue, VenueInput, VenueStatus } from '../api/venues'
import type { ErrorCode } from '../errors/registry'

/**
 * Story 8.3: the venue form's state and rules, kept apart from the page. Numbers stay strings
 * until submit, so a half-typed value never breaks the form.
 */
export interface FacilityDraft {
  quantity: string
  notes: string
}

export interface LayoutDraft {
  layoutCapacity: string
}

export interface AccessibilityDraft {
  notes: string
}

export interface VenueFormState {
  name: string
  location: string
  capacity: string
  description: string
  floorAreaSqm: string
  opensAt: string
  closesAt: string
  operatingNotes: string
  setupMinutes: string
  teardownMinutes: string
  status: VenueStatus
  facilities: Record<string, FacilityDraft>
  layouts: Record<string, LayoutDraft>
  accessibility: Record<string, AccessibilityDraft>
}

export const EMPTY_FACILITY: FacilityDraft = { quantity: '', notes: '' }
export const EMPTY_LAYOUT: LayoutDraft = { layoutCapacity: '' }
export const EMPTY_ACCESSIBILITY: AccessibilityDraft = { notes: '' }

export const EMPTY_VENUE_FORM: VenueFormState = {
  name: '',
  location: '',
  capacity: '',
  description: '',
  floorAreaSqm: '',
  opensAt: '',
  closesAt: '',
  operatingNotes: '',
  setupMinutes: '0',
  teardownMinutes: '0',
  status: 'ACTIVE',
  facilities: {},
  layouts: {},
  accessibility: {},
}

/** "HH:MM:SS" from the API becomes "HH:MM" for a time input. */
const TIME_INPUT_LENGTH = 5
const WHOLE_NUMBER = /^\d+$/
const AREA_WITH_TWO_DECIMALS = /^\d+(\.\d{1,2})?$/

function textOf(value: string | null): string {
  return value ?? ''
}

function numberText(value: number | null): string {
  return value === null ? '' : String(value)
}

export function formFromVenue(venue: Venue): VenueFormState {
  return {
    name: venue.name,
    location: venue.location,
    capacity: String(venue.capacity),
    description: textOf(venue.description),
    floorAreaSqm: textOf(venue.floor_area_sqm),
    opensAt: textOf(venue.operating_hours_start).slice(0, TIME_INPUT_LENGTH),
    closesAt: textOf(venue.operating_hours_end).slice(0, TIME_INPUT_LENGTH),
    operatingNotes: textOf(venue.operating_notes),
    setupMinutes: String(venue.setup_minutes_default),
    teardownMinutes: String(venue.teardown_minutes_default),
    status: venue.status,
    facilities: Object.fromEntries(
      venue.facilities.map((facility) => [
        facility.code,
        { quantity: numberText(facility.quantity), notes: textOf(facility.notes) },
      ]),
    ),
    layouts: Object.fromEntries(
      venue.layouts.map((layout) => [
        layout.code,
        { layoutCapacity: numberText(layout.layout_capacity) },
      ]),
    ),
    accessibility: Object.fromEntries(
      venue.accessibility_features.map((feature) => [
        feature.code,
        { notes: textOf(feature.notes) },
      ]),
    ),
  }
}

function isPositiveWholeNumber(value: string): boolean {
  return WHOLE_NUMBER.test(value.trim()) && Number(value) > 0
}

function isBlankOrPositiveWholeNumber(value: string): boolean {
  return value.trim() === '' || isPositiveWholeNumber(value)
}

function isValidFloorArea(value: string): boolean {
  const area = value.trim()
  return area === '' || (AREA_WITH_TWO_DECIMALS.test(area) && Number(area) > 0)
}

/**
 * Story 8.3 AC1/AC3: the first problem with the form as an error-registry code, or null. The
 * backend checks the same rules again; this only saves a round trip.
 */
export function validateVenueForm(form: VenueFormState): ErrorCode | null {
  if (!form.name.trim()) return 'VENUE_NAME_REQUIRED'
  if (!form.location.trim()) return 'VENUE_LOCATION_REQUIRED'
  if (!isPositiveWholeNumber(form.capacity)) return 'VENUE_CAPACITY_INVALID'
  if (!isValidFloorArea(form.floorAreaSqm)) return 'VENUE_FLOOR_AREA_INVALID'
  if (!form.opensAt !== !form.closesAt) return 'VENUE_HOURS_INCOMPLETE'
  if (form.opensAt && form.closesAt <= form.opensAt) return 'VENUE_HOURS_OUT_OF_ORDER'
  const turnaround = [form.setupMinutes, form.teardownMinutes]
  if (!turnaround.every((minutes) => WHOLE_NUMBER.test(minutes.trim()))) {
    return 'VENUE_TURNAROUND_INVALID'
  }
  const quantities = Object.values(form.facilities).map((facility) => facility.quantity)
  if (!quantities.every(isBlankOrPositiveWholeNumber)) return 'VENUE_QUANTITY_INVALID'
  const layoutCapacities = Object.values(form.layouts).map((layout) => layout.layoutCapacity)
  if (!layoutCapacities.every(isBlankOrPositiveWholeNumber)) return 'VENUE_LAYOUT_CAPACITY_INVALID'
  return null
}

function textOrNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

function numberOrNull(value: string): number | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : Number(trimmed)
}

/** The request body for a valid form. Status is only sent when editing. */
export function venueInputFrom(form: VenueFormState, isEditing: boolean): VenueInput {
  const input: VenueInput = {
    name: form.name.trim(),
    location: form.location.trim(),
    capacity: Number(form.capacity),
    description: textOrNull(form.description),
    floor_area_sqm: textOrNull(form.floorAreaSqm),
    operating_hours_start: textOrNull(form.opensAt),
    operating_hours_end: textOrNull(form.closesAt),
    operating_notes: textOrNull(form.operatingNotes),
    setup_minutes_default: Number(form.setupMinutes),
    teardown_minutes_default: Number(form.teardownMinutes),
    facilities: Object.entries(form.facilities).map(([code, facility]) => ({
      code,
      quantity: numberOrNull(facility.quantity),
      notes: textOrNull(facility.notes),
    })),
    layouts: Object.entries(form.layouts).map(([code, layout]) => ({
      code,
      layout_capacity: numberOrNull(layout.layoutCapacity),
    })),
    accessibility_features: Object.entries(form.accessibility).map(([code, feature]) => ({
      code,
      notes: textOrNull(feature.notes),
    })),
  }
  return isEditing ? { ...input, status: form.status } : input
}

/** Add a characteristic when it is not selected, remove it when it is. */
export function toggleEntry<T>(entries: Record<string, T>, code: string, empty: T) {
  const next = { ...entries }
  if (code in next) delete next[code]
  else next[code] = empty
  return next
}
