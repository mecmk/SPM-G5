import type { ChangeRequest, ChangeRequestField, ChangeRequestStatus } from '../api/changeRequests'
import type { EventReferenceData } from '../api/events'
import type { IconName } from '../components/Icon'
import { ANY_LAYOUT, formatDateTime, formatSchedule, NOT_RECORDED } from '../shared/format'

/**
 * Story 19.1 AC1: how each requestable field is named, in the order the form offers them.
 * Mirrors the backend's `FIELD_LABELS` (app/change_requests/service.py). Story 19.2 names the
 * fields in its queue and dialogs the same way.
 */
export const FIELD_LABELS: Record<ChangeRequestField, string> = {
  schedule: 'Date and time',
  expected_attendance: 'Expected attendance',
  venue_requirements: 'Venue requirements',
  equipment: 'Equipment',
}

/** Story 19.1 AC1/AC9, story 19.2 AC2/AC3, story 6.2 AC4: how each request status reads. */
export const STATUS_LABELS: Record<ChangeRequestStatus, string> = {
  PENDING: 'Pending',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  WITHDRAWN: 'Withdrawn',
  CANCELLED: 'Cancelled',
}

/** Story 19.2 AC7: why a pending request can only be rejected - the event no longer has the value
 *  it recorded as current, because another request's approval moved it. */
export const OUT_OF_DATE_NOTE =
  'The event has changed since this request was raised, so it can no longer be approved. Reject it so the organiser can ask again.'

/** Story 19.2 AC1: what a request is about, in words - "Changes to date and time". */
export function changeTitle(field: ChangeRequestField): string {
  return `Changes to ${FIELD_LABELS[field].toLowerCase()}`
}

/** One difference a request asks for: what it is, its value now, and the value asked for, with
 *  the icon it is shown beside. */
export interface ChangeLine {
  icon: IconName
  what: string
  now: string
  requested: string
}

/** The icon beside each part of a venue requirement. */
const REQUIREMENT_PART_ICONS: Record<string, IconName> = {
  name: 'pencil',
  people: 'people',
  layout: 'grid',
  time: 'calendar',
  facilities: 'building',
  notes: 'pencil',
}

// How a side reads when the thing is not there on it.
const NOT_THERE_NOW = 'Not requested'
export const NOT_THERE_REQUESTED = 'Removed'
const NONE = 'None'

/** The canonical value shapes the backend stores (app/change_requests/service.py). */
interface ScheduleValue {
  starts_at: string | null
  ends_at: string | null
}
interface FacilityValue {
  code: string
  quantity: number | null
  notes: string | null
}
interface RequirementValue extends ScheduleValue {
  /** Story 19.2: kept since then; absent from a request raised before it. */
  id?: string | null
  name: string | null
  capacity: number | null
  layout_code: string | null
  notes: string | null
  facilities: FacilityValue[]
}
/** A venue requirement as far as the attendance is concerned: its name and number of people. */
interface SizedRequirement {
  name: string | null
  capacity: number | null
}

/** Fix f19.1.2 (2.7 AC6): the fewest people the event can expect, and the requirement that sets
 *  it. */
interface AttendanceMinimum {
  minimum: number
  requirement: string
}

/**
 * Fix f19.1.2 (2.7 AC6): the most people any of `requirements` needs room for, which the expected
 * attendance cannot go below, and the requirement needing it - the first on the form when two tie,
 * one without a name named by its place. Null when none gives a number. Mirrors the backend's
 * `check_attendance_leaves_room` (app/events/service.py).
 */
function findAttendanceMinimum(requirements: SizedRequirement[]): AttendanceMinimum | null {
  let found: AttendanceMinimum | null = null
  for (const [index, requirement] of requirements.entries()) {
    if (requirement.capacity === null) continue
    if (found === null || requirement.capacity > found.minimum) {
      found = {
        minimum: requirement.capacity,
        requirement: requirement.name || `Venue requirement ${index + 1}`,
      }
    }
  }
  return found
}

/** Fix f19.1.2 (Q80): the venue requirements change waiting for a decision that can still be
 *  approved - not out of date (19.2 AC7) - if there is one. */
function findWaitingRequirementsChange(requests: ChangeRequest[]): ChangeRequest | undefined {
  return requests.find(
    (request) =>
      request.field === 'venue_requirements' &&
      request.status === 'PENDING' &&
      !request.is_out_of_date,
  )
}

/**
 * Fix f19.1.2 (19.2 AC2, Q81): why a pending attendance change cannot be approved yet - a venue
 * requirement still needs room for more people than it asks for - and what to do: approve the
 * waiting venue requirements change first, or wait for one that lowers it. Null when the change
 * is not a pending attendance change, or nothing stands in its way. The server refuses the
 * approval either way; this tells the coordinator before they try.
 */
