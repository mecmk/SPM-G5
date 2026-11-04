import type { OutOfServiceReason, OutOfServiceRecord } from '../api/equipment'
import { formatDateTime } from '../shared/format'

/** Story 16.2 AC1: each reason as Technical Support reads it, in the order the form offers them. */
export const REASON_LABELS: Record<OutOfServiceReason, string> = {
  DAMAGED: 'Damaged',
  MAINTENANCE: 'Under maintenance',
  LOST: 'Lost',
  OTHER: 'Other',
}

export const REASON_CODES = Object.keys(REASON_LABELS) as OutOfServiceReason[]

/** Story 16.2 AC2: how many units a record has out. */
export function describeUnitsOut(quantity: number): string {
  return `${quantity} out of service`
}

/** Story 16.2 AC1/AC2: when a record's units are out - until its end, or until it is ended. */
export function describeOutPeriod(record: OutOfServiceRecord): string {
  const until = record.ends_at === null ? 'ended' : formatDateTime(record.ends_at)
  return `From ${formatDateTime(record.starts_at)} until ${until}`
}

/** Story 16.2 AC2: when the first units out now are back - a dash when none are out, and "No end
 *  date" when the ones out have no end yet. */
export function describeBackInService(outNow: number, backAt: string | null): string {
  if (outNow === 0) return '—'
  return backAt === null ? 'No end date' : formatDateTime(backAt)
}

/** Story 16.2 AC2: whether a record's units are out now - by the page's clock; the server decides
 *  again whether it is ended or removed. */
export function hasStarted(record: OutOfServiceRecord, now: number): boolean {
  return Date.parse(record.starts_at) < now
}

/** Story 16.2 AC4/AC5: how short a hold would be. */
export function describeHoldShort(unitsShort: number, unitsHeld: number): string {
  return `${unitsShort} of ${unitsHeld} short`
}
