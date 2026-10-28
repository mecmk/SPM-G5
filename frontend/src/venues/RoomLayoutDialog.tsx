import { useId, useState } from 'react'
import { ApiError, formatApiError } from '../api/client'
import {
  addRoomLayout,
  ROOM_LAYOUT_DESCRIPTION_MAX_LENGTH,
  ROOM_LAYOUT_NAME_MAX_LENGTH,
  updateRoomLayout,
  type RoomLayout,
  type RoomLayoutInput,
} from '../api/venues'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { RequiredMark } from '../components/RequiredMark'

export interface RoomLayoutDialogProps {
  /** The layout being changed, or null to add one. */
  layout: RoomLayout | null
  onSaved: (saved: RoomLayout) => void
  onCancel: () => void
  /** The layout had been deleted meanwhile. The dialog stays open to say so, and the page reads
   *  its list again. */
  onGone: () => void
}

/**
 * Story 8.6 AC2/AC3: Venue Staff add a room layout, or change a layout's name or description. The
 * server judges both (AC5-AC7) and refuses a name another layout has (AC6, AC10); its sentence is
 * shown here and nothing typed is lost. AC5/AC7: both boxes are marked required, stop taking text
 * at their limits, and show under them how much of the limit is used. AC12: a layout deleted
 * while this dialog was open is refused for good, so only Close is left.
 */
export function RoomLayoutDialog({ layout, onSaved, onCancel, onGone }: RoomLayoutDialogProps) {
  const [input, setInput] = useState<RoomLayoutInput>({
    name: layout?.name ?? '',
    description: layout?.description ?? '',
  })
  const nameCountId = useId()
  const descriptionCountId = useId()
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isGone, setIsGone] = useState(false)

  async function save() {
    setIsSaving(true)
    setError(null)
    try {
      onSaved(
        layout === null ? await addRoomLayout(input) : await updateRoomLayout(layout.code, input),
      )
    } catch (err) {
      setError(formatApiError(err))
      if (err instanceof ApiError && err.code === 'ROOM_LAYOUT_NOT_FOUND') {
        setIsGone(true)
        onGone()
      }
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <ConfirmDialog
      title={layout === null ? 'Add a room layout' : `Edit ${layout.name}`}
      confirmLabel={layout === null ? 'Add layout' : 'Save changes'}
      tone="primary"
      isBusy={isSaving}
      error={error}
      onConfirm={save}
      onCancel={onCancel}
      canConfirm={!isGone}
      cancelLabel={isGone ? 'Close' : 'Cancel'}
    >
      <label>
        <span>
          Name <RequiredMark />
        </span>
        <input
          type="text"
          aria-required="true"
          maxLength={ROOM_LAYOUT_NAME_MAX_LENGTH}
          aria-describedby={nameCountId}
          value={input.name}
          onChange={(e) => setInput({ ...input, name: e.target.value })}
        />
      </label>
      <span id={nameCountId} className="small muted">
        {input.name.length} of {ROOM_LAYOUT_NAME_MAX_LENGTH} characters
      </span>
      <label>
        <span>
          Description <RequiredMark />
        </span>
        <textarea
          rows={3}
          aria-required="true"
          maxLength={ROOM_LAYOUT_DESCRIPTION_MAX_LENGTH}
          aria-describedby={descriptionCountId}
          value={input.description}
          onChange={(e) => setInput({ ...input, description: e.target.value })}
        />
      </label>
      <span id={descriptionCountId} className="small muted">
        {input.description.length} of {ROOM_LAYOUT_DESCRIPTION_MAX_LENGTH} characters
      </span>
    </ConfirmDialog>
  )
}
