import { useCallback, useState } from 'react'
import { listEventChanges, type EventChange, type EventReferenceData } from '../api/events'
import { EmptyState } from '../components/EmptyState'
import { LoadingState } from '../layout/LoadingState'
import { formatDateTime, NONE, shortReference } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { describeChanges, FIELD_LABELS } from './changeRequestValues'

/** Story 7.4 AC3: a value longer than this is cut short, with a way to show all of it. */
const SHORT_VALUE_LENGTH = 120

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

/** One difference a history entry shows: what changed, and its value before and after - or, for
 *  the cover picture, only what happened to it. */
interface ChangeLine {
  what: string
  before: string
  after: string | null
}

/** An accessibility need as stored: its feature code and any notes. */
interface AccessibilityNeedValue {
  code: string
  notes: string | null
}

/** Story 7.4 AC1: a recorded value as the page shows it. */
function describeValue(
  field: string,
  value: unknown,
  references: EventReferenceData | null,
): string {
  if (value === null || value === undefined || value === '') return NONE
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (field === 'accessibility_needs') {
    const needs = value as AccessibilityNeedValue[]
    if (needs.length === 0) return NONE
    const names = new Map(
      (references?.accessibility_features ?? []).map((item) => [item.code, item.name]),
    )
    return needs
      .map((need) => {
        const name = names.get(need.code) ?? need.code
        return need.notes === null ? name : `${name} (${need.notes})`
      })
      .join('; ')
  }
  if (typeof value === 'string' && field.endsWith('_at')) return formatDateTime(value)
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

/** The cover picture's address means nothing to a reader, so say what happened to it. */
function describePictureChange(change: EventChange): string {
  if (change.old_value === null) return 'Added'
  return change.new_value === null ? 'Removed' : 'Replaced'
}

/** Story 7.4 AC1: an entry's differences. Venue requirements and equipment are lists, so they are
 *  compared part by part, with names from the reference lists, as a change request is (19.1):
 *  "Main venue · layout: Classroom → Banquet" rather than two whole lists. */
function describeEntry(change: EventChange, references: EventReferenceData | null): ChangeLine[] {
  if (change.field === 'venue_requirements' || change.field === 'equipment') {
    return describeChanges(change.field, change.old_value, change.new_value ?? [], references).map(
      (line) => ({ what: line.what, before: line.now, after: line.requested }),
    )
  }
  const what = CHANGE_FIELD_LABELS[change.field] ?? change.field
  if (change.field === 'cover_image_url') {
    return [{ what, before: describePictureChange(change), after: null }]
  }
  return [
    {
      what,
      before: describeValue(change.field, change.old_value, references),
      after: describeValue(change.field, change.new_value, references),
    },
  ]
}

/** Story 7.4 AC3: a value, cut short past `SHORT_VALUE_LENGTH` with a Show more / Show less. */
function ChangeValue({ text }: { text: string }) {
  const [isExpanded, setIsExpanded] = useState(false)
  if (text.length <= SHORT_VALUE_LENGTH) return <span className="wrap-anywhere">{text}</span>

  function toggle() {
    setIsExpanded((was) => !was)
  }

  return (
    <span className="wrap-anywhere">
      {isExpanded ? text : `${text.slice(0, SHORT_VALUE_LENGTH)}…`}{' '}
      <button type="button" className="link" aria-expanded={isExpanded} onClick={toggle}>
        {isExpanded ? 'Show less' : 'Show more'}
      </button>
    </span>
  )
}

/** Story 7.4 AC4: the entries of one save - the same time and the same person - kept together,
 *  newest save first and each save's own fields in the order they were recorded. */
function groupBySave(changes: EventChange[]): EventChange[][] {
  const saves: EventChange[][] = []
  for (const change of changes) {
    const last = saves.at(-1)?.[0]
    if (
      last !== undefined &&
      last.changed_at === change.changed_at &&
      last.changed_by_name === change.changed_by_name
    ) {
      saves.at(-1)!.unshift(change)
    } else {
      saves.push([change])
    }
  }
  return saves
}

export interface ChangeHistorySectionProps {
  eventId: string
  /** Changes whenever the page reloads the event: the history is read again then. */
  version: string
  /** The pick-lists that name layouts, facilities, equipment and accessibility features; null
   *  while they load, when codes show instead. */
  references: EventReferenceData | null
}

/**
 * Story 7.4: what was changed on the event, by whom and when, for its organiser and assigned
 * coordinator (AC5). AC1 - each field with its old and new value and who saved it with their role,
 * newest save first. AC3 - "No changes yet" when there are none, and long values cut short. AC4 -
 * the fields of one save under one heading, and a change request's reference, as its card shows
 * it. AC5/AC6 - read-only; the server leaves out internal-notes changes for an organiser.
 */
export function ChangeHistorySection({ eventId, version, references }: ChangeHistorySectionProps) {
  // `version` is not sent: it only marks when the history must be read again.
  const load = useCallback(() => listEventChanges(eventId), [eventId, version])
  const { data: changes, error, isLoading } = useLoaded(load)

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
      {isLoading && <LoadingState label="Loading change history…" />}
      {changes !== null && changes.length === 0 && <EmptyState>No changes yet</EmptyState>}
      {changes !== null &&
        groupBySave(changes).map((save) => (
          <div className="stack" key={save[0]!.id}>
            <p className="muted">
              <span>{`${save[0]!.changed_by_name} (${save[0]!.changed_by_role_name})`}</span> ·{' '}
              <time dateTime={save[0]!.changed_at}>{formatDateTime(save[0]!.changed_at)}</time>
            </p>
            <ul className="stack">
              {save.flatMap((change) =>
                describeEntry(change, references).map((line, index) => (
                  <li key={`${change.id}-${index}`}>
                    <strong>{line.what}</strong>: <ChangeValue text={line.before} />
                    {line.after !== null && (
                      <>
                        {' '}
                        → <ChangeValue text={line.after} />
                      </>
                    )}
                    {change.change_request_id !== null && (
                      <span className="muted">
                        {' '}
                        (from change request {shortReference(change.change_request_id)})
                      </span>
                    )}
                  </li>
                )),
              )}
            </ul>
          </div>
        ))}
    </section>
  )
}
