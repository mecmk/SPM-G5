import type { EventDetail, EventInput } from '../api/events'
import type { ErrorCode } from '../errors/registry'
import { inputToInstant, instantToInput } from '../shared/format'

/**
 * Story 2.1: the event request form's state and rules, kept apart from the page. Numbers and
 * dates stay strings until submit, so a half-typed value never breaks the form.
 */
export interface NoteDraft {
  notes: string
}

export interface FacilityDraft {
  /** Optional: how many are needed, for example 3 breakout rooms. */
  quantity: string
  notes: string
}

export interface EquipmentDraft {
  /** React key; a new line has no `id` until the server has saved it. */
  key: number
  id: string | null
  typeCode: string
  /** Shown when the line's type is no longer in the pick-list. */
  typeName: string
  quantity: string
  notes: string
}

export interface EventFormState {
  name: string
  purpose: string
  description: string
  startsAt: string
  endsAt: string
  attendance: string
  /** Story 2.1 AC4: true is "no venue requirements"; false with nothing chosen is "not specified". */
  hasNoVenueRequirements: boolean
  layoutCode: string
  facilities: Record<string, FacilityDraft>
  venueNotes: string
  /** Story 2.1 AC5: true is "none required"; false with nothing selected is "not specified". */
  hasNoAccessibilityNeeds: boolean
  accessibility: Record<string, NoteDraft>
  accessibilityNotes: string
  equipment: EquipmentDraft[]
}

export const EMPTY_NOTE: NoteDraft = { notes: '' }
export const EMPTY_FACILITY: FacilityDraft = { quantity: '', notes: '' }
const WHOLE_NUMBER = /^\d+$/
// The largest value the backend's INTEGER columns hold.
const MAX_WHOLE_NUMBER = 2_147_483_647
const NO_EQUIPMENT_TYPE = ''

export const EMPTY_EVENT_FORM: EventFormState = {
  name: '',
  purpose: '',
  description: '',
  startsAt: '',
  endsAt: '',
  attendance: '',
  hasNoVenueRequirements: false,
  layoutCode: '',
  facilities: {},
  venueNotes: '',
  hasNoAccessibilityNeeds: false,
  accessibility: {},
  accessibilityNotes: '',
  equipment: [],
}

let nextEquipmentKey = 0

export function newEquipmentDraft(): EquipmentDraft {
  nextEquipmentKey += 1
  return {
    key: nextEquipmentKey,
    id: null,
    typeCode: NO_EQUIPMENT_TYPE,
    typeName: '',
    quantity: '1',
    notes: '',
  }
}

function textOf(value: string | null): string {
  return value ?? ''
}

export function formFromEvent(event: EventDetail): EventFormState {
  return {
    name: event.name,
    purpose: textOf(event.purpose),
    description: textOf(event.description),
    startsAt: event.starts_at ? instantToInput(event.starts_at) : '',
    endsAt: event.ends_at ? instantToInput(event.ends_at) : '',
    attendance: event.expected_attendance === null ? '' : String(event.expected_attendance),
    hasNoVenueRequirements: event.venue_none_required,
    layoutCode: textOf(event.required_layout_code),
    facilities: Object.fromEntries(
      event.required_facilities.map((facility) => [
        facility.code,
        {
          quantity: facility.quantity === null ? '' : String(facility.quantity),
          notes: textOf(facility.notes),
        },
      ]),
    ),
    venueNotes: textOf(event.venue_requirement_notes),
    hasNoAccessibilityNeeds: event.accessibility_none_required,
    accessibility: Object.fromEntries(
      event.accessibility_needs.map((need) => [need.code, { notes: textOf(need.notes) }]),
    ),
    accessibilityNotes: textOf(event.accessibility_notes),
    equipment: event.equipment.map((line) => {
      nextEquipmentKey += 1
      return {
        key: nextEquipmentKey,
        id: line.id,
        typeCode: line.equipment_type_code,
        typeName: line.equipment_type_name,
        quantity: String(line.quantity),
        notes: textOf(line.technical_notes),
      }
    }),
  }
}

function isPositiveWholeNumber(value: string): boolean {
  const trimmed = value.trim()
  return WHOLE_NUMBER.test(trimmed) && Number(trimmed) > 0 && Number(trimmed) <= MAX_WHOLE_NUMBER
}

function isBlankOrPositiveWholeNumber(value: string): boolean {
  return value.trim() === '' || isPositiveWholeNumber(value)
}

