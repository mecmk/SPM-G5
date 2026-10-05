import { useState, type ChangeEvent, type DragEvent } from 'react'
import { Icon } from '../components/Icon'
import { ERROR_REGISTRY, type ErrorCode } from '../errors/registry'
import { VENUE_IMAGE_TYPES } from './venueForm'

/** One picture on the form, saved already or chosen and not uploaded yet, and where to show it. */
export interface PictureTile {
  key: string
  src: string
}

export interface VenuePicturesFieldProps {
  /** In the order they will be saved in: the venue's own, then those chosen here. */
  pictures: PictureTile[]
  /** Why the files chosen last were not all taken (story 8.3 AC7), or null. */
  problem: ErrorCode | null
  /** True while the form saves: the pictures being sent cannot change under it. */
  isDisabled: boolean
  onAdd: (files: File[]) => void
  onRemove: (key: string) => void
}

/**
 * Story 8.3 AC5 (bug f8.3.2): a venue's pictures on its form. Pictures are added by choosing files
 * or dragging them onto the area, previewed in their order - the first is the venue's cover (AC6)
 * - and each can be removed. Nothing is uploaded here: the page saves the pictures with the venue's
 * details. Built like the event form's cover picture (story 2.1 AC14), with the same
 * `.picture-drop` styles.
 */
export function VenuePicturesField({
  pictures,
  problem,
  isDisabled,
  onAdd,
  onRemove,
}: VenuePicturesFieldProps) {
  const [isDragging, setIsDragging] = useState(false)

  function handleInput(change: ChangeEvent<HTMLInputElement>) {
    onAdd(Array.from(change.target.files ?? []))
    // So choosing the same files again still counts as a change.
    change.target.value = ''
  }

  function handleDragOver(drag: DragEvent<HTMLDivElement>) {
    drag.preventDefault()
    if (!isDisabled) setIsDragging(true)
  }

  function handleDragLeave() {
    setIsDragging(false)
  }

  function handleDrop(drag: DragEvent<HTMLDivElement>) {
    drag.preventDefault()
    setIsDragging(false)
    // A disabled fieldset stops its buttons and file input, but not a drop onto this area.
    if (!isDisabled) onAdd(Array.from(drag.dataTransfer.files))
  }

  return (
    <fieldset className="card" disabled={isDisabled}>
      <legend>Pictures</legend>
      <p className="form-hint">
        Optional. Up to 10 JPEG, PNG or WebP pictures, each up to 5 MB. The first shows on the
        venue&rsquo;s card.
      </p>
      {pictures.length > 0 && (
        <ul className="picture-tiles">
          {pictures.map((picture, index) => (
            <li key={picture.key} className="picture-tile">
              <img src={picture.src} alt={`Picture ${index + 1} preview`} />
              <button
                type="button"
                className="secondary"
                aria-label={`Remove picture ${index + 1}`}
                onClick={() => onRemove(picture.key)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <div
        role="group"
        aria-label="Pictures drop area"
        className={isDragging ? 'picture-drop is-dragging' : 'picture-drop'}
        onDragEnter={handleDragOver}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <span className="picture-drop-icon" aria-hidden="true">
          <Icon name="image" size={32} />
        </span>
        <p className="picture-drop-hint">
          {isDragging ? 'Drop the pictures here' : 'Drag pictures here, or'}
        </p>
        <div className="picture-drop-actions">
          <label className="button secondary">
            {pictures.length > 0 ? 'Add more pictures' : 'Choose pictures'}
            <input
              type="file"
              multiple
              className="visually-hidden"
              accept={VENUE_IMAGE_TYPES.join(',')}
              aria-label="Choose pictures"
              onChange={handleInput}
            />
          </label>
        </div>
      </div>
      {problem && <span className="field-error">{ERROR_REGISTRY[problem].message}</span>}
    </fieldset>
  )
}