export function describeAttendanceWait(
  request: ChangeRequest,
  requirements: SizedRequirement[],
  requests: ChangeRequest[],
): string | null {
  if (request.field !== 'expected_attendance' || request.status !== 'PENDING') return null
  const current = findAttendanceMinimum(requirements)
  if (current === null || (request.proposed_value as number) >= current.minimum) return null
  const needs = `${current.requirement} needs room for ${current.minimum} people`
  return findWaitingRequirementsChange(requests) === undefined
    ? `${needs}, so this cannot be approved until a venue requirements change lowers it.`
    : `${needs} until the venue requirements change is approved, so approve that first.`
}

/**
 * Fix f19.1.2 (19.1 AC4, CL-172 (4)): what the change form says beneath the new attendance - the
 * lowest the server takes, by its own rule. That is the lowest the event's venue requirements
 * allow, or, when a venue requirements change waiting for a decision (and not out of date, 19.2
 * AC7) allows lower, the lowest that change allows, saying it is approved first. Null when no
 * requirement gives a number of people.
 */
export function describeAttendanceMinimum(
  requirements: SizedRequirement[],
  requests: ChangeRequest[],
): string | null {
  const current = findAttendanceMinimum(requirements)
  if (current === null) return null
  const pending = findWaitingRequirementsChange(requests)
  const proposed =
    pending === undefined
      ? null
      : findAttendanceMinimum(pending.proposed_value as RequirementValue[])
  if (proposed === null || proposed.minimum >= current.minimum) {
    return `At least ${current.minimum}: ${current.requirement} needs room for ${current.minimum} people.`
  }
  return `At least ${proposed.minimum}: your venue requirements change brings ${proposed.requirement} to ${proposed.minimum} people, and is approved before this one.`
}

interface EquipmentValue {
  /** Story 19.2: kept since then; absent from a request raised before it. */
  id?: string | null
  equipment_type_code: string
  quantity: number
  technical_notes: string | null
}

/** Names from the reference lists, so a code never reaches the screen when its name is known. */
interface Names {
  layouts: Map<string, string>
  facilities: Map<string, string>
  equipment: Map<string, string>
}

function namesByCode(items: { code: string; name: string }[] | undefined): Map<string, string> {
  return new Map((items ?? []).map((item) => [item.code, item.name]))
}

function namesFrom(references: EventReferenceData | null): Names {
  return {
    layouts: namesByCode(references?.layouts),
    facilities: namesByCode(references?.facilities),
    equipment: namesByCode(references?.equipment_types),
  }
}

/** "Wed, 18 Nov 2026 · 09:00–17:00", or both dates when it runs over more than one day. */
function describePeriod(value: ScheduleValue): string {
  if (value.starts_at === null || value.ends_at === null) return NOT_RECORDED
  return formatSchedule(value.starts_at, value.ends_at)
}

function describeMoment(stamp: string | null): string {
  return stamp === null ? NOT_RECORDED : formatDateTime(stamp)
}

function describeLayout(code: string | null, names: Names): string {
  return code === null ? ANY_LAYOUT : (names.layouts.get(code) ?? code)
}

function describeFacilities(facilities: FacilityValue[], names: Names): string {
  if (facilities.length === 0) return NONE
  return facilities
    .map((facility) => {
      const name = names.facilities.get(facility.code) ?? facility.code
      return facility.quantity === null ? name : `${name} ×${facility.quantity}`
    })
    .join(', ')
}

/** A whole requirement on one line, for one that is added or removed. */
function describeRequirement(requirement: RequirementValue, names: Names): string {
  return [
    `${requirement.capacity ?? '?'} people`,
    describeLayout(requirement.layout_code, names),
    describePeriod(requirement),
  ].join(' · ')
}

function nameKey(requirement: RequirementValue): string {
  return (requirement.name ?? '').trim().toLowerCase()
}

/** Each part of a requirement kept on both sides that differs, labelled with its name. */
function requirementChanges(
  now: RequirementValue,
  requested: RequirementValue,
  names: Names,
): ChangeLine[] {
  const name = requested.name ?? 'Unnamed'
  const parts: [string, string, string][] = [
    ['name', now.name ?? 'Unnamed', name],
    ['people', `${now.capacity ?? '?'}`, `${requested.capacity ?? '?'}`],
    [
      'layout',
      describeLayout(now.layout_code, names),
      describeLayout(requested.layout_code, names),
    ],
    ['time', describePeriod(now), describePeriod(requested)],
    [
      'facilities',
      describeFacilities(now.facilities, names),
      describeFacilities(requested.facilities, names),
    ],
    ['notes', now.notes ?? NONE, requested.notes ?? NONE],
  ]
  return parts
    .filter(([, before, after]) => before !== after)
    .map(([part, before, after]) => ({
      icon: REQUIREMENT_PART_ICONS[part],
      what: `${name} · ${part}`,
      now: before,
      requested: after,
    }))
}

/** The requirement in `now` that `requested` edits: the one with its id, or - for a request
 *  raised before ids were kept - the one of the same name; undefined for a new requirement. */
