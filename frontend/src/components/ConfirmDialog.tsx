import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react'

export interface ConfirmDialogProps {
  title: string
  children: ReactNode
  confirmLabel: string
  isBusy: boolean
  error: string | null
  onConfirm: () => void
  onCancel: () => void
  /** Visual weight of the confirm button. Story 13.2 adds `primary` for a non-destructive
   * decision (approving a booking); `danger` (the default) is for actions that remove data. */
  tone?: 'danger' | 'primary'
}

/**
 * Story 8.3 - a modal that asks before a consequential action. Escape or Cancel closes it; focus
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
  tone = 'danger',
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
          <button
            type="button"
            className={tone === 'primary' ? 'brand' : 'danger-solid'}
            disabled={isBusy}
            onClick={onConfirm}
          >
            {isBusy && <span className="spinner button-spinner" aria-hidden="true" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </>
  )
}
