import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type MouseEvent,
  type PointerEvent,
} from 'react'
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

/** How far a mouse moves with its button down before it picks a picture up, so a click on a
 *  picture never moves it. */
const MOUSE_PICK_UP_PX = 4
/** How long a finger rests on a picture to pick it up, so a swipe across the pictures still
 *  scrolls the page, as on a phone's home screen. */
const TOUCH_HOLD_MS = 250
/** How far a finger may wander during that hold before it counts as a scroll instead. */
const TOUCH_SLOP_PX = 8
/** How much a picked-up picture grows, to show it is lifted off the others. */
const LIFTED_SCALE = 1.06
/** How a dropped picture settles into its place; the others glide with `.picture-tile`'s own. */
const SETTLE_TRANSITION = 'transform 220ms cubic-bezier(0.2, 0, 0, 1)'
/** When a settled picture's inline transition and pivot can go: just after it settles. */
const SETTLED_AFTER_MS = 260

/** A press on a picture, which may become a drag once it moves (mouse) or rests (touch). */
interface Press {
  key: string
  pointerId: number
  isTouch: boolean
  startX: number
  startY: number
  /** Where in the picture the pointer took hold, which stays under it while it is carried. */
  grabX: number
  grabY: number
  isLifted: boolean
  holdTimer: number | null
}