function requirementEdited(
  requested: RequirementValue,
  now: RequirementValue[],
): RequirementValue | undefined {
  if (requested.id !== undefined) {
    return requested.id === null ? undefined : now.find((item) => item.id === requested.id)
  }
  return now.find((item) => nameKey(item) === nameKey(requested))
}

/** Requirements are matched as the backend applies them (story 19.2): by id, or by name for a
 *  request raised before ids were kept. A renamed requirement reads as a change of name. */
function venueRequirementChanges(
  now: RequirementValue[],
  requested: RequirementValue[],
  names: Names,
): ChangeLine[] {
  const lines: ChangeLine[] = []
  const edited = new Set<RequirementValue>()
  for (const item of requested) {
    const before = requirementEdited(item, now)
    if (before === undefined) {
      lines.push({
        icon: 'building',
        what: item.name ?? 'Unnamed',
        now: NOT_THERE_NOW,
        requested: describeRequirement(item, names),
      })
      continue
    }
    edited.add(before)
    lines.push(...requirementChanges(before, item, names))
  }
  for (const item of now) {
    if (!edited.has(item)) {
      lines.push({
        icon: 'building',
        what: item.name ?? 'Unnamed',
        now: describeRequirement(item, names),
        requested: NOT_THERE_REQUESTED,
      })
    }
  }
  return lines
}

/** The item in `now` that `requested` edits: the one with its id, or - for a request raised
 *  before ids were kept - the one of the same type; undefined for a new item. */
function equipmentEdited(
  requested: EquipmentValue,
  now: EquipmentValue[],
): EquipmentValue | undefined {
  if (requested.id !== undefined) {
    return requested.id === null ? undefined : now.find((item) => item.id === requested.id)
  }
  return now.find((item) => item.equipment_type_code === requested.equipment_type_code)
}

/** Items are matched as the backend applies them (story 19.2): by id, or by type for a request
 *  raised before ids were kept. Once an item is declined its type can be asked for again (15.1
 *  AC6), so the same type may appear twice. */
function equipmentChanges(
  now: EquipmentValue[],
  requested: EquipmentValue[],
  names: Names,
): ChangeLine[] {
  const typeName = (code: string) => names.equipment.get(code) ?? code
  const lines: ChangeLine[] = []
  const edited = new Set<EquipmentValue>()
  for (const item of requested) {
    const before = equipmentEdited(item, now)
    const name = typeName(item.equipment_type_code)
    if (before === undefined) {
      lines.push({ icon: 'box', what: name, now: NOT_THERE_NOW, requested: `×${item.quantity}` })
      continue
    }
    edited.add(before)
    if (before.equipment_type_code !== item.equipment_type_code) {
      lines.push({
        icon: 'box',
        what: `${name} · type`,
        now: typeName(before.equipment_type_code),
        requested: name,
      })
    }
    if (before.quantity !== item.quantity) {
      lines.push({
        icon: 'box',
        what: `${name} · quantity`,
        now: `×${before.quantity}`,
        requested: `×${item.quantity}`,
      })
    }
    if (before.technical_notes !== item.technical_notes) {
      lines.push({
        icon: 'pencil',
        what: `${name} · notes`,
        now: before.technical_notes ?? NONE,
        requested: item.technical_notes ?? NONE,
      })
    }
  }
  for (const item of now) {
    if (!edited.has(item)) {
      lines.push({
        icon: 'box',
        what: typeName(item.equipment_type_code),
        now: `×${item.quantity}`,
        requested: NOT_THERE_REQUESTED,
      })
    }
  }
  return lines
}

/**
 * Story 19.1 AC1, story 19.2 AC1: what a request would change, one line per difference, with the
 * value now beside the value asked for - so a reviewer sees "Main venue · people: 180 → 167"
 * rather than two whole lists to compare by eye.
 */
export function describeChanges(
  field: ChangeRequestField,
  current: unknown,
  proposed: unknown,
  references: EventReferenceData | null,
): ChangeLine[] {
  const names = namesFrom(references)
  if (field === 'schedule') {
    const now = (current ?? { starts_at: null, ends_at: null }) as ScheduleValue
    const requested = proposed as ScheduleValue
    const lines: ChangeLine[] = [
      {
        icon: 'calendar',
        what: 'Start',
        now: describeMoment(now.starts_at),
        requested: describeMoment(requested.starts_at),
      },
      {
        icon: 'calendar',
        what: 'End',
        now: describeMoment(now.ends_at),
        requested: describeMoment(requested.ends_at),
      },
    ]
    return lines.filter((line) => line.now !== line.requested)
  }
  if (field === 'expected_attendance') {
    return [
      {
        icon: 'people',
        what: 'Expected attendance',
        now: current === null ? NOT_RECORDED : `${current as number} people`,
        requested: `${proposed as number} people`,
      },
    ]
  }
  if (field === 'venue_requirements') {
    return venueRequirementChanges(
      (current ?? []) as RequirementValue[],
      proposed as RequirementValue[],
      names,
    )
  }
  return equipmentChanges((current ?? []) as EquipmentValue[], proposed as EquipmentValue[], names)
}