function isInThePast(inputValue: string): boolean {
  return new Date(inputToInstant(inputValue)).getTime() < Date.now()
}

/**
 * Story 2.1 AC2/AC3: the first problem with the form as an error-registry code, or null. The
 * backend checks the same rules again; this only saves a round trip. A date already saved on
 * the draft is not judged again unless it was changed, as on the backend. What a request needs
 * before it can be submitted (AC10) is left to the backend, which names anything missing.
 */
export function validateEventForm(
  form: EventFormState,
  saved: EventDetail | null,
): ErrorCode | null {
  if (!form.name.trim()) return 'EVENT_NAME_REQUIRED'
  if (!isBlankOrPositiveWholeNumber(form.attendance)) return 'EVENT_ATTENDANCE_INVALID'
  if (form.startsAt && form.endsAt && form.endsAt <= form.startsAt) return 'EVENT_END_BEFORE_START'
  const savedStart = saved?.starts_at ? instantToInput(saved.starts_at) : ''
  const savedEnd = saved?.ends_at ? instantToInput(saved.ends_at) : ''
  const isStartChangedToPast =
    form.startsAt !== '' && form.startsAt !== savedStart && isInThePast(form.startsAt)
  const isEndChangedToPast =
    form.endsAt !== '' && form.endsAt !== savedEnd && isInThePast(form.endsAt)
  if (isStartChangedToPast || isEndChangedToPast) return 'EVENT_DATE_IN_PAST'

  const facilityQuantities = Object.values(form.facilities).map((facility) => facility.quantity)
  if (!facilityQuantities.every(isBlankOrPositiveWholeNumber)) {
    return 'EVENT_FACILITY_QUANTITY_INVALID'
  }
  const typeCodes = form.equipment.map((line) => line.typeCode)
  if (typeCodes.some((code) => code === NO_EQUIPMENT_TYPE)) return 'EVENT_EQUIPMENT_TYPE_REQUIRED'
  if (new Set(typeCodes).size !== typeCodes.length) return 'EVENT_EQUIPMENT_DUPLICATE'
  if (!form.equipment.every((line) => isPositiveWholeNumber(line.quantity))) {
    return 'EVENT_QUANTITY_INVALID'
  }
  return null
}

function textOrNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

/** The request body for a valid form: every field, so an edit replaces what was saved. */
export function eventInputFrom(form: EventFormState): EventInput {
  const hasNoVenueNeeds = form.hasNoVenueRequirements
  const hasNoAccessibilityNeeds = form.hasNoAccessibilityNeeds
  return {
    name: form.name.trim(),
    purpose: textOrNull(form.purpose),
    description: textOrNull(form.description),
    starts_at: form.startsAt ? inputToInstant(form.startsAt) : null,
    ends_at: form.endsAt ? inputToInstant(form.endsAt) : null,
    expected_attendance: form.attendance.trim() === '' ? null : Number(form.attendance),
    required_layout_code: hasNoVenueNeeds ? null : textOrNull(form.layoutCode),
    venue_requirement_notes: hasNoVenueNeeds ? null : textOrNull(form.venueNotes),
    required_facilities: hasNoVenueNeeds
      ? []
      : Object.entries(form.facilities).map(([code, facility]) => ({
          code,
          quantity: facility.quantity.trim() === '' ? null : Number(facility.quantity),
          notes: textOrNull(facility.notes),
        })),
    venue_none_required: hasNoVenueNeeds,
    accessibility_none_required: hasNoAccessibilityNeeds,
    accessibility_needs: hasNoAccessibilityNeeds
      ? []
      : Object.entries(form.accessibility).map(([code, need]) => ({
          code,
          notes: textOrNull(need.notes),
        })),
    accessibility_notes: hasNoAccessibilityNeeds ? null : textOrNull(form.accessibilityNotes),
    equipment: form.equipment.map((line) => ({
      id: line.id,
      equipment_type_code: line.typeCode,
      quantity: Number(line.quantity),
      technical_notes: textOrNull(line.notes),
    })),
  }
}

/** Select an option when it is not selected, deselect it when it is. */
export function toggleEntry<T>(
  entries: Record<string, T>,
  code: string,
  empty: T,
): Record<string, T> {
  const next = { ...entries }
  if (code in next) delete next[code]
  else next[code] = empty
  return next
}
