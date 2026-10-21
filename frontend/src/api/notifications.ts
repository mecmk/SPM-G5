import { api } from './client'

/** Mirrors `NotificationTargetOut` (backend/app/notifications/schemas.py): where opening a
 * notification goes for its reader. `kind` is one of `TARGET_KINDS` (src/notifications/
 * notificationText.ts), or a kind this build does not know; `id` is null for a page that needs
 * none. */
export interface NotificationTarget {
  kind: string
  id: string | null
}

/** Mirrors `NotificationOut`: story 20.2, one notification as its recipient reads it. `read_at` is
 * null while unread; `target` is null when the reader has no page for it, cannot open its item, or
 * the item is gone (AC4). */
export interface ServerNotification {
  id: string
  notification_type: string
  title: string
  message: string
  event_id: string | null
  related_entity_type: string | null
  related_entity_id: string | null
  created_at: string
  read_at: string | null
  target: NotificationTarget | null
}

/** The user's newest notifications, newest first (the backend returns at most 50). */
export function listNotifications(): Promise<ServerNotification[]> {
  return api<ServerNotification[]>('/notifications')
}

/** Mirrors `UnreadCountOut`: how many notifications the user has not read, all of them. */
export interface UnreadCountOut {
  count: number
}

/** How many notifications the user has not read: every unread row, not only the 50 the list holds. */
export async function fetchUnreadCount(): Promise<number> {
  const { count } = await api<UnreadCountOut>('/notifications/unread-count')
  return count
}

/** Mark one notification read. `notify: false`: marking read is not a save the user made, so it
 * adds no toast and no entry to the log of their own actions. */
export function markNotificationRead(notificationId: string): Promise<ServerNotification> {
  return api<ServerNotification>(`/notifications/${encodeURIComponent(notificationId)}`, {
    method: 'PATCH',
    body: { is_read: true },
    notify: false,
  })
}

/** Mirrors `MarkedOut`: how many notifications a mark-all-read marked. */
export interface MarkedOut {
  marked: number
}

/** Mark read every unread notification up to and including `throughId`, the newest one the user
 * had loaded, so one that arrived after stays unread. Resolves to how many were marked. */
export async function markNotificationsReadThrough(throughId: string): Promise<number> {
  const { marked } = await api<MarkedOut>('/notifications', {
    method: 'PATCH',
    body: { is_read: true, through_id: throughId },
    notify: false,
  })
  return marked
}
