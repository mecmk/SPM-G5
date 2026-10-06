import { useState, type ChangeEvent, type DragEvent } from 'react'
import { Icon } from '../components/Icon'
import { ERROR_REGISTRY } from '../errors/registry'
import { VENUE_IMAGE_TYPES, type RefusedPicture } from './venueForm'

/** One picture on the form, saved already or chosen and not uploaded yet, and where to show it. */
export interface PictureTile {
  key: string
  src: string
}

export interface VenuePicturesFieldProps {
  /** In the order they will be saved in; the first is the venue's cover. */
  pictures: PictureTile[]
  /** The files chosen last that were not taken, each with its reason (story 8.3 AC7). */
  refused: RefusedPicture[]
  /** True while the form saves: the pictures being sent cannot change under it. */
  isDisabled: boolean
  onAdd: (files: File[]) => void
  onRemove: (key: string) => void
  /** Story 8.3 AC5: put the picture `key` at `index`; the ones between move up or down one. */
  onMove: (key: string, index: number) => void
}

/** A drag that carries files from outside the page, rather than one of the pictures here. */
function isFileDrag(drag: DragEvent<HTMLElement>): boolean {
  return drag.dataTransfer.types.includes('Files')
}

/**
 * Story 8.3 AC5 (bug f8.3.2): a venue's pictures on its form. Pictures are added by choosing files
 * or dragging them onto the area, previewed in their order, and each can be moved earlier or
 * later, dragged onto another's place, or removed. The first is the venue's cover (AC6). AC7:
 * each chosen file is checked on its own, and every one refused is named with its reason.
 * Nothing is uploaded here: the page saves the pictures with the venue's details. Built like the
 * event form's cover picture (story 2.1 AC14), with the same `.picture-drop` styles.
 */
export function VenuePicturesField({
  pictures,
  refused,
  isDisabled,
  onAdd,
  onRemove,
  onMove,
}: VenuePicturesFieldProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [draggedKey, setDraggedKey] = useState<string | null>(null)

  function handleInput(change: ChangeEvent<HTMLInputElement>) {
    onAdd(Array.from(change.target.files ?? []))
    // So choosing the same files again still counts as a change.
    change.target.value = ''
  }

  function handleDragOver(drag: DragEvent<HTMLDivElement>) {
    if (!isFileDrag(drag)) return
    drag.preventDefault()
    if (!isDisabled) setIsDragging(true)
  }

  function handleDragLeave() {
    setIsDragging(false)
  }

  function handleDrop(drag: DragEvent<HTMLDivElement>) {
    if (!isFileDrag(drag)) return
    drag.preventDefault()
    setIsDragging(false)
    // A disabled fieldset stops its buttons and file input, but not a drop onto this area.
    if (!isDisabled) onAdd(Array.from(drag.dataTransfer.files))
  }

  function handleTileDragStart(drag: DragEvent<HTMLLIElement>) {
    const key = drag.currentTarget.dataset.key ?? null
    drag.dataTransfer.effectAllowed = 'move'
    // Some browsers only start a drag that carries data.
    drag.dataTransfer.setData('text/plain', key ?? '')
    setDraggedKey(key)
  }

  function handleTileDragOver(drag: DragEvent<HTMLLIElement>) {
    if (draggedKey === null) return
    drag.preventDefault()
    drag.dataTransfer.dropEffect = 'move'
  }

  function handleTileDrop(drag: DragEvent<HTMLLIElement>) {
    if (draggedKey === null) return
    drag.preventDefault()
    onMove(draggedKey, Number(drag.currentTarget.dataset.index))
    setDraggedKey(null)
  }

  function handleTileDragEnd() {
    setDraggedKey(null)
  }

  return (
    <fieldset className="card" disabled={isDisabled}>
      <legend>Pictures</legend>
      <p className="form-hint">
        Optional. Up to 10 JPEG, PNG or WebP pictures, each up to 5 MB. Drag a picture, or use its
        arrows, to change the order: the first shows on the venue&rsquo;s card.
      </p>
      {pictures.length > 0 && (
        <ul className="picture-tiles" aria-label="Pictures to save">
          {pictures.map((picture, index) => (
            <li
              key={picture.key}
              className={picture.key === draggedKey ? 'picture-tile is-dragged' : 'picture-tile'}
              data-key={picture.key}
              data-index={index}
              draggable={!isDisabled}
              onDragStart={handleTileDragStart}
              onDragOver={handleTileDragOver}
              onDrop={handleTileDrop}
              onDragEnd={handleTileDragEnd}
            >
              <div className="picture-tile-frame">
                <img src={picture.src} alt={`Picture ${index + 1} preview`} draggable={false} />
                {index === 0 && <span className="picture-tile-cover">Cover</span>}
              </div>
              <div className="picture-tile-actions">
                <button
                  type="button"
                  className="secondary"
                  aria-label={`Move picture ${index + 1} earlier`}
                  disabled={index === 0}
                  onClick={() => onMove(picture.key, index - 1)}
                >
                  <span aria-hidden="true">&larr;</span>
                </button>
                <button
                  type="button"
                  className="secondary"
                  aria-label={`Move picture ${index + 1} later`}
                  disabled={index === pictures.length - 1}
                  onClick={() => onMove(picture.key, index + 1)}
                >
                  <span aria-hidden="true">&rarr;</span>
                </button>
                <button
                  type="button"
                  className="secondary"
                  aria-label={`Remove picture ${index + 1}`}
                  onClick={() => onRemove(picture.key)}
                >
                  Remove
                </button>
              </div>
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
      <div className="field-error picture-refusals" aria-live="polite">
        {refused.length > 0 && (
          <>
            <p>{ERROR_REGISTRY.VENUE_PICTURES_NOT_ADDED.message}</p>
            <ul>
              {refused.map((picture, index) => (
                <li key={`${index}-${picture.name}`}>
                  {picture.name}: {ERROR_REGISTRY[picture.problem].message}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </fieldset>
  )
}
