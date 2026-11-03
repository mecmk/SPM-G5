import { useState } from 'react'
import { mediaUrl } from '../api/client'
import { Icon } from '../components/Icon'

/**
 * The picture on a venue booking's card: the venue's first picture, as on its catalogue card.
 * Without one, or if it fails to load, the placeholder icon stays.
 */
export function BookingVenueThumb({ coverUrl }: { coverUrl: string | null }) {
  // The address that failed, not just that one did, so a new cover is tried rather than hidden.
  const [failedUrl, setFailedUrl] = useState<string | null>(null)

  return (
    <div className="booking-outcome-thumb" aria-hidden="true">
      {coverUrl !== null && coverUrl !== failedUrl ? (
        <img
          className="booking-outcome-thumb-image"
          src={mediaUrl(coverUrl) ?? undefined}
          alt=""
          onError={() => setFailedUrl(coverUrl)}
        />
      ) : (
        <Icon name="image" size={28} />
      )}
    </div>
  )
}
