import type { EventDetail, EventInput, VenueRequirement } from '../api/events'
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

/**
 * Story 2.7 AC1/AC2: one venue the event needs, as the form holds it. Every field may stay empty on
 * a draft (AC8). `id` is null until the server has saved it; then it is sent back so the
 * requirement is edited in place rather than replaced.
 */
export interface VenueRequirementDraft {
  /** React key, and the stem of each field's id. */
  key: number
  id: string | null
  name: string
  capacity: string
  startsAt: string
  endsAt: string
  layoutCode: string
  facilities: Record<string, FacilityDraft>
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
  /** Story 2.1 AC13: the point of contact, all three needed to submit. */
  contactName: string
  contactEmail: string
  contactPhone: string
  /** Story 2.1 AC4: true is "no venue requirements"; false with none listed is "not specified". */
  hasNoVenueRequirements: boolean
  /** Story 2.7: each venue the event needs, in order. */
  venueRequirements: VenueRequirementDraft[]
  /** Story 2.1 AC5: true is "none required"; false with nothing selected is "not specified". */
  hasNoAccessibilityNeeds: boolean
  accessibility: Record<string, NoteDraft>
  accessibilityNotes: string
  equipment: EquipmentDraft[]
  /** Story 2.1 AC17: Yes/No. Dates below are only meaningful, and only sent, when this is true. */
  isRegistrationRequired: boolean
  registrationOpensAt: string
  registrationClosesAt: string
  /** Story 2.1 AC19: defaults to Private. */
  isPublic: boolean
}

export const EMPTY_NOTE: NoteDraft = { notes: '' }
export const EMPTY_FACILITY: FacilityDraft = { quantity: '', notes: '' }
const WHOLE_NUMBER = /^\d+$/
// Story 2.1 AC13: mirrored from the backend's schemas.
const EMAIL_ADDRESS = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const PHONE_NUMBER = /^\+?[\d -]+$/
export const CONTACT_NAME_MAX_LENGTH = 200
export const CONTACT_EMAIL_MAX_LENGTH = 254
export const CONTACT_PHONE_MAX_LENGTH = 50
const CONTACT_PHONE_MIN_DIGITS = 8
const CONTACT_PHONE_MAX_DIGITS = 15
/** Story 2.1 AC14: what a cover picture may be, mirrored from the backend's service. */
export const MAX_COVER_IMAGE_BYTES = 5 * 1024 * 1024
export const COVER_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const DATE_TIME_INPUT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/
const DATE_TIME_INPUT_LENGTH = 'YYYY-MM-DDTHH:mm'.length
// The largest value the backend's INTEGER columns hold.
const MAX_WHOLE_NUMBER = 2_147_483_647
const NO_EQUIPMENT_TYPE = ''
/** Story 2.7, mirrored from the backend's schemas: a requirement's name is short, and a request
 * lists a bounded number of requirements. */
export const VENUE_REQUIREMENT_NAME_MAX_LENGTH = 100
export const MAX_VENUE_REQUIREMENTS = 20
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
  contactName: '',
  contactEmail: '',
  contactPhone: '',
  hasNoVenueRequirements: false,
  venueRequirements: [],
  hasNoAccessibilityNeeds: false,
  accessibility: {},
  accessibilityNotes: '',
  equipment: [],
  isRegistrationRequired: false,
  registrationOpensAt: '',
  registrationClosesAt: '',
  isPublic: false,
}

/** The field a problem belongs to, so the page can mark it and move focus there. */
export interface FormProblem {
  code: ErrorCode
  fieldId: string
}

export const FIELD_ID = {
  name: 'event-name',
  attendance: 'event-attendance',
  contactName: 'event-contact-name',
  contactEmail: 'event-contact-email',
  contactPhone: 'event-contact-phone',
  startsAt: 'event-starts-at',
  endsAt: 'event-ends-at',
  registrationOpensAt: 'event-registration-opens-at',
  registrationClosesAt: 'event-registration-closes-at',
} as const

