import { useId, useLayoutEffect, useRef, useState } from 'react'
import { Icon } from './Icon'
import { placeErrorToast, removeErrorToast, useErrorToastOffset } from './toastStack'

export interface ErrorToastProps {
  message: string
  /** The message's id, so a field can point at it with `aria-describedby`. */
  id?: string
  /** Called when the toast's close button is pressed. A page whose check can fail twice in a row
   *  with the same message clears its error here, so the next failure shows again. */
  onDismiss?: () => void
}

/**
 * An error, shown as a toast in the bottom-right corner of the screen until its close button is
 * pressed or the error is cleared: it may still hold, so it never closes by itself. It is rendered
 * where the error belongs, so it stays inside its dialog or section for `getByRole('alert')`;
 * `.error-toast` lifts it out to the corner, and several stack there rather than cover each other.
 * A new message shows it again.
 */
export function ErrorToast(props: ErrorToastProps) {
  return <ShownErrorToast key={props.message} {...props} />
}

function ShownErrorToast({ message, id, onDismiss }: ErrorToastProps) {
  const [isOpen, setIsOpen] = useState(true)

  function handleDismiss() {
    setIsOpen(false)
    onDismiss?.()
  }

  if (!isOpen) return null

  return <StackedToast message={message} id={id} onDismiss={handleDismiss} />
}

function StackedToast({
  message,
  id,
  onDismiss,
}: {
  message: string
  id?: string
  onDismiss: () => void
}) {
  const stackId = useId()
  const toast = useRef<HTMLDivElement>(null)
  const offset = useErrorToastOffset(stackId)

  useLayoutEffect(() => {
    const element = toast.current
    if (!element) return
    placeErrorToast(stackId, element.offsetHeight)
    const observer = new ResizeObserver(() => placeErrorToast(stackId, element.offsetHeight))
    observer.observe(element)
    return () => {
      observer.disconnect()
      removeErrorToast(stackId)
    }
  }, [stackId])

  return (
    <div
      ref={toast}
      role="alert"
      className="toast is-failure error-toast"
      style={{ bottom: `calc(1rem + ${offset}px)` }}
    >
      <p id={id} className="error-toast-message">
        {message}
      </p>
      <button type="button" className="icon-button" aria-label="Dismiss" onClick={onDismiss}>
        <Icon name="close" size={16} />
      </button>
    </div>
  )
}
