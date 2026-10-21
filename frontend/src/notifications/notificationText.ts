/** What the bell and its panel say, in one place (frontend/STYLE.md: a string used in more than
 * one file is one exported constant). Story 20.2. */
export const PANEL_NAME = 'Notifications'
export const UNREAD_LABEL = 'Unread'
export const MARK_AS_READ = 'Mark as read'
export const MARK_ALL_AS_READ = 'Mark all as read'
export const NO_NOTIFICATIONS = 'No notifications yet.'
/** AC4: shown in a row whose item the reader cannot open, or which no longer exists. */
export const NO_LONGER_AVAILABLE = 'This is no longer available to you.'
export const RECENT_ACTIONS_HEADING = 'Your recent actions'
export const NO_RECENT_ACTIONS = 'Nothing yet. Changes you save appear here.'

/** AC3: the badge shows the count up to here, and `BADGE_OVERFLOW_LABEL` above it. */
export const BADGE_CAP = 99
export const BADGE_OVERFLOW_LABEL = `${BADGE_CAP}+`

/** The number on the bell for `count` unread, or null at 0, when there is no badge. */
export function badgeText(count: number): string | null {
  if (count <= 0) return null
  return count > BADGE_CAP ? BADGE_OVERFLOW_LABEL : String(count)
}

/** The bell's accessible name: it keeps starting with the panel's name. */
export function bellLabel(count: number): string {
  return count > 0 ? `${PANEL_NAME}, ${count} unread` : PANEL_NAME
}

/** Values of `TargetKind` (backend/app/notifications/targets.py): the pages a notification opens. */
export const TARGET_KINDS = {
  EVENT: 'event',
  BOOKING_REQUEST: 'booking_request',
  EQUIPMENT_REQUESTS: 'equipment_requests',
  SAFETY_CHECK: 'safety_check',
  REGISTRATIONS: 'registrations',
  UNASSIGNED_EVENTS: 'unassigned_events',
  CHANGE_REQUEST_QUEUE: 'change_request_queue',
} as const
