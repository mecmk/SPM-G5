import { useId, useState, type ChangeEvent } from 'react'
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

/** Story 8.6 AC5/AC7: how many characters `text` has, counted as the server counts them: an emoji
 *  is one, where a browser's own limit (`maxLength`) counts two. */
function countCharacters(text: string): number {
  return [...text].length
}

/** Story 8.6 AC5/AC7: a box's new text kept to `max` characters, counted as the server counts
 *  them. A full box takes no more, and text pasted past the limit is cut there. */
function keepWithin(previous: string, next: string, max: number): string {
  if (countCharacters(next) <= max) return next
  if (countCharacters(previous) >= max) return previous
  return [...next].slice(0, max).join('')
}

/**
 * Story 8.6 AC2/AC3: Venue Staff add a room layout, or change a layout's name or description. The
 * server judges both (AC5-AC7) and refuses a name another layout has (AC6, AC10); its sentence is
 * shown here and nothing typed is lost. AC5/AC7: both boxes are marked required, stop taking text
 * at their limits, and show under them how much of the limit is used, counting characters as the
 * server does. AC12: a layout deleted while this dialog was open is refused for good, so only
 * Close is left.
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

  function changeName(event: ChangeEvent<HTMLInputElement>) {
    const name = keepWithin(input.name, event.target.value, ROOM_LAYOUT_NAME_MAX_LENGTH)
    setInput({ ...input, name })
  }

  function changeDescription(event: ChangeEvent<HTMLTextAreaElement>) {
    const max = ROOM_LAYOUT_DESCRIPTION_MAX_LENGTH
    setInput({ ...input, description: keepWithin(input.description, event.target.value, max) })
  }

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
          aria-describedby={nameCountId}
          value={input.name}
          onChange={changeName}
        />
      </label>
      <span id={nameCountId} className="small muted">
        {countCharacters(input.name)} of {ROOM_LAYOUT_NAME_MAX_LENGTH} characters
      </span>
      <label>
        <span>
          Description <RequiredMark />
        </span>
        <textarea
          rows={3}
          aria-required="true"
          aria-describedby={descriptionCountId}
          value={input.description}
          onChange={changeDescription}
        />
      </label>
      <span id={descriptionCountId} className="small muted">
        {countCharacters(input.description)} of {ROOM_LAYOUT_DESCRIPTION_MAX_LENGTH} characters
      </span>
    </ConfirmDialog>
  )
}
