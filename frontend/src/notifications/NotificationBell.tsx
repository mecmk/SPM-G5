import { useState, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router'
import { formatApiError } from '../api/client'
import type { ServerNotification } from '../api/notifications'
import { Icon } from '../components/Icon'
import { useNotifications, type AppNotification } from './notificationContext'
import { routeForTarget } from './notificationTarget'
import {
  MARK_ALL_AS_READ,
  NO_NOTIFICATIONS,
  NO_RECENT_ACTIONS,
  PANEL_NAME,
  RECENT_ACTIONS_HEADING,
  badgeText,
  bellLabel,
} from './notificationText'
import { ServerNotificationRow } from './ServerNotificationRow'
import { useServerNotifications } from './serverNotificationContext'

const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS

function describeAge(createdAt: Date): string {
  const ageMs = Date.now() - createdAt.getTime()
  if (ageMs < MINUTE_MS) return 'just now'
  if (ageMs < HOUR_MS) return `${Math.floor(ageMs / MINUTE_MS)} min ago`
  return createdAt.toLocaleTimeString('en-SG', { hour: '2-digit', minute: '2-digit' })
}

function toneOf(notification: AppNotification): string {
  if (!notification.isSuccess) return 'is-failure'
  return notification.importance === 'important' ? 'is-important' : 'is-routine'
}

interface NotificationBellProps {
  /** Which chrome this instance sits in, since the panel portals to `document.body` and can no
   * longer be positioned by a `.sidebar` / `.mobile-bar` ancestor selector. */
  placement: 'sidebar' | 'mobile'
  isSidebarCollapsed?: boolean
}

/**
 * The bell and its panel. Story 20.2: the bell's count is the server's, and the panel lists the
 * user's server notifications, newest first, each opened, or marked read, from its own row. Under
 * them, in the notification centre of the team decision of 17 Sep 2026, is the log of the user's
 * own recent actions, which is not counted.
 */
export function NotificationBell({ placement, isSidebarCollapsed = false }: NotificationBellProps) {
  const { notifications: recentActions } = useNotifications()
  const { notifications, unreadCount, listError, refresh, markRead, markAllRead } =
    useServerNotifications()
  const navigate = useNavigate()
  const [isOpen, setIsOpen] = useState(false)
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({})
  const [unavailableIds, setUnavailableIds] = useState<string[]>([])
  const [markAllError, setMarkAllError] = useState<string | null>(null)
  const badge = badgeText(unreadCount)
  const isMarkAllDisabled =
    notifications === null || notifications.length === 0 || unreadCount === 0
  const panelClassName = [
    'notification-panel',
    placement === 'mobile' && 'is-mobile',
    placement === 'sidebar' && isSidebarCollapsed && 'is-sidebar-collapsed',
  ]
    .filter(Boolean)
    .join(' ')

  /** Story 20.2 AC2: opening the panel reads the count and the list again. */
  function togglePanel() {
    if (!isOpen) refresh()
    setIsOpen(!isOpen)
  }

  function closePanel() {
    setIsOpen(false)
  }

  function handlePanelKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape') closePanel()
  }

  function showRowError(notificationId: string, message: string | null) {
    setRowErrors((current) => {
      const rest = { ...current }
      delete rest[notificationId]
      return message === null ? rest : { ...rest, [notificationId]: message }
    })
  }

  /** Mark one read, showing a refusal in its row. Resolves to whether it worked. */
  async function markRowRead(notification: ServerNotification): Promise<boolean> {
    showRowError(notification.id, null)
    try {
      await markRead(notification.id)
      return true
    } catch (err) {
      showRowError(notification.id, formatApiError(err))
      return false
    }
  }

  async function handleMarkAsRead(notification: ServerNotification) {
    await markRowRead(notification)
  }

  /** AC1: open the item, after the server has the notification read, so the page the user lands
   * on counts it read. AC4: with no page to open, say so in the row, read all the same. */
  async function handleOpen(notification: ServerNotification) {
    if (notification.read_at === null && !(await markRowRead(notification))) return
    const route = routeForTarget(notification.target)
    if (route === null) {
      setUnavailableIds((current) => [...current, notification.id])
      return
    }
    closePanel()
    navigate(route)
  }

  async function handleMarkAllAsRead() {
    setMarkAllError(null)
    try {
      await markAllRead()
    } catch (err) {
      setMarkAllError(formatApiError(err))
    }
  }

  return (
    <div className="notification-bell">
      <button
        type="button"
        className="icon-button"
        aria-label={bellLabel(unreadCount)}
        aria-expanded={isOpen}
        title={PANEL_NAME}
        onClick={togglePanel}
      >
        <Icon name="bell" />
        {badge !== null && (
          <span className="notification-count" aria-hidden="true">
            {badge}
          </span>
        )}
      </button>

      {isOpen &&
        createPortal(
          <>
            <div className="notification-backdrop" onClick={closePanel} />
            <section
              className={panelClassName}
              aria-label={PANEL_NAME}
              onKeyDown={handlePanelKeyDown}
            >
              <header className="notification-panel-header">
                <h2 className="notification-panel-title">{PANEL_NAME}</h2>
                <button
                  type="button"
                  className="secondary button-sm"
                  disabled={isMarkAllDisabled}
                  onClick={handleMarkAllAsRead}
                >
                  {MARK_ALL_AS_READ}
                </button>
              </header>
              <div className="notification-scroll">
                {markAllError && (
                  <p role="alert" className="error notification-error">
                    {markAllError}
                  </p>
                )}
                {listError && (
                  <p role="alert" className="error notification-error">
                    {listError}
                  </p>
                )}
                {notifications !== null && notifications.length === 0 && !listError && (
                  <p className="notification-empty">{NO_NOTIFICATIONS}</p>
                )}
                {notifications !== null && notifications.length > 0 && (
                  <ul className="notification-list">
                    {notifications.map((notification) => (
                      <ServerNotificationRow
                        key={notification.id}
                        notification={notification}
                        isUnavailable={unavailableIds.includes(notification.id)}
                        error={rowErrors[notification.id]}
                        onOpen={handleOpen}
                        onMarkAsRead={handleMarkAsRead}
                      />
                    ))}
                  </ul>
                )}

                <section className="notification-log" aria-labelledby="recent-actions-heading">
                  <h3 id="recent-actions-heading" className="notification-log-title">
                    {RECENT_ACTIONS_HEADING}
                  </h3>
                  {recentActions.length === 0 ? (
                    <p className="notification-empty">{NO_RECENT_ACTIONS}</p>
                  ) : (
                    <ul className="notification-list">
                      {recentActions.map((item) => (
                        <li key={item.id} className={`notification-item ${toneOf(item)}`}>
                          <span className="notification-dot" aria-hidden="true" />
                          <div>
                            <p className="notification-title">{item.title}</p>
                            <p className="notification-message">{item.message}</p>
                            <p className="notification-age">{describeAge(item.createdAt)}</p>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            </section>
          </>,
          document.body,
        )}
    </div>
  )
}
