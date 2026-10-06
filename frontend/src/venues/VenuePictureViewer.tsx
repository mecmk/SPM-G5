import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { mediaUrl } from '../api/client'
import type { VenueImage } from '../api/venues'

export interface VenuePictureViewerProps {
  venueName: string
  pictures: VenueImage[]
  /** The picture it opens on. */
  startIndex: number
  onClose: () => void
}

/**
 * Story 8.3 AC6 (bug f8.3.2): a venue's pictures in a pop-up carousel, opened from the gallery on
 * its record. Previous and Next, or the arrow keys, step through them, coming round at either
 * end. Close, Escape or a click outside closes it, and focus goes back to the picture that opened
 * it. Built on ConfirmDialog's pattern, with its dialog styles.
 */
export function VenuePictureViewer({
  venueName,
  pictures,
  startIndex,
  onClose,
}: VenuePictureViewerProps) {
  const [index, setIndex] = useState(startIndex)
  const closeButton = useRef<HTMLButtonElement>(null)
  const count = pictures.length
  const picture = pictures[index]

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeButton.current?.focus()
    return () => opener?.focus()
  }, [])

  function showPrevious() {
    setIndex((current) => (current - 1 + count) % count)
  }

  function showNext() {
    setIndex((current) => (current + 1) % count)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') onClose()
    else if (event.key === 'ArrowLeft') showPrevious()
    else if (event.key === 'ArrowRight') showNext()
  }

  if (picture === undefined) return null

  return (
    <>
      <div className="dialog-backdrop" onClick={onClose} />
      <div
        className="dialog picture-viewer"
        role="dialog"
        aria-modal="true"
        aria-label={`Pictures of ${venueName}`}
        onKeyDown={handleKeyDown}
      >
        <div className="picture-viewer-header">
          <p className="picture-viewer-count">
            {index + 1} of {count}
          </p>
          <button ref={closeButton} type="button" className="secondary" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="picture-viewer-stage">
          <button
            type="button"
            className="secondary"
            aria-label="Previous picture"
            disabled={count < 2}
            onClick={showPrevious}
          >
            <span aria-hidden="true">&larr;</span>
          </button>
          <img src={mediaUrl(picture.url) ?? undefined} alt={`Picture ${index + 1} of ${count}`} />
          <button
            type="button"
            className="secondary"
            aria-label="Next picture"
            disabled={count < 2}
            onClick={showNext}
          >
            <span aria-hidden="true">&rarr;</span>
          </button>
        </div>
      </div>
    </>
  )
}
