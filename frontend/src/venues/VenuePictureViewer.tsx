import {
  useEffect,
  useRef,
  useState,
  type AnimationEvent,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
} from 'react'
import { mediaUrl } from '../api/client'
import type { VenueImage } from '../api/venues'
import { Icon } from '../components/Icon'

export interface VenuePictureViewerProps {
  venueName: string
  pictures: VenueImage[]
  /** The picture it opens on. */
  startIndex: number
  onClose: () => void
}

type Direction = 'next' | 'previous'

/** The picture on show, the one sliding away (if any) and which way they move. */
interface Showing {
  index: number
  leaving: number | null
  direction: Direction
}

/** A finger or mouse dragging the picture sideways. */
interface Swipe {
  pointerId: number
  startX: number
  distance: number
}

/** How far a swipe must travel to change the picture; a shorter one springs back. */
const SWIPE_PX = 48
/** How far the pointer may move and still count as a click, which closes the viewer outside the
 *  picture. */
const CLICK_SLOP_PX = 6
/** The longest the closing fade takes, in case its end is never reported. */
const CLOSING_FALLBACK_MS = 400

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * Story 8.3 AC6 (bug f8.3.2): a venue's pictures in a pop-up carousel, opened from the gallery on
 * its record. Pictures slide in from the way the viewer is moving: by the side buttons, the arrow
 * keys, a swipe, or a thumbnail, coming round at either end. Close, Escape or a click on the dark
 * space around the picture fades it away. While it is open the page behind stays still, focus stays
 * inside it, and on closing focus goes back to the picture that opened it.
 */