/** Story 2.1 AC17/AC18: the two registration date fields, so a shared helper can tell them apart
 * from the proposed start/end when a date is left half-typed. */
export const REGISTRATION_DATE_FIELD_IDS: readonly string[] = [
  FIELD_ID.registrationOpensAt,
  FIELD_ID.registrationClosesAt,
]

/** Story 2.7: the fields of one venue requirement, so a problem can mark and focus the right one. */
export type VenueRequirementField = 'name' | 'capacity' | 'starts' | 'ends'

export function getVenueRequirementFieldId(key: number, field: VenueRequirementField): string {
  return `venue-requirement-${key}-${field}`
}

export function getFacilityQuantityId(key: number, code: string): string {
  return `venue-requirement-${key}-facility-${code}-quantity`
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
let nextVenueRequirementKey = 0

/**
 * Story 2.7: a new venue requirement. AC2: its times start as the event's proposed start and end.
 * AC6: the first one's number of people starts as the expected attendance; a later room is rarely
 * the whole audience, so its number is left for the organiser.
 */
export function newVenueRequirementDraft(form: EventFormState): VenueRequirementDraft {
  nextVenueRequirementKey += 1
  return {
    key: nextVenueRequirementKey,
    id: null,
    name: '',
    capacity: form.venueRequirements.length === 0 ? form.attendance.trim() : '',
    startsAt: form.startsAt,
    endsAt: form.endsAt,
    layoutCode: '',
    facilities: {},
    notes: '',
  }
}

function venueRequirementDraftFrom(requirement: VenueRequirement): VenueRequirementDraft {
  nextVenueRequirementKey += 1
  return {
    key: nextVenueRequirementKey,
    id: requirement.id,
    name: textOf(requirement.name),
    capacity: requirement.capacity === null ? '' : String(requirement.capacity),
    startsAt: requirement.starts_at ? instantToInput(requirement.starts_at) : '',
    endsAt: requirement.ends_at ? instantToInput(requirement.ends_at) : '',
    layoutCode: textOf(requirement.layout_code),
    facilities: Object.fromEntries(
      requirement.facilities.map((facility) => [
        facility.code,
        {
          quantity: facility.quantity === null ? '' : String(facility.quantity),
          notes: textOf(facility.notes),
        },
      ]),
    ),
    notes: textOf(requirement.notes),
  }
}

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
    contactName: textOf(event.contact_name),
    contactEmail: textOf(event.contact_email),
    contactPhone: textOf(event.contact_phone),
    hasNoVenueRequirements: event.venue_none_required,
    venueRequirements: event.venue_requirements.map(venueRequirementDraftFrom),
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
    isRegistrationRequired: event.registration_required,
    registrationOpensAt: event.registration_opens_at
      ? instantToInput(event.registration_opens_at)
      : '',
    registrationClosesAt: event.registration_closes_at
      ? instantToInput(event.registration_closes_at)
      : '',
    isPublic: event.is_public,
  }
}

function isPositiveWholeNumber(value: string): boolean {
  const trimmed = value.trim()
  return WHOLE_NUMBER.test(trimmed) && Number(trimmed) > 0 && Number(trimmed) <= MAX_WHOLE_NUMBER
}

function isBlankOrPositiveWholeNumber(value: string): boolean {
  return value.trim() === '' || isPositiveWholeNumber(value)
}

/** Story 2.1 AC13: blank is fine on a draft; anything typed must look like an email address. */
function isBlankOrEmailAddress(value: string): boolean {
  const trimmed = value.trim()
  return (
    trimmed === '' || (trimmed.length <= CONTACT_EMAIL_MAX_LENGTH && EMAIL_ADDRESS.test(trimmed))
  )
}

