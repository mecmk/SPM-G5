import { formatDateTime } from '../shared/format'

export type ClarificationEntryKind = 'REQUEST' | 'RESPONSE' | 'NOTE'

export interface ClarificationEntry {
  id: string
  kind: ClarificationEntryKind
  authorId: string
  authorName: string
  message: string
  createdAt: string
}

export interface ClarificationHistoryProps {
  entries: ClarificationEntry[] | null
  error: string | null
  /** The signed-in viewer's id, so their own messages render as the "self" bubble; null when
   *  there is no viewer to compare against. */
  currentUserId: string | null
}

const KIND_LABELS: Record<ClarificationEntryKind, string> = {
  REQUEST: 'Clarification requested',
  RESPONSE: 'Response',
  NOTE: 'Note',
}

/** Up to two initials for the round avatar, e.g. "Chloe Coordinator" -> "CC". No dependency. */
function initialsFor(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'
  const first = words[0]!.charAt(0)
  const last = words.length > 1 ? words[words.length - 1]!.charAt(0) : ''
  return (first + last).toUpperCase()
}

/**
 * Story 4.6 AC2 - the clarification conversation on a request, oldest first, each with its
 * author and timestamp, laid out as a two-party chat thread with the viewer's own messages on
 * the right. AC3: entries are historical and cannot be edited or removed - this component
 * renders no button or input, so there is nothing here to change one with.
 */
export function ClarificationHistory({ entries, error, currentUserId }: ClarificationHistoryProps) {
  return (
    <section className="card stack" aria-labelledby="event-clarifications-heading">
      <p className="eyebrow" id="event-clarifications-heading">
        Clarifications
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {entries === null && !error && <p className="muted">Loading…</p>}
      {entries !== null && entries.length === 0 && (
        <p className="muted">No clarification has been requested on this request.</p>
      )}
      {entries !== null && entries.length > 0 && (
        <ul className="clarification-list">
          {entries.map((entry) => {
            const isSelf = currentUserId !== null && entry.authorId === currentUserId
            return (
              <li
                key={entry.id}
                className={`clarification-row${isSelf ? ' clarification-row-self' : ''}`}
              >
                <span
                  className={`clarification-avatar${isSelf ? ' clarification-avatar-self' : ''}`}
                  aria-hidden="true"
                >
                  {initialsFor(entry.authorName)}
                </span>
                <div
                  className={`clarification-bubble${isSelf ? ' clarification-bubble-self' : ''}`}
                >
                  <p className="clarification-bubble-meta">
                    {entry.authorName} · {KIND_LABELS[entry.kind]} ·{' '}
                    {formatDateTime(entry.createdAt)}
                  </p>
                  <p className="clarification-bubble-text">{entry.message}</p>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
