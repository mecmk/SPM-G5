import { Icon } from '../components/Icon'
import { useNotifications } from './notificationContext'

/** Brief pop-ups for new notifications; the bell keeps the full list. */
export function ToastStack() {
  const { toasts, dismissToast } = useNotifications()
  if (toasts.length === 0) return null

  return (
    <div className="toast-stack">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={toast.isSuccess ? 'toast is-success' : 'toast is-failure'}
          role="status"
          aria-live="polite"
        >
          <div className="toast-body">
            <p className="toast-title">{toast.title}</p>
            <p className="toast-message">{toast.message}</p>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="Dismiss"
            onClick={() => dismissToast(toast.id)}
          >
            <Icon name="close" size={16} />
          </button>
        </div>
      ))}
    </div>
  )
}