/** Story 2.1 AC13: blank is fine on a draft; anything typed must be 8 to 15 digits. */
function isBlankOrPhoneNumber(value: string): boolean {
  const trimmed = value.trim()
  if (trimmed === '') return true
  const digitCount = trimmed.replace(/\D/g, '').length
  return (
    trimmed.length <= CONTACT_PHONE_MAX_LENGTH &&
    PHONE_NUMBER.test(trimmed) &&
    digitCount >= CONTACT_PHONE_MIN_DIGITS &&
    digitCount <= CONTACT_PHONE_MAX_DIGITS
  )
}

/**
 * Story 2.1 AC14: what is wrong with a chosen picture, or null. The backend checks the bytes
 * again; this only saves uploading a file that is certain to be refused.
 */
export function validateCoverImage(file: File): ErrorCode | null {
  if (!COVER_IMAGE_TYPES.includes(file.type)) return 'EVENT_PICTURE_TYPE_INVALID'
  if (file.size > MAX_COVER_IMAGE_BYTES) return 'EVENT_PICTURE_TOO_LARGE'
  return null
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
 * Story 2.1 AC2/AC3/AC6 and story 2.7: the first problem with the form (an error-registry code and the field to
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
  const registrationDateProblem = validateRegistrationDates(form, saved)
  if (registrationDateProblem) return registrationDateProblem
  if (!isBlankOrEmailAddress(form.contactEmail)) {
    return { code: 'EVENT_CONTACT_EMAIL_INVALID', fieldId: FIELD_ID.contactEmail }
  }
  if (!isBlankOrPhoneNumber(form.contactPhone)) {
    return { code: 'EVENT_CONTACT_PHONE_INVALID', fieldId: FIELD_ID.contactPhone }
  }
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
 * Story 2.1 AC17/AC18: the first problem with the registration opening/closing dates, or null.
 * Nothing to check when registration is not required - the dates are hidden and cleared then.
 * Mirrors the backend's `_check_registration`: a date already saved is not judged again unless
 * it was the one just changed (same "not re-rejected" principle as `validateDates`), but both
 * are re-checked against the proposed start whenever the start itself changes (AC18) - that
 * effect falls out of comparing against `form.startsAt` directly rather than only a "supplied"
 * start, the same way `_check_registration` does server-side.
 */
export function validateRegistrationDates(
  form: EventFormState,
  saved: EventDetail | null,
): FormProblem | null {
  if (!form.isRegistrationRequired) return null
  if (form.registrationOpensAt && !isReadableDateTime(form.registrationOpensAt)) {
    return { code: 'EVENT_REGISTRATION_DATE_INVALID', fieldId: FIELD_ID.registrationOpensAt }
  }
  if (form.registrationClosesAt && !isReadableDateTime(form.registrationClosesAt)) {
    return { code: 'EVENT_REGISTRATION_DATE_INVALID', fieldId: FIELD_ID.registrationClosesAt }
  }
  const savedOpensAt = saved?.registration_opens_at
    ? instantToInput(saved.registration_opens_at)
    : ''
  const savedClosesAt = saved?.registration_closes_at
    ? instantToInput(saved.registration_closes_at)
    : ''
  if (
    form.registrationOpensAt !== '' &&
    form.registrationOpensAt !== savedOpensAt &&
    isInThePast(form.registrationOpensAt)
  ) {
    return { code: 'EVENT_REGISTRATION_OPENS_IN_PAST', fieldId: FIELD_ID.registrationOpensAt }
  }
  if (
    form.registrationClosesAt !== '' &&
    form.registrationClosesAt !== savedClosesAt &&
    isInThePast(form.registrationClosesAt)
  ) {
    return { code: 'EVENT_REGISTRATION_CLOSES_IN_PAST', fieldId: FIELD_ID.registrationClosesAt }
  }
  // A registration window needs positive width - equal is refused, matching the backend's own
  // ck_events_registration_window constraint.
  if (
    form.registrationOpensAt &&
    form.registrationClosesAt &&
    form.registrationOpensAt >= form.registrationClosesAt
  ) {
    return {
      code: 'EVENT_REGISTRATION_OPENS_AFTER_CLOSES',
      fieldId: FIELD_ID.registrationOpensAt,
    }
  }
  if (form.registrationOpensAt && form.startsAt && form.registrationOpensAt > form.startsAt) {
    return { code: 'EVENT_REGISTRATION_OPENS_AFTER_START', fieldId: FIELD_ID.registrationOpensAt }
  }
  if (form.registrationClosesAt && form.startsAt && form.registrationClosesAt > form.startsAt) {
    return {
      code: 'EVENT_REGISTRATION_CLOSES_AFTER_START',
      fieldId: FIELD_ID.registrationClosesAt,
    }
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
  if (!isBlankOrEmailAddress(form.contactEmail)) {
    problems[FIELD_ID.contactEmail] = 'EVENT_CONTACT_EMAIL_INVALID'
  }
  if (!isBlankOrPhoneNumber(form.contactPhone)) {
    problems[FIELD_ID.contactPhone] = 'EVENT_CONTACT_PHONE_INVALID'
  }
  for (const requirement of form.venueRequirements) {
    const capacityProblem = getCapacityProblem(requirement, form)
    if (capacityProblem) {
      problems[getVenueRequirementFieldId(requirement.key, 'capacity')] = capacityProblem
    }
    for (const [code, facility] of Object.entries(requirement.facilities)) {
      if (!isBlankOrPositiveWholeNumber(facility.quantity)) {
        problems[getFacilityQuantityId(requirement.key, code)] = 'EVENT_FACILITY_QUANTITY_INVALID'
      }
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
  if (!form.contactName.trim()) missing.push('point of contact name')
  if (!form.contactEmail.trim()) missing.push('point of contact email')
  if (!form.contactPhone.trim()) missing.push('point of contact phone number')
  // Story 2.7 AC8: at least one requirement, or "none"; each listed one needs a name and a number
  // of people, pointed out by its place in the list.
  if (!form.hasNoVenueRequirements && form.venueRequirements.length === 0) {
    missing.push('venue requirements (choose some, or mark none)')
  }
  form.venueRequirements.forEach((requirement, index) => {
    if (!requirement.name.trim()) missing.push(`venue requirement ${index + 1}: name`)
    if (!isPositiveWholeNumber(requirement.capacity)) {
      missing.push(`venue requirement ${index + 1}: number of people`)
    }
  })
  const hasAccessibilityAnswer =
    form.hasNoAccessibilityNeeds ||
    Object.keys(form.accessibility).length > 0 ||
    form.accessibilityNotes.trim() !== ''
  if (!hasAccessibilityAnswer) missing.push('accessibility needs (choose some, or mark none)')
  if (form.isRegistrationRequired && !form.registrationClosesAt) {
    missing.push('registration closing date')
  }
  return missing
}

/** Story 2.7 AC6: what is wrong with a requirement's number of people, or null. Blank is fine on a
 * draft; anything typed is a positive whole number, no more than the expected attendance. */
function getCapacityProblem(
  requirement: VenueRequirementDraft,
  form: EventFormState,
): ErrorCode | null {
  if (!isBlankOrPositiveWholeNumber(requirement.capacity)) {
    return 'VENUE_REQUIREMENT_CAPACITY_INVALID'
  }
  if (
    requirement.capacity.trim() !== '' &&
    isPositiveWholeNumber(form.attendance) &&
    Number(requirement.capacity) > Number(form.attendance)
  ) {
    return 'VENUE_REQUIREMENT_OVER_ATTENDANCE'
  }
  return null
}

/**
 * Story 2.7: the first problem with the venue requirements, in list order, or null - the rules the
 * backend's `_check_venue_requirement_rules` applies, so a refusal is said before a round trip.
 * AC2: both times or neither. AC5/AC10: within the event's proposed start and end, inclusive, and
 * ending after starting - judged against the event's times as they stand on the form, so moving
 * the event flags a requirement left outside it. AC6: the number of people. AC9: no two share a
 * name, trimmed and case-insensitive.
 */
function validateVenueRequirements(form: EventFormState): FormProblem | null {
  const seenNames = new Set<string>()
  for (const requirement of form.venueRequirements) {
    const fieldId = (field: VenueRequirementField) =>
      getVenueRequirementFieldId(requirement.key, field)
    const capacityProblem = getCapacityProblem(requirement, form)
    if (capacityProblem) return { code: capacityProblem, fieldId: fieldId('capacity') }
    const { startsAt, endsAt } = requirement
    if (startsAt && !isReadableDateTime(startsAt)) {
      return { code: 'VENUE_REQUIREMENT_DATE_INVALID', fieldId: fieldId('starts') }
    }
    if (endsAt && !isReadableDateTime(endsAt)) {
      return { code: 'VENUE_REQUIREMENT_DATE_INVALID', fieldId: fieldId('ends') }
    }
    if ((startsAt === '') !== (endsAt === '')) {
      return {
        code: 'VENUE_REQUIREMENT_TIMES_INCOMPLETE',
        fieldId: fieldId(startsAt === '' ? 'starts' : 'ends'),
      }
    }
    if (startsAt && endsAt) {
      if (endsAt <= startsAt) {
        return { code: 'VENUE_REQUIREMENT_END_BEFORE_START', fieldId: fieldId('ends') }
      }
      if (form.startsAt && startsAt < form.startsAt) {
        return { code: 'VENUE_REQUIREMENT_STARTS_BEFORE_EVENT', fieldId: fieldId('starts') }
      }
      if (form.endsAt && endsAt > form.endsAt) {
        return { code: 'VENUE_REQUIREMENT_ENDS_AFTER_EVENT', fieldId: fieldId('ends') }
      }
    }
    const name = requirement.name.trim().toLowerCase()
    if (name !== '') {
      if (seenNames.has(name)) {
        return { code: 'VENUE_REQUIREMENT_NAME_DUPLICATE', fieldId: fieldId('name') }
      }
      seenNames.add(name)
    }
    const badFacility = Object.entries(requirement.facilities).find(
      ([, facility]) => !isBlankOrPositiveWholeNumber(facility.quantity),
    )
    if (badFacility) {
      return {
        code: 'EVENT_FACILITY_QUANTITY_INVALID',
        fieldId: getFacilityQuantityId(requirement.key, badFacility[0]),
      }
    }
  }
  return null
}

/** The first problem with the venue requirements and equipment, or null. */
function validateRequirements(
  form: EventFormState,
  availability: Record<string, number> | null,
): FormProblem | null {
  const venueProblem = validateVenueRequirements(form)
  if (venueProblem) return venueProblem
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
    contact_name: textOrNull(form.contactName),
    contact_email: textOrNull(form.contactEmail),
    contact_phone: textOrNull(form.contactPhone),
    venue_requirements: hasNoVenueNeeds
      ? []
      : form.venueRequirements.map((requirement) => ({
          id: requirement.id,
          name: textOrNull(requirement.name),
          capacity: requirement.capacity.trim() === '' ? null : Number(requirement.capacity),
          starts_at: requirement.startsAt ? inputToInstant(requirement.startsAt) : null,
          ends_at: requirement.endsAt ? inputToInstant(requirement.endsAt) : null,
          layout_code: textOrNull(requirement.layoutCode),
          facilities: Object.entries(requirement.facilities).map(([code, facility]) => ({
            code,
            quantity: facility.quantity.trim() === '' ? null : Number(facility.quantity),
            notes: textOrNull(facility.notes),
          })),
          notes: textOrNull(requirement.notes),
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
    registration_required: form.isRegistrationRequired,
    registration_opens_at:
      form.isRegistrationRequired && form.registrationOpensAt
        ? inputToInstant(form.registrationOpensAt)
        : null,
    registration_closes_at:
      form.isRegistrationRequired && form.registrationClosesAt
        ? inputToInstant(form.registrationClosesAt)
        : null,
    is_public: form.isPublic,
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
