import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { Icon } from './Icon'

/** Story 7.1: the page this card was reached from, so its back link can return there. */
export interface EventCardBackState {
  from: string
  fromLabel: string
}

export interface EventCardProps {
  title: string
  imageUrl: string | null
  details: ReactNode[]
  /** Story 7.1: when given, the whole card links to the event's details page. */
  to?: string
  /** Passed through to the link, so the details page knows where "back" goes. */
  state?: EventCardBackState
}

/**
 * Team decision, 17 Sep 2026: one card style for every list of events, a full-width row with a
 * square picture on the left. Story 4.1 is the first user in the real frontend: the square shows
 * `imageUrl` when the event has one and it loads, and a placeholder icon otherwise.
 */
export function EventCard({ title, imageUrl, details, to, state }: EventCardProps) {
  const [hasImageFailed, setHasImageFailed] = useState(false)

  function markImageFailed() {
    setHasImageFailed(true)
  }

  const body = (
    <>
      <span className="event-card-image" aria-hidden="true">
        {imageUrl !== null && !hasImageFailed ? (
          <img className="event-card-picture" src={imageUrl} alt="" onError={markImageFailed} />
        ) : (
          <Icon name="image" size={28} />
        )}
      </span>
      <div className="event-card-body">
        <h3 className="event-card-title">{title}</h3>
        <ul className="event-card-details">
          {details.map((detail, index) => (
            <li key={index}>{detail}</li>
          ))}
        </ul>
      </div>
    </>
  )

  return (
    <li className="event-card">
      {to ? (
        <Link to={to} state={state} className="event-card-link">
          {body}
        </Link>
      ) : (
        body
      )}
    </li>
  )
}

export function EventCardGrid({ children }: { children: ReactNode }) {
  return <ul className="event-grid">{children}</ul>
}
