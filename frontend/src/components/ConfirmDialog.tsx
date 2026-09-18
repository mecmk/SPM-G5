import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react'

export interface ConfirmDialogProps {
  title: string
  children: ReactNode
  confirmLabel: string
  isBusy: boolean
  error: string | null
  onConfirm: () => void
  onCancel: () => void
}

/**
 * Story 8.3 - a modal that asks before a destructive action. Escape or Cancel closes it; focus
 * starts on Cancel, so a stray Enter never confirms.
 */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  isBusy,
  error,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId()
  const cancelButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    cancelButton.current?.focus()
  }, [])

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape' && !isBusy) onCancel()
  }

  return (
    <>
      <div className="dialog-backdrop" />
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={handleKeyDown}
      >
        <h2 id={titleId} className="dialog-title">
          {title}
        </h2>
        <div className="dialog-body">
          {children}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
        </div>
        <div className="dialog-actions">
          <button
            ref={cancelButton}
            type="button"
            className="secondary"
            disabled={isBusy}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button type="button" className="danger-solid" disabled={isBusy} onClick={onConfirm}>
            {isBusy && <span className="spinner button-spinner" aria-hidden="true" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </>
  )
}
