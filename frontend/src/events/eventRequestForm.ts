import type { EventDetail, EventInput } from '../api/events'
import type { ErrorCode } from '../errors/registry'
import { inputToInstant, instantToInput, nowAsInput } from '../shared/format'

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
const DATE_TIME_INPUT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/
const DATE_TIME_INPUT_LENGTH = 'YYYY-MM-DDTHH:mm'.length
// The largest value the backend's INTEGER columns hold.
const MAX_WHOLE_NUMBER = 2_147_483_647
const NO_EQUIPMENT_TYPE = ''
const MS_PER_DAY = 24 * 60 * 60 * 1000
/** How far ahead an event may start and how long it may run (story 2.1 AC2), mirrored from the
 * backend's service. */
export const MAX_LEAD_YEARS = 2
export const MAX_EVENT_DAYS = 14
/** The latest date a four-digit year allows; the backend cannot read a longer year. */
export const LATEST_DATE_INPUT = '9999-12-31T23:59'

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

/** The field a problem belongs to, so the page can mark it and move focus there. */
export interface FormProblem {
  code: ErrorCode
  fieldId: string
}

export const FIELD_ID = {
  name: 'event-name',
  attendance: 'event-attendance',
  startsAt: 'event-starts-at',
  endsAt: 'event-ends-at',
} as const

export function getFacilityQuantityId(code: string): string {
  return `facility-${code}-quantity`
}

export function getEquipmentTypeId(key: number): string {
  return `equipment-${key}-type`
}

export function getEquipmentQuantityId(key: number): string {
  return `equipment-${key}-quantity`
}

/**
 * Story 2.1 AC6: more of an item than is free for the dates. Unknown until both dates are chosen
 * and the backend has answered, and then nothing is judged here (the backend judges on save).
 */
export function isOverAvailable(
  line: EquipmentDraft,
  availability: Record<string, number> | null,
): boolean {
  return (
    availability !== null &&
    line.typeCode in availability &&
    isPositiveWholeNumber(line.quantity) &&
    Number(line.quantity) > availability[line.typeCode]
  )
}

