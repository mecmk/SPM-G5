import {
  APPROVABLE_FIELDS,
  type ChangeRequestField,
  type ChangeRequestStatus,
} from '../api/changeRequests'
import type { EventReferenceData, EventStatus } from '../api/events'
import type { IconName } from '../components/Icon'
import { CHANGE_APPROVABLE_STATUS } from '../shared/eventStatus'
import { formatDate, formatDateTime, formatSchedule, NOT_RECORDED } from '../shared/format'

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

/** Story 19.1 AC1/AC9, story 19.2 AC2/AC3: how each request status reads. */
export const STATUS_LABELS: Record<ChangeRequestStatus, string> = {
  PENDING: 'Pending',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  WITHDRAWN: 'Withdrawn',
}

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
  people: 'people',
  layout: 'grid',
  time: 'calendar',
  facilities: 'building',
  notes: 'pencil',
}

// How a side reads when the thing is not there on it.
const NOT_THERE_NOW = 'Not requested'
const NOT_THERE_REQUESTED = 'Removed'
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
  name: string | null
  capacity: number | null
  layout_code: string | null
  notes: string | null
  facilities: FacilityValue[]
}
interface EquipmentValue {
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
  if (formatDate(value.starts_at) === formatDate(value.ends_at)) {
    return formatSchedule(value.starts_at, value.ends_at)
  }
  return `${formatDateTime(value.starts_at)} – ${formatDateTime(value.ends_at)}`
}

function describeMoment(stamp: string | null): string {
  return stamp === null ? NOT_RECORDED : formatDateTime(stamp)
}

function describeLayout(code: string | null, names: Names): string {
  return code === null ? 'Any' : (names.layouts.get(code) ?? code)
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

function requirementKey(requirement: RequirementValue): string {
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

/** Requirements are matched by name, which is unique on an event (2.7 AC9); one renamed reads as
 *  one removed and one added, since the stored values carry no ids (story 19.1). */
function venueRequirementChanges(
  now: RequirementValue[],
  requested: RequirementValue[],
  names: Names,
): ChangeLine[] {
  const requestedByKey = new Map(requested.map((item) => [requirementKey(item), item]))
  const nowKeys = new Set(now.map(requirementKey))
  const lines: ChangeLine[] = []
  for (const item of now) {
    const kept = requestedByKey.get(requirementKey(item))
    if (kept === undefined) {
      lines.push({
        icon: 'building',
        what: item.name ?? 'Unnamed',
        now: describeRequirement(item, names),
        requested: NOT_THERE_REQUESTED,
      })
    } else {
      lines.push(...requirementChanges(item, kept, names))
    }
  }
  for (const item of requested) {
    if (!nowKeys.has(requirementKey(item))) {
      lines.push({
        icon: 'building',
        what: item.name ?? 'Unnamed',
        now: NOT_THERE_NOW,
        requested: describeRequirement(item, names),
      })
    }
  }
  return lines
}

/** Equipment is matched by type, which an event lists once (2.1 AC6). */
function equipmentChanges(
  now: EquipmentValue[],
  requested: EquipmentValue[],
  names: Names,
): ChangeLine[] {
  const typeName = (code: string) => names.equipment.get(code) ?? code
  const requestedByType = new Map(requested.map((line) => [line.equipment_type_code, line]))
  const nowTypes = new Set(now.map((line) => line.equipment_type_code))
  const lines: ChangeLine[] = []
  for (const line of now) {
    const name = typeName(line.equipment_type_code)
    const kept = requestedByType.get(line.equipment_type_code)
    if (kept === undefined) {
      lines.push({
        icon: 'box',
        what: name,
        now: `×${line.quantity}`,
        requested: NOT_THERE_REQUESTED,
      })
      continue
    }
    if (kept.quantity !== line.quantity) {
      lines.push({
        icon: 'box',
        what: `${name} · quantity`,
        now: `×${line.quantity}`,
        requested: `×${kept.quantity}`,
      })
    }
    if (kept.technical_notes !== line.technical_notes) {
      lines.push({
        icon: 'pencil',
        what: `${name} · notes`,
        now: line.technical_notes ?? NONE,
        requested: kept.technical_notes ?? NONE,
      })
    }
  }
  for (const line of requested) {
    if (!nowTypes.has(line.equipment_type_code)) {
      lines.push({
        icon: 'box',
        what: typeName(line.equipment_type_code),
        now: NOT_THERE_NOW,
        requested: `×${line.quantity}`,
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

/**
 * Story 19.2 (Phase 1): whether a pending request on an event in `eventStatus` can be approved
 * yet - as the backend decides it, so Approve is not offered only to be refused. Any pending
 * request can be rejected.
 */
export function canApproveYet(field: ChangeRequestField, eventStatus: EventStatus): boolean {
  return APPROVABLE_FIELDS.includes(field) && eventStatus === CHANGE_APPROVABLE_STATUS
}

/** Story 19.2 (Phase 1): why Approve is not offered on a request `canApproveYet` refuses. */
export const NOT_YET_APPROVABLE_NOTE =
  'This change cannot be approved yet. Reject it, or leave it pending.'
