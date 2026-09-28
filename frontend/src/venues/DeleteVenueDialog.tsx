import { useState } from 'react'
import { ApiError, formatApiError } from '../api/client'
import { deleteVenue, type VenueSummary } from '../api/venues'
import { ConfirmDialog } from '../components/ConfirmDialog'

export interface DeleteVenueDialogProps {
  venue: Pick<VenueSummary, 'id' | 'name'>
  onDeleted: () => void
  onCancel: () => void
  /** The venue had already been deleted elsewhere. The dialog stays open to say so, and the page
   *  reloads what it lists. */
  onAlreadyGone: () => void
}

/**
 * Story 8.1 AC12 (f8.1.1): Venue Staff delete a venue from its catalogue card, after confirming
 * (delete itself: team decision, 17 Sep 2026). A refusal, such as a venue with bookings or one
 * already deleted, is shown in the dialog with the backend's reason, and nothing is removed.
 */
export function DeleteVenueDialog({
  venue,
  onDeleted,
  onCancel,
  onAlreadyGone,
}: DeleteVenueDialogProps) {
  const [isDeleting, setIsDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function confirmDelete() {
    setIsDeleting(true)
    setError(null)
    try {
      await deleteVenue(venue.id, venue.name)
      onDeleted()
    } catch (err) {
      setError(formatApiError(err))
      if (err instanceof ApiError && err.code === 'VENUE_NOT_FOUND') onAlreadyGone()
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <ConfirmDialog
      title={`Delete ${venue.name}?`}
      confirmLabel="Delete venue"
      isBusy={isDeleting}
      error={error}
      onConfirm={confirmDelete}
      onCancel={onCancel}
    >
      <p>
        This removes the venue with its facilities, layouts and accessibility details. It cannot be
        undone.
      </p>
      <p className="muted">
        A venue with bookings cannot be deleted. Withdraw it from service instead.
      </p>
    </ConfirmDialog>
  )
}
