import { useState, type KeyboardEvent } from 'react'
import { FilterPills } from '../components/FilterPills'
import { Icon } from '../components/Icon'
import { useNotifications, type AppNotification } from './notificationContext'

type Filter = 'all' | 'important'

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

/**
 * The notification centre's bell and panel (team decision, 17 Sep 2026): every change the user
 * made this session, with the important ones (failures, deletions) easy to pick out.
 */
export function NotificationBell() {
  const { notifications, unreadCount, markAllRead } = useNotifications()
  const [isOpen, setIsOpen] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const importantCount = notifications.filter((item) => item.importance === 'important').length
  const shown =
    filter === 'all'
      ? notifications
      : notifications.filter((item) => item.importance === 'important')

  function togglePanel() {
    if (isOpen) markAllRead()
    setIsOpen(!isOpen)
  }

  function closePanel() {
    markAllRead()
    setIsOpen(false)
  }

  function handlePanelKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape') closePanel()
  }

  return (
    <div className="notification-bell">
      <button
        type="button"
        className="icon-button"
        aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : 'Notifications'}
        aria-expanded={isOpen}
        title="Notifications"
        onClick={togglePanel}
      >
        <Icon name="bell" />
        {unreadCount > 0 && (
          <span className="notification-count" aria-hidden="true">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <>
          <div className="notification-backdrop" onClick={closePanel} />
          <section
            className="notification-panel"
            aria-label="Notifications"
            onKeyDown={handlePanelKeyDown}
          >
            <header className="notification-panel-header">
              <h2 className="notification-panel-title">Notifications</h2>
              <FilterPills
                options={[
                  { key: 'all', label: `All (${notifications.length})` },
                  { key: 'important', label: `Important (${importantCount})` },
                ]}
                value={filter}
                onChange={setFilter}
              />
            </header>
            {shown.length === 0 ? (
              <p className="notification-empty">
                {filter === 'all'
                  ? 'Nothing yet. Changes you save appear here.'
                  : 'Nothing important right now.'}
              </p>
            ) : (
              <ul className="notification-list">
                {shown.map((item) => (
                  <li key={item.id} className={`notification-item ${toneOf(item)}`}>
                    <span className="notification-dot" aria-hidden="true" />
                    <div>
                      <p className="notification-title">
                        {item.title}
                        {!item.isRead && <span className="visually-hidden"> (new)</span>}
                      </p>
                      <p className="notification-message">{item.message}</p>
                      <p className="notification-age">{describeAge(item.createdAt)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  )
}
