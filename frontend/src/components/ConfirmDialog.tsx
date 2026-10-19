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
  /** Story 18.2: false once confirming can no longer succeed (a refusal that is final), so the
   * confirm button is not offered at all and the cancel button, labelled `cancelLabel`, is the
   * only one left. */
  canConfirm?: boolean
  /** The label of the button that closes the dialog without confirming. Story 6.2 names it
   *  "Keep event", so it is never read as the "Cancel event" it stands beside. */
  cancelLabel?: string
  /** The error message's id, so a field in `children` can point at it with `aria-describedby`
   *  (story 19.2 AC4: the rejection reason). */
  errorId?: string
  /** A class added to the dialog, so one dialog can be styled apart from the others (story 5.6:
   *  the Reassign dialog's 44px phone targets). */
  className?: string
}

/**
 * Story 8.3 - a modal that asks before a consequential action. Escape or Cancel closes it; focus
 * starts on Cancel, so a stray Enter never confirms. Story 18.2: focus goes back to Cancel whenever
 * it has fallen out of the dialog - the confirm button it was on is disabled while busy, or no
 * longer offered after a final refusal - so Escape still closes it.
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
  canConfirm = true,
  cancelLabel = 'Cancel',
  errorId,
  className,
}: ConfirmDialogProps) {
  const titleId = useId()
  const dialog = useRef<HTMLDivElement>(null)
  const cancelButton = useRef<HTMLButtonElement>(null)

  // On opening, and whenever the confirm button stops being one focus can stay on. While busy,
  // Cancel is disabled too, so focus waits for the answer.
  useEffect(() => {
    if (isBusy || dialog.current?.contains(document.activeElement)) return
    cancelButton.current?.focus()
  }, [isBusy, canConfirm])

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape' && !isBusy) onCancel()
  }

  return (
    <>
      <div className="dialog-backdrop" />
      <div
        ref={dialog}
        className={className ? `dialog ${className}` : 'dialog'}
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
            {cancelLabel}
          </button>
          {canConfirm && (
            <button
              type="button"
              className={tone === 'primary' ? 'brand' : 'danger-solid'}
              disabled={isBusy}
              onClick={onConfirm}
            >
              {isBusy && <span className="spinner button-spinner" aria-hidden="true" />}
              {confirmLabel}
            </button>
          )}
        </div>
      </div>
    </>
  )
}
