import {
  APPROVABLE_FIELDS,
  type ChangeRequestField,
  type ChangeRequestStatus,
} from '../api/changeRequests'
import type { EventReferenceData, EventStatus } from '../api/events'
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

/** The canonical value shapes the backend stores (app/change_requests/service.py). */
interface ScheduleValue {
  starts_at: string | null
  ends_at: string | null
}
interface RequirementValue extends ScheduleValue {
  name: string | null
  capacity: number | null
  layout_code: string | null
}
interface EquipmentValue {
  equipment_type_code: string
  quantity: number
}

function namesByCode(items: { code: string; name: string }[] | undefined): Map<string, string> {
  return new Map((items ?? []).map((item) => [item.code, item.name]))
}

/** "Wed, 18 Nov 2026 · 09:00–17:00", or both dates when it runs over more than one day. */
function describeSchedule(value: ScheduleValue): string {
  if (value.starts_at === null || value.ends_at === null) return NOT_RECORDED
  if (formatDate(value.starts_at) === formatDate(value.ends_at)) {
    return formatSchedule(value.starts_at, value.ends_at)
  }
  return `${formatDateTime(value.starts_at)} – ${formatDateTime(value.ends_at)}`
}

/**
 * Story 19.1 AC1, story 19.2 AC1: a stored value in words, for a request's "now" and "requested"
 * lines. A venue requirement reads with its period, so a change of times alone shows.
 */
export function describeValue(
  field: ChangeRequestField,
  value: unknown,
  references: EventReferenceData | null,
): string {
  if (value === null || value === undefined) return NOT_RECORDED
  if (field === 'schedule') return describeSchedule(value as ScheduleValue)
  if (field === 'expected_attendance') return `${value as number} people`
  if (field === 'venue_requirements') {
    const layouts = namesByCode(references?.layouts)
    const requirements = value as RequirementValue[]
    if (requirements.length === 0) return 'No venue requirements'
    return requirements
      .map((item) => {
        const layout = item.layout_code
          ? `, ${layouts.get(item.layout_code) ?? item.layout_code}`
          : ''
        const period = item.starts_at === null ? '' : `, ${describeSchedule(item)}`
        return `${item.name ?? 'Unnamed'} (${item.capacity ?? '?'} people${layout}${period})`
      })
      .join('; ')
  }
  const types = namesByCode(references?.equipment_types)
  const lines = value as EquipmentValue[]
  if (lines.length === 0) return 'No equipment'
  return lines
    .map(
      (line) =>
        `${types.get(line.equipment_type_code) ?? line.equipment_type_code} ×${line.quantity}`,
    )
    .join('; ')
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