/** A drag that carries files from outside the page, rather than one of the pictures here. */
function isFileDrag(drag: DragEvent<HTMLElement>): boolean {
  return drag.dataTransfer.types.includes('Files')
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** Where each picture is on screen now, to glide from when the order changes. */
function positionsOf(tiles: Map<string, HTMLLIElement>): Map<string, DOMRect> {
  const positions = new Map<string, DOMRect>()
  tiles.forEach((tile, key) => positions.set(key, tile.getBoundingClientRect()))
  return positions
}

/**
 * Story 8.3 AC5 (bug f8.3.2): a venue's pictures on its form. Pictures are added by choosing files
 * or dragging them onto the area, and previewed in their order; the first is the venue's cover
 * (AC6). A picture is arranged by picking it up and carrying it, the others moving aside as it
 * passes, like apps on a phone's home screen; or with its arrows, which also serve the keyboard.
 * Its × removes it. AC7: each chosen file is checked on its own, and every one refused is named
 * with its reason. Nothing is uploaded here: the page saves the pictures with the venue's details.
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
  const [liftedKey, setLiftedKey] = useState<string | null>(null)
  const list = useRef<HTMLUListElement>(null)
  const tiles = useRef(new Map<string, HTMLLIElement>())
  const press = useRef<Press | null>(null)
  /** Picks up the pressed picture when a finger has rested on it long enough. */
  const onHold = useRef<() => void>(() => {})
  const pointer = useRef({ x: 0, y: 0 })
  /** Where each picture was just before the order changed, if it has; read once, after it. */
  const before = useRef<Map<string, DOMRect> | null>(null)
  // The latest props, for the window listeners set up once below.
  const latest = useRef({ pictures, onMove })
  useEffect(() => {
    latest.current = { pictures, onMove }
  })

  /** Keep the carried picture under the pointer, wherever its place in the list now is. */
  function placeUnderPointer(tile: HTMLLIElement, held: Press) {
    const box = list.current?.getBoundingClientRect()
    if (box === undefined) return
    const x = pointer.current.x - held.grabX - (box.left + tile.offsetLeft)
    const y = pointer.current.y - held.grabY - (box.top + tile.offsetTop)
    tile.style.transform = `translate(${x}px, ${y}px) scale(${LIFTED_SCALE})`
  }

  // FLIP: after the order changes, each picture starts where it was and glides to its new place.
  useLayoutEffect(() => {
    const positions = before.current
    before.current = null
    const box = list.current?.getBoundingClientRect()
    if (positions === null || box === undefined) return
    const isAnimated = !prefersReducedMotion()
    tiles.current.forEach((tile, key) => {
      const held = press.current
      if (held !== null && held.isLifted && held.key === key) {
        placeUnderPointer(tile, held)
        return
      }
      const from = positions.get(key)
      if (from === undefined || !isAnimated) return
      const dx = from.left - (box.left + tile.offsetLeft)
      const dy = from.top - (box.top + tile.offsetTop)
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return
      tile.style.transition = 'none'
      tile.style.transform = `translate(${dx}px, ${dy}px)`
      // Lay the start position out before gliding away from it.
      void tile.offsetWidth
      tile.style.transition = ''
      tile.style.transform = ''
    })
  })

  // Carrying a picture: the pointer is followed on the window, so it can leave the list.
  useEffect(() => {
    const listElement = list.current

    function slotUnderPointer(): number | null {
      const box = listElement?.getBoundingClientRect()
      if (box === undefined) return null
      const x = pointer.current.x - box.left
      const y = pointer.current.y - box.top
      return latest.current.pictures.findIndex((picture) => {
        const tile = tiles.current.get(picture.key)
        return (
          tile !== undefined &&
          x >= tile.offsetLeft &&
          x < tile.offsetLeft + tile.offsetWidth &&
          y >= tile.offsetTop &&
          y < tile.offsetTop + tile.offsetHeight
        )
      })
    }

    function lift(held: Press) {
      held.isLifted = true
      held.holdTimer = null
      setLiftedKey(held.key)
      const tile = tiles.current.get(held.key)
      if (tile === undefined) return
      tile.style.transformOrigin = `${held.grabX}px ${held.grabY}px`
      placeUnderPointer(tile, held)
    }

    function letGo() {
      const held = press.current
      if (held?.holdTimer != null) window.clearTimeout(held.holdTimer)
      press.current = null
      return held
    }

    function handleHold() {
      const held = press.current
      if (held !== null && !held.isLifted) lift(held)
    }

    function handleMove(event: globalThis.PointerEvent) {
      const held = press.current
      if (held === null || event.pointerId !== held.pointerId) return
      pointer.current = { x: event.clientX, y: event.clientY }
      if (!held.isLifted) {
        const distance = Math.hypot(event.clientX - held.startX, event.clientY - held.startY)
        if (held.isTouch) {
          // Moving before the hold is up is a scroll, not a pick-up.
          if (distance > TOUCH_SLOP_PX) letGo()
          return
        }
        if (distance < MOUSE_PICK_UP_PX) return
        lift(held)
      }
      const tile = tiles.current.get(held.key)
      if (tile !== undefined) placeUnderPointer(tile, held)
      const slot = slotUnderPointer()
      const from = latest.current.pictures.findIndex((picture) => picture.key === held.key)
      if (slot === null || slot === -1 || slot === from) return
      before.current = positionsOf(tiles.current)
      latest.current.onMove(held.key, slot)
    }

    function handleEnd(event: globalThis.PointerEvent) {
      const held = press.current
      if (held === null || event.pointerId !== held.pointerId) return
      letGo()
      if (!held.isLifted) return
      setLiftedKey(null)
      const tile = tiles.current.get(held.key)
      if (tile === undefined) return
      // Settle from under the pointer into its place.
      tile.style.transition = prefersReducedMotion() ? 'none' : SETTLE_TRANSITION
      tile.style.transform = ''
      window.setTimeout(() => {
        tile.style.transition = ''
        tile.style.transformOrigin = ''
      }, SETTLED_AFTER_MS)
    }

    function preventScrollWhileCarrying(event: TouchEvent) {
      if (press.current?.isLifted) event.preventDefault()
    }

    onHold.current = handleHold
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleEnd)
    window.addEventListener('pointercancel', handleEnd)
    listElement?.addEventListener('touchmove', preventScrollWhileCarrying, { passive: false })
    return () => {
      letGo()
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleEnd)
      window.removeEventListener('pointercancel', handleEnd)
      listElement?.removeEventListener('touchmove', preventScrollWhileCarrying)
    }
  }, [])

  function handlePointerDown(event: PointerEvent<HTMLLIElement>) {
    if (isDisabled || press.current !== null || !event.isPrimary || event.button !== 0) return
    if (event.target instanceof Element && event.target.closest('button') !== null) return
    const key = event.currentTarget.dataset.key
    if (key === undefined) return
    const box = event.currentTarget.getBoundingClientRect()
    const isTouch = event.pointerType === 'touch'
    pointer.current = { x: event.clientX, y: event.clientY }
    press.current = {
      key,
      pointerId: event.pointerId,
      isTouch,
      startX: event.clientX,
      startY: event.clientY,
      grabX: event.clientX - box.left,
      grabY: event.clientY - box.top,
      isLifted: false,
      holdTimer: isTouch ? window.setTimeout(() => onHold.current(), TOUCH_HOLD_MS) : null,
    }
    // A mouse press would otherwise start selecting text.
    if (!isTouch) event.preventDefault()
  }

  /** A long press would otherwise open the phone's menu for the picture. */
  function handleContextMenu(event: MouseEvent<HTMLLIElement>) {
    if (press.current?.isTouch) event.preventDefault()
  }

  /** The arrows and × move or remove a picture; the others glide into their new places. */
  function moveTile(key: string, index: number) {
    before.current = positionsOf(tiles.current)
    onMove(key, index)
  }

  function removeTile(key: string) {
    before.current = positionsOf(tiles.current)
    onRemove(key)
  }

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

  return (
    <fieldset className="card" disabled={isDisabled}>
      <legend>Pictures</legend>
      <p className="form-hint">
        Optional. Up to 10 JPEG, PNG or WebP pictures, each up to 5 MB. Drag a picture to change the
        order: the first shows on the venue&rsquo;s card.
      </p>
      <ul
        ref={list}
        className="picture-tiles"
        aria-label="Pictures to save"
        hidden={pictures.length === 0}
      >
        {pictures.map((picture, index) => (
          <li
            key={picture.key}
            ref={(tile) => {
              if (tile === null) return
              tiles.current.set(picture.key, tile)
              return () => {
                tiles.current.delete(picture.key)
              }
            }}
            className={picture.key === liftedKey ? 'picture-tile is-lifted' : 'picture-tile'}
            data-key={picture.key}
            onPointerDown={handlePointerDown}
            onContextMenu={handleContextMenu}
          >
            <div className="picture-tile-frame">
              <img src={picture.src} alt={`Picture ${index + 1} preview`} draggable={false} />
              {index === 0 && <span className="picture-tile-cover">Cover</span>}
              <button
                type="button"
                className="picture-tile-remove"
                aria-label={`Remove picture ${index + 1}`}
                onClick={() => removeTile(picture.key)}
              >
                <Icon name="close" size={14} />
              </button>
              <div className="picture-tile-moves">
                <button
                  type="button"
                  className="picture-tile-move"
                  aria-label={`Move picture ${index + 1} earlier`}
                  disabled={index === 0}
                  onClick={() => moveTile(picture.key, index - 1)}
                >
                  <Icon name="chevron-left" size={16} />
                </button>
                <button
                  type="button"
                  className="picture-tile-move"
                  aria-label={`Move picture ${index + 1} later`}
                  disabled={index === pictures.length - 1}
                  onClick={() => moveTile(picture.key, index + 1)}
                >
                  <Icon name="chevron-right" size={16} />
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>
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
