import { useState } from 'react'
import { ApiError, formatApiError } from '../api/client'
import { deleteRoomLayout, type RoomLayout } from '../api/venues'
import { ConfirmDialog } from '../components/ConfirmDialog'

export interface DeleteRoomLayoutDialogProps {
  layout: RoomLayout
  onDeleted: () => void
  onCancel: () => void
  /** The layout had been deleted meanwhile. The dialog stays open to say so, and the page reads
   *  its list again. */
  onGone: () => void
}

/**
 * Story 8.6 AC4: Venue Staff delete a room layout, after confirming. AC8: one that venues, venue
 * requirements or booking requests use is refused, and the backend's sentence says which of them
 * use it; nothing is removed. AC12: one deleted elsewhere meanwhile is refused for good, so only
 * Close is left.
 */
export function DeleteRoomLayoutDialog({
  layout,
  onDeleted,
  onCancel,
  onGone,
}: DeleteRoomLayoutDialogProps) {
  const [isDeleting, setIsDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isGone, setIsGone] = useState(false)

  async function confirmDelete() {
    setIsDeleting(true)
    setError(null)
    try {
      await deleteRoomLayout(layout.code, layout.name)
      onDeleted()
    } catch (err) {
      setError(formatApiError(err))
      if (err instanceof ApiError && err.code === 'ROOM_LAYOUT_NOT_FOUND') {
        setIsGone(true)
        onGone()
      }
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <ConfirmDialog
      title={`Delete ${layout.name}?`}
      confirmLabel="Delete layout"
      isBusy={isDeleting}
      error={error}
      onConfirm={confirmDelete}
      onCancel={onCancel}
      canConfirm={!isGone}
      cancelLabel={isGone ? 'Close' : 'Cancel'}
    >
      <p>
        Venue records, event requests and the catalogue’s filter will no longer offer this layout.
        It cannot be undone.
      </p>
      <p className="muted">
        A layout that venues, venue requirements or booking requests use cannot be deleted. You can
        still rename it.
      </p>
    </ConfirmDialog>
  )
}
