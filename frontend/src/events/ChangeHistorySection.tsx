import { useEffect, useState } from 'react'
import { formatApiError } from '../api/client'
import { listEventChanges, type EventChange } from '../api/events'
import { EmptyState } from '../components/EmptyState'
import { formatDateTime } from '../shared/format'
import { FIELD_LABELS } from './changeRequestValues'

/** Story 7.4 AC3: a value longer than this is cut short, with a way to show all of it. */
const SHORT_VALUE_LENGTH = 120
/** Story 7.4 AC4: how much of a change request's id names it, as the booking requests page does. */
const SHORT_ID_LENGTH = 8
const NONE = 'None'

/** Story 7.4 AC1: how each recorded field is named. */
const CHANGE_FIELD_LABELS: Record<string, string> = {
  name: 'Event name',
  purpose: 'Purpose',
  description: 'Description',
  starts_at: 'Start',
  ends_at: 'End',
  expected_attendance: FIELD_LABELS.expected_attendance,
  contact_name: 'Contact name',
  contact_email: 'Contact email',
  contact_phone: 'Contact phone number',
  venue_none_required: 'No venue requirements',
  venue_requirements: FIELD_LABELS.venue_requirements,
  accessibility_none_required: 'No accessibility needs',
  accessibility_needs: 'Accessibility needs',
  accessibility_notes: 'Accessibility notes',
  equipment: FIELD_LABELS.equipment,
  registration_required: 'Registration required',
  registration_opens_at: 'Registration opens',
  registration_closes_at: 'Registration closes',
  is_public: 'Public',
  cover_image_url: 'Cover picture',
  internal_notes: 'Internal notes',
}

interface ListItem {
  name?: string | null
  capacity?: number | null
  code?: string
  equipment_type_code?: string
  quantity?: number | null
}

/** One list entry in words: a venue requirement by name and size, equipment by type and number,
 *  an accessibility need by its code. */
function describeItem(item: ListItem): string {
  if (item.equipment_type_code !== undefined) {
    return `${item.equipment_type_code} × ${item.quantity ?? '?'}`
  }
  if (item.code !== undefined) return item.code
  return `${item.name ?? 'Unnamed'} · ${item.capacity ?? '?'} people`
}

/** Story 7.4 AC1: a recorded value as the page shows it. */
function describeValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return NONE
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (field === 'cover_image_url') return 'Picture'
  if (Array.isArray(value)) {
    return value.length === 0
      ? NONE
      : value.map((item) => describeItem(item as ListItem)).join('; ')
  }
  if (typeof value === 'string' && field.endsWith('_at')) return formatDateTime(value)
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

/** Story 7.4 AC3: a value, cut short past `SHORT_VALUE_LENGTH` with a Show more / Show less. */
function ChangeValue({ text }: { text: string }) {
  const [isExpanded, setIsExpanded] = useState(false)
  if (text.length <= SHORT_VALUE_LENGTH) return <span>{text}</span>

  function toggle() {
    setIsExpanded((was) => !was)
  }

  return (
    <span>
      {isExpanded ? text : `${text.slice(0, SHORT_VALUE_LENGTH)}…`}{' '}
      <button type="button" className="link" aria-expanded={isExpanded} onClick={toggle}>
        {isExpanded ? 'Show less' : 'Show more'}
      </button>
    </span>
  )
}

/** Story 7.4 AC4: the entries of one save - the same time and the same person - kept together. */
function groupBySave(changes: EventChange[]): EventChange[][] {
  const saves: EventChange[][] = []
  for (const change of changes) {
    const last = saves.at(-1)?.[0]
    if (
      last !== undefined &&
      last.changed_at === change.changed_at &&
      last.changed_by_name === change.changed_by_name
    ) {
      saves.at(-1)!.push(change)
    } else {
      saves.push([change])
    }
  }
  return saves
}

export interface ChangeHistorySectionProps {
  eventId: string
  /** The event's `updated_at`: the history is read again whenever the event changes. */
  version: string
}

/**
 * Story 7.4: what was changed on the event, by whom and when, for its organiser and assigned
 * coordinator (AC5). AC1 - each field with its old and new value and who saved it with their role,
 * newest save first. AC3 - "No changes yet" when there are none, and long values cut short. AC4 -
 * the fields of one save under one heading, and a change request's reference. AC5/AC6 - read-only;
 * the server leaves out internal-notes changes for an organiser.
 */
export function ChangeHistorySection({ eventId, version }: ChangeHistorySectionProps) {
  const [changes, setChanges] = useState<EventChange[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listEventChanges(eventId)
      .then((data) => {
        if (!cancelled) setChanges(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [eventId, version])

  return (
    <section className="card stack" aria-labelledby="change-history-heading">
      <p className="eyebrow" id="change-history-heading">
        Change history
      </p>
      {error !== null && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {changes !== null && changes.length === 0 && <EmptyState>No changes yet</EmptyState>}
      {changes !== null &&
        groupBySave(changes).map((save) => (
          <div className="stack" key={save[0]!.id}>
            <p className="muted">
              <span>{`${save[0]!.changed_by_name} (${save[0]!.changed_by_role_name})`}</span> ·{' '}
              <time dateTime={save[0]!.changed_at}>{formatDateTime(save[0]!.changed_at)}</time>
            </p>
            <ul className="stack">
              {save.map((change) => (
                <li key={change.id}>
                  <strong>{CHANGE_FIELD_LABELS[change.field] ?? change.field}</strong>:{' '}
                  <ChangeValue text={describeValue(change.field, change.old_value)} /> →{' '}
                  <ChangeValue text={describeValue(change.field, change.new_value)} />
                  {change.change_request_id !== null && (
                    <span className="muted">
                      {' '}
                      (from change request #
                      {change.change_request_id.slice(-SHORT_ID_LENGTH).toUpperCase()})
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
    </section>
  )
}
