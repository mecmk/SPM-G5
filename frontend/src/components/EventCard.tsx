import { useState, type MouseEvent, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
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
  /** Story 7.1: when given, the card opens this page: its title is the link, and so is the card. */
  to?: string
  /** Passed through to the link, so the page it opens knows where "back" goes. */
  state?: EventCardBackState
}

/** Anything a click on it is meant for, so the card does not also open. */
const INTERACTIVE_ELEMENTS =
  'a, button, input, select, textarea, label, summary, [role="button"], [role="link"]'

/**
 * Team decision, 17 Sep 2026: one card style for every list of events, a full-width row with a
 * square picture on the left. Story 4.1 is the first user in the real frontend: the square shows
 * `imageUrl` when the event has one and it loads, and a placeholder icon otherwise.
 *
 * Story 7.1 made a card open its event. The title is the one real link, so a keyboard user and a
 * screen reader get a single link named for the event, and it can be opened in a new tab. A click
 * anywhere else on the card opens it too, from a click handler rather than by stretching or
 * wrapping the link, so the text on the card can still be selected and anything interactive put
 * inside it (a button, another link) keeps its own click. The handler steps aside for those, for a
 * click with a modifier key, and whenever text has been selected.
 */
export function EventCard({ title, imageUrl, details, to, state }: EventCardProps) {
  const [hasImageFailed, setHasImageFailed] = useState(false)
  const navigate = useNavigate()

  function markImageFailed() {
    setHasImageFailed(true)
  }

  function handleCardClick(click: MouseEvent<HTMLLIElement>) {
    if (to === undefined || click.button !== 0) return
    if (click.metaKey || click.ctrlKey || click.shiftKey || click.altKey) return
    if (click.target instanceof Element) {
      const inner = click.target.closest(INTERACTIVE_ELEMENTS)
      if (inner !== null && click.currentTarget.contains(inner)) return
    }
    if (window.getSelection()?.isCollapsed === false) return
    navigate(to, { state })
  }

  return (
    <li
      className={to === undefined ? 'event-card' : 'event-card event-card-linked'}
      onClick={to === undefined ? undefined : handleCardClick}
    >
      <span className="event-card-image" aria-hidden="true">
        {imageUrl !== null && !hasImageFailed ? (
          <img className="event-card-picture" src={imageUrl} alt="" onError={markImageFailed} />
        ) : (
          <Icon name="image" size={28} />
        )}
      </span>
      <div className="event-card-body">
        <h3 className="event-card-title">
          {to === undefined ? (
            title
          ) : (
            <Link to={to} state={state}>
              {title}
            </Link>
          )}
        </h3>
        <ul className="event-card-details">
          {details.map((detail, index) => (
            <li key={index}>{detail}</li>
          ))}
        </ul>
      </div>
    </li>
  )
}

export function EventCardGrid({ children }: { children: ReactNode }) {
  return <ul className="event-grid">{children}</ul>
}