export function VenuePictureViewer({
  venueName,
  pictures,
  startIndex,
  onClose,
}: VenuePictureViewerProps) {
  const [showing, setShowing] = useState<Showing>({
    index: startIndex,
    leaving: null,
    direction: 'next',
  })
  const [isClosing, setIsClosing] = useState(false)
  const viewer = useRef<HTMLDivElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const shownPicture = useRef<HTMLImageElement>(null)
  const thumbs = useRef<HTMLDivElement>(null)
  const swipe = useRef<Swipe | null>(null)
  /** The click that ends a swipe is not a click on the dark space. */
  const wasSwipe = useRef(false)
  const count = pictures.length
  const picture = pictures[showing.index]
  const leaving = showing.leaving === null ? undefined : pictures[showing.leaving]

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const pageOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButton.current?.focus()
    return () => {
      document.body.style.overflow = pageOverflow
      opener?.focus()
    }
  }, [])

  useEffect(() => {
    if (!isClosing) return
    const fallback = window.setTimeout(onClose, CLOSING_FALLBACK_MS)
    return () => window.clearTimeout(fallback)
  }, [isClosing, onClose])

  // Keep the current thumbnail in view when there are more than fit.
  useEffect(() => {
    const current = thumbs.current?.querySelector('[aria-current="true"]')
    current?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [showing.index])

  function show(index: number, direction: Direction) {
    // Without the slide nothing reports that the picture has arrived (`handleArrived`), so the
    // one going out is not kept for it.
    const isSliding = !prefersReducedMotion()
    setShowing((current) =>
      current.index === index
        ? current
        : { index, leaving: isSliding ? current.index : null, direction },
    )
  }

  function showPrevious() {
    show((showing.index - 1 + count) % count, 'previous')
  }

  function showNext() {
    show((showing.index + 1) % count, 'next')
  }

  function showPicture(index: number) {
    show(index, index > showing.index ? 'next' : 'previous')
  }

  function close() {
    if (prefersReducedMotion()) onClose()
    else setIsClosing(true)
  }

  function handleClosed(event: AnimationEvent<HTMLDivElement>) {
    if (isClosing && event.target === event.currentTarget) onClose()
  }

  /** The picture coming in has arrived, so the one going out can go. */
  function handleArrived() {
    setShowing((current) => (current.leaving === null ? current : { ...current, leaving: null }))
  }

  /** Tab and Shift+Tab go round the viewer's own controls, never out to the page behind. */
  function keepFocusInside(event: KeyboardEvent<HTMLDivElement>) {
    const controls = viewer.current?.querySelectorAll<HTMLElement>('button:not(:disabled)')
    if (controls === undefined || controls.length === 0) return
    const first = controls[0]
    const last = controls[controls.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') close()
    else if (event.key === 'ArrowLeft' && count > 1) showPrevious()
    else if (event.key === 'ArrowRight' && count > 1) showNext()
    else if (event.key === 'Tab') keepFocusInside(event)
  }

  /** A click on the dark space, not the picture or a control, closes the viewer. */
  function handleClick(event: MouseEvent<HTMLDivElement>) {
    if (wasSwipe.current) {
      wasSwipe.current = false
      return
    }
    const isOnContent =
      event.target instanceof Element &&
      event.target.closest('button, img, [role="group"]') !== null
    if (!isOnContent) close()
  }

  function handleSwipeStart(event: PointerEvent<HTMLDivElement>) {
    wasSwipe.current = false
    if (!event.isPrimary || event.button !== 0 || count < 2) return
    if (event.target instanceof Element && event.target.closest('button') !== null) return
    swipe.current = { pointerId: event.pointerId, startX: event.clientX, distance: 0 }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  /** The picture follows the finger or mouse sideways while it is dragged. */
  function handleSwipeMove(event: PointerEvent<HTMLDivElement>) {
    const current = swipe.current
    if (current === null || current.pointerId !== event.pointerId) return
    current.distance = event.clientX - current.startX
    const image = shownPicture.current
    if (image === null) return
    image.style.transition = 'none'
    image.style.transform = `translateX(${current.distance}px)`
  }

  function handleSwipeEnd(event: PointerEvent<HTMLDivElement>) {
    const current = swipe.current
    if (current === null || current.pointerId !== event.pointerId) return
    swipe.current = null
    wasSwipe.current = Math.abs(current.distance) > CLICK_SLOP_PX
    if (Math.abs(current.distance) > SWIPE_PX) {
      // The picture slides on from where the swipe left it.
      if (current.distance < 0) showNext()
      else showPrevious()
      return
    }
    const image = shownPicture.current
    if (image === null) return
    image.style.transition = ''
    image.style.transform = ''
  }

  if (picture === undefined) return null

  return (
    <div
      ref={viewer}
      className={isClosing ? 'picture-viewer is-closing' : 'picture-viewer'}
      role="dialog"
      aria-modal="true"
      aria-label={`Pictures of ${venueName}`}
      onKeyDown={handleKeyDown}
      onClick={handleClick}
      onAnimationEnd={handleClosed}
    >
      <div className="picture-viewer-top">
        <p className="picture-viewer-count">
          {showing.index + 1} / {count}
        </p>
        <button
          ref={closeButton}
          type="button"
          className="picture-viewer-close"
          aria-label="Close"
          onClick={close}
        >
          <Icon name="close" size={20} />
        </button>
      </div>
      <div
        className="picture-viewer-stage"
        onPointerDown={handleSwipeStart}
        onPointerMove={handleSwipeMove}
        onPointerUp={handleSwipeEnd}
        onPointerCancel={handleSwipeEnd}
      >
        {leaving !== undefined && (
          <img
            key={leaving.id}
            className={`picture-viewer-picture is-leaving-${showing.direction}`}
            src={mediaUrl(leaving.url) ?? undefined}
            alt=""
            aria-hidden="true"
            draggable={false}
          />
        )}
        <img
          key={picture.id}
          ref={shownPicture}
          className={
            leaving === undefined
              ? 'picture-viewer-picture'
              : `picture-viewer-picture is-entering-${showing.direction}`
          }
          src={mediaUrl(picture.url) ?? undefined}
          alt={`Picture ${showing.index + 1} of ${count}`}
          draggable={false}
          onAnimationEnd={handleArrived}
        />
        {count > 1 && (
          <>
            <button
              type="button"
              className="picture-viewer-nav is-previous"
              aria-label="Previous picture"
              onClick={showPrevious}
            >
              <Icon name="chevron-left" size={26} />
            </button>
            <button
              type="button"
              className="picture-viewer-nav is-next"
              aria-label="Next picture"
              onClick={showNext}
            >
              <Icon name="chevron-right" size={26} />
            </button>
          </>
        )}
      </div>
      {count > 1 && (
        <div ref={thumbs} className="picture-viewer-thumbs" role="group" aria-label="All pictures">
          {pictures.map((thumb, index) => (
            <button
              key={thumb.id}
              type="button"
              className="picture-viewer-thumb"
              aria-label={`Show picture ${index + 1}`}
              aria-current={index === showing.index ? 'true' : undefined}
              onClick={() => showPicture(index)}
            >
              <img src={mediaUrl(thumb.url) ?? undefined} alt="" draggable={false} />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
