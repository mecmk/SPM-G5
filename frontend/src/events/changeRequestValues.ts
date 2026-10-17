import type { ChangeRequestField, ChangeRequestStatus } from '../api/changeRequests'
import type { EventReferenceData } from '../api/events'
import type { IconName } from '../components/Icon'
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
  name: 'pencil',
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
  /** Story 19.2: kept since then; absent from a request raised before it. */
  id?: string | null
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
