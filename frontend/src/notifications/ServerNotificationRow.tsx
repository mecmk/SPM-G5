import type { ServerNotification } from '../api/notifications'
import { formatDateTime } from '../shared/format'
import { MARK_AS_READ, NO_LONGER_AVAILABLE, UNREAD_LABEL } from './notificationText'

interface ServerNotificationRowProps {
  notification: ServerNotification
  /** AC4: the item cannot be opened, so the row says so. */
  isUnavailable: boolean
  /** The message to show when the last attempt to open or mark this row failed. */
  error: string | undefined
  onOpen: (notification: ServerNotification) => void
  onMarkAsRead: (notification: ServerNotification) => void
}

/**
 * Story 20.2 AC1: one server notification in the panel - its title (a button that opens the item),
 * message and time, the word "Unread" and a "Mark as read" button while it is unread. The two
 * buttons sit side by side, never one inside the other.
 */
export function ServerNotificationRow({
  notification,
  isUnavailable,
  error,
  onOpen,
  onMarkAsRead,
}: ServerNotificationRowProps) {
  const isUnread = notification.read_at === null

  function handleOpen() {
    onOpen(notification)
  }

  function handleMarkAsRead() {
    onMarkAsRead(notification)
  }

  return (
    <li className={isUnread ? 'notification-item is-unread' : 'notification-item'}>
      <div className="notification-body">
        <button type="button" className="notification-open" onClick={handleOpen}>
          {notification.title}
        </button>
        {isUnread && <span className="notification-unread-tag">{UNREAD_LABEL}</span>}
        <p className="notification-message">{notification.message}</p>
        <p className="notification-time">{formatDateTime(notification.created_at)}</p>
        {isUnavailable && <p className="notification-unavailable">{NO_LONGER_AVAILABLE}</p>}
        {error && (
          <p role="alert" className="error notification-error">
            {error}
          </p>
        )}
        {isUnread && (
          <button type="button" className="secondary button-sm" onClick={handleMarkAsRead}>
            {MARK_AS_READ}
          </button>
        )}
      </div>
    </li>
  )
}
