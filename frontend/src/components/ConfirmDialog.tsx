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
  /** The error message's id, so a field in `children` can point at it with `aria-describedby`
   *  (story 19.2 AC4: the rejection reason). */
  errorId?: string
  /** The button that closes the dialog without acting. Story 6.2 names it "Keep event", so it is
   *  never read as the "Cancel event" it stands beside. */
  dismissLabel?: string
}

/**
 * Story 8.3 - a modal that asks before a consequential action. Escape or the dismiss button
 * (Cancel, unless `dismissLabel` names it) closes it; focus starts on that button, so a stray
 * Enter never confirms.
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
  errorId,
  dismissLabel = 'Cancel',
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
            <p id={errorId} role="alert" className="error">
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
            {dismissLabel}
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
