import { createContext, useContext } from 'react'
import type { ServerNotification } from '../api/notifications'

export interface ServerNotificationContextValue {
  /** The newest notifications as the server last listed them (at most 50, newest first); null
   * until the first list arrives. */
  notifications: ServerNotification[] | null
  /** How many notifications are unread, from the server's own count - not the list's, which holds
   * 50 at most. Keeps its last value while a refetch runs or fails. */
  unreadCount: number
  /** The message to show in the panel when the latest list request failed, otherwise null. */
  listError: string | null
  /** Read the count and the list again. */
  refresh: () => void
  /** Mark one read on the server, then show it read and read the count again. Rejects with the
   * request's `ApiError`, leaving everything as it was. */
  markRead: (notificationId: string) => Promise<void>
  /** Mark read everything up to the newest notification of the list last loaded, then read the
   * count and the list again. Rejects with the request's `ApiError`. */
  markAllRead: () => Promise<void>
}

export const ServerNotificationContext = createContext<ServerNotificationContextValue | null>(null)

const MISSING_PROVIDER_MESSAGE =
  'useServerNotifications must be used inside <ServerNotificationProvider>.'

export function useServerNotifications(): ServerNotificationContextValue {
  const value = useContext(ServerNotificationContext)
  if (!value) throw new Error(MISSING_PROVIDER_MESSAGE)
  return value
}