/** Story 2.1 AC6: a type can be on a request once, so another line's type is not on offer. */
export function isEquipmentTypeTaken(
  equipment: EquipmentDraft[],
  key: number,
  typeCode: string,
): boolean {
  return equipment.some((line) => line.key !== key && line.typeCode === typeCode)
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
 * The latest start the start picker should offer: two calendar years from now on Singapore's
 * clock, so leap days and month lengths are counted (never a fixed 730 days), as on the backend.
 */
export function getLatestStartInput(): string {
  const [date, time] = nowAsInput().split('T')
  const [year, month, day] = date.split('-').map(Number)
  const [hour, minute] = time.split(':').map(Number)
  // Date.UTC is only a calendar here; it also rolls 29 February of a non-leap year to 1 March.
  const later = new Date(Date.UTC(year + MAX_LEAD_YEARS, month - 1, day, hour, minute))
  return later.toISOString().slice(0, DATE_TIME_INPUT_LENGTH)
}

/** The latest end the end picker should offer: 14 days after the start, or after the latest start
 * when none is chosen yet. */
export function getLatestEndInput(startsAt: string): string {
  const anchor = isReadableDateTime(startsAt) ? startsAt : getLatestStartInput()
  const latest = instantToInput(
    new Date(Date.parse(inputToInstant(anchor)) + MAX_EVENT_DAYS * MS_PER_DAY).toISOString(),
  )
  return latest < LATEST_DATE_INPUT ? latest : LATEST_DATE_INPUT
}

/** A picker can hold a six-digit year, which the backend cannot read as a date. */
function isReadableDateTime(inputValue: string): boolean {
  return DATE_TIME_INPUT.test(inputValue) && !Number.isNaN(Date.parse(inputToInstant(inputValue)))
}

/**
 * Story 2.1 AC2/AC3/AC6: the first problem with the form (an error-registry code and the field to
 * fix), or null. The backend checks the same rules again; this only saves a round trip. A date
 * already saved on the draft is not judged again unless it was changed, as on the backend. What a
 * request needs before it can be submitted (AC10) is left to the backend, which names anything
 * missing.
 */
export function validateEventForm(
  form: EventFormState,
  saved: EventDetail | null,
  availability: Record<string, number> | null,
): FormProblem | null {
  if (!form.name.trim()) return { code: 'EVENT_NAME_REQUIRED', fieldId: FIELD_ID.name }
  if (!isBlankOrPositiveWholeNumber(form.attendance)) {
    return { code: 'EVENT_ATTENDANCE_INVALID', fieldId: FIELD_ID.attendance }
  }
  const dateProblem = validateDates(form, saved)
  if (dateProblem) return dateProblem
  return validateRequirements(form, availability)
}

/**
 * The first problem with the proposed start and end, or null. The page shows this under the dates
 * as soon as it is typed, and the save check uses it too.
 */
export function validateDates(form: EventFormState, saved: EventDetail | null): FormProblem | null {
  if (form.startsAt && !isReadableDateTime(form.startsAt)) {
    return { code: 'EVENT_DATE_INVALID', fieldId: FIELD_ID.startsAt }
  }
  if (form.endsAt && !isReadableDateTime(form.endsAt)) {
    return { code: 'EVENT_DATE_INVALID', fieldId: FIELD_ID.endsAt }
  }
  if (form.startsAt && form.endsAt && form.endsAt <= form.startsAt) {
    return { code: 'EVENT_END_BEFORE_START', fieldId: FIELD_ID.endsAt }
  }
  const savedStart = saved?.starts_at ? instantToInput(saved.starts_at) : ''
  const savedEnd = saved?.ends_at ? instantToInput(saved.ends_at) : ''
  if (form.startsAt !== '' && form.startsAt !== savedStart && isInThePast(form.startsAt)) {
    return { code: 'EVENT_DATE_IN_PAST', fieldId: FIELD_ID.startsAt }
  }
  if (form.endsAt !== '' && form.endsAt !== savedEnd && isInThePast(form.endsAt)) {
    return { code: 'EVENT_DATE_IN_PAST', fieldId: FIELD_ID.endsAt }
  }
  if (form.startsAt && form.startsAt > getLatestStartInput()) {
    return { code: 'EVENT_TOO_FAR_AHEAD', fieldId: FIELD_ID.startsAt }
  }
  // Last: a start in the year 1 is "in the past", and fixing it fixes the length too.
  if (form.startsAt && form.endsAt && form.endsAt > getLatestEndInput(form.startsAt)) {
    return { code: 'EVENT_TOO_LONG', fieldId: FIELD_ID.endsAt }
  }
  return null
}

/**
 * Problems with the numbers on the form, keyed by the field they belong to, so the page can say
 * each next to its field as it is typed instead of waiting for a save.
 */
export function getLiveProblems(
  form: EventFormState,
  availability: Record<string, number> | null,
): Record<string, ErrorCode> {
  const problems: Record<string, ErrorCode> = {}
  if (!isBlankOrPositiveWholeNumber(form.attendance)) {
    problems[FIELD_ID.attendance] = 'EVENT_ATTENDANCE_INVALID'
  }
  for (const [code, facility] of Object.entries(form.facilities)) {
    if (!isBlankOrPositiveWholeNumber(facility.quantity)) {
      problems[getFacilityQuantityId(code)] = 'EVENT_FACILITY_QUANTITY_INVALID'
    }
  }
  for (const line of form.equipment) {
    if (!isPositiveWholeNumber(line.quantity)) {
      problems[getEquipmentQuantityId(line.key)] = 'EVENT_QUANTITY_INVALID'
    } else if (isOverAvailable(line, availability)) {
      problems[getEquipmentQuantityId(line.key)] = 'EVENT_EQUIPMENT_UNAVAILABLE'
    }
  }
  return problems
}

/**
 * Story 2.1 AC10: what a request still needs before it can be submitted, worded as the backend
 * words it. Shown as the form is filled in, so a refused submission is never a surprise; the
 * backend still checks, and names anything missing.
 */
export function getMissingForSubmission(form: EventFormState): string[] {
  const missing: string[] = []
  if (!form.purpose.trim()) missing.push('purpose')
  if (!form.description.trim()) missing.push('description')
  if (!form.startsAt) missing.push('proposed start date and time')
  if (!form.endsAt) missing.push('proposed end date and time')
  if (!isPositiveWholeNumber(form.attendance)) missing.push('expected attendance')
  const hasVenueAnswer =
    form.hasNoVenueRequirements ||
    form.layoutCode !== '' ||
    Object.keys(form.facilities).length > 0 ||
    form.venueNotes.trim() !== ''
  if (!hasVenueAnswer) missing.push('venue requirements (choose some, or mark none)')
  const hasAccessibilityAnswer =
    form.hasNoAccessibilityNeeds ||
    Object.keys(form.accessibility).length > 0 ||
    form.accessibilityNotes.trim() !== ''
  if (!hasAccessibilityAnswer) missing.push('accessibility needs (choose some, or mark none)')
  return missing
}

/** The first problem with the facilities and equipment, or null. */
function validateRequirements(
  form: EventFormState,
  availability: Record<string, number> | null,
): FormProblem | null {
  const badFacility = Object.entries(form.facilities).find(
    ([, facility]) => !isBlankOrPositiveWholeNumber(facility.quantity),
  )
  if (badFacility) {
    return {
      code: 'EVENT_FACILITY_QUANTITY_INVALID',
      fieldId: getFacilityQuantityId(badFacility[0]),
    }
  }
  const untypedLine = form.equipment.find((line) => line.typeCode === NO_EQUIPMENT_TYPE)
  if (untypedLine) {
    return { code: 'EVENT_EQUIPMENT_TYPE_REQUIRED', fieldId: getEquipmentTypeId(untypedLine.key) }
  }
  const repeatedLine = form.equipment.find((line) =>
    isEquipmentTypeTaken(form.equipment, line.key, line.typeCode),
  )
  if (repeatedLine) {
    return { code: 'EVENT_EQUIPMENT_DUPLICATE', fieldId: getEquipmentTypeId(repeatedLine.key) }
  }
  const badQuantityLine = form.equipment.find((line) => !isPositiveWholeNumber(line.quantity))
  if (badQuantityLine) {
    return {
      code: 'EVENT_QUANTITY_INVALID',
      fieldId: getEquipmentQuantityId(badQuantityLine.key),
    }
  }
  const overLine = form.equipment.find((line) => isOverAvailable(line, availability))
  if (overLine) {
    return { code: 'EVENT_EQUIPMENT_UNAVAILABLE', fieldId: getEquipmentQuantityId(overLine.key) }
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
