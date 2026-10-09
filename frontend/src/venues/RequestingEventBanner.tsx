import { useId } from 'react'
import { Link } from 'react-router'
import type { EventDetail, VenueRequirement } from '../api/events'
import { eventPath } from '../routes'
import { formatSchedule } from '../shared/format'
import { venueRequirementTerms } from '../shared/venueRequest'

/** Story 2.7 AC8: a requirement's name, or its place when a draft left it unnamed. */
function requirementName(event: EventDetail, requirement: VenueRequirement): string {
  return (
    requirement.name ?? `Venue requirement ${event.venue_requirements.indexOf(requirement) + 1}`
  )
}

/** Story 8.4 AC1: how many people the requirement must hold, its layout and its times. */
function describeRequirement(event: EventDetail, requirement: VenueRequirement): string {
  const terms = venueRequirementTerms(event, requirement)
  return [
    terms.capacity === null ? null : `${terms.capacity} people`,
    terms.layoutName,
    terms.startsAt && terms.endsAt ? formatSchedule(terms.startsAt, terms.endsAt) : null,
  ]
    .filter((fact) => fact !== null)
    .join(' · ')
}

interface RequirementChoiceProps {
  event: EventDetail
  requirement: VenueRequirement
  isSelected: boolean
  onSelect: (requirement: VenueRequirement) => void
}

/**
 * Story 8.4 AC1/AC3/AC7: one venue requirement to search for. Pressed while it is the one
 * selected; pressing it again restores its own filters, so it never disables itself. Named by the
 * requirement alone, with its facts as the description.
 */
function RequirementChoice({ event, requirement, isSelected, onSelect }: RequirementChoiceProps) {
  const nameId = useId()
  const factsId = useId()

  function select() {
    onSelect(requirement)
  }

  return (
    <button
      type="button"
      className="requirement-choice"
      aria-pressed={isSelected}
      aria-labelledby={nameId}
      aria-describedby={factsId}
      onClick={select}
    >
      <span id={nameId} className="requirement-choice-name">
        {requirementName(event, requirement)}
      </span>
      <span id={factsId} className="small muted">
        {describeRequirement(event, requirement)}
      </span>
    </button>
  )
}

/** Story 8.4 AC5: the event's one venue requirement, shown alone - there is nothing to choose. */
function RequirementSummary({
  event,
  requirement,
}: {
  event: EventDetail
  requirement: VenueRequirement
}) {
  return (
    <div className="requirement-summary">
      <span className="requirement-choice-name">{requirementName(event, requirement)}</span>
      <span className="small muted">{describeRequirement(event, requirement)}</span>
    </div>
  )
}

interface RequestingEventBannerProps {
  event: EventDetail
  /** Story 8.4: the requirement the page address selects, if it names one of the event's. */
  selectedRequirement: VenueRequirement | null
  /** Story 8.4 AC7: the filters are no longer the selected requirement's own. */
  hasChangedFilters: boolean
  onSelectRequirement: (requirement: VenueRequirement) => void
}

/**
 * f12.1.1 (story 12.1 AC15): on the catalogue opened from an event's Find a venue, names the event
 * the venues are being found for, and leads back to it.
 *
 * Story 8.4: it also lists the event's venue requirements, for anyone who may read the event
 * (AC10). With several, each is a choice that sets the filters from that requirement (AC3), the
 * selected one pressed (AC1); with one, it is shown alone, with nothing to switch between (AC5);
 * with "No venue requirements", none are listed (AC6). Once the filters are changed by hand, it
 * says how to restore the selected requirement's own (AC7).
 */
export function RequestingEventBanner({
  event,
  selectedRequirement,
  hasChangedFilters,
  onSelectRequirement,
}: RequestingEventBannerProps) {
  const requirementsId = useId()
  const requirements = event.venue_requirements
  const hasChoice = requirements.length > 1
  const facts = [
    event.starts_at && event.ends_at ? formatSchedule(event.starts_at, event.ends_at) : null,
    event.expected_attendance === null ? null : `${event.expected_attendance} attendees expected`,
  ].filter((fact) => fact !== null)

  return (
    <section className="card stack requesting-event" aria-labelledby="requesting-event-heading">
      <div className="card-heading">
        <h2 id="requesting-event-heading">Finding a venue for {event.name}</h2>
        <Link to={eventPath(event.id)} className="button secondary button-sm">
          Back to the event
        </Link>
      </div>
      {facts.length > 0 && <p className="small muted">{facts.join(' · ')}</p>}
      {requirements.length > 0 && (
        <div>
          <p id={requirementsId} className="eyebrow">
            {hasChoice ? 'Venue requirements' : 'Venue requirement'}
          </p>
          <ul className="requirement-choices" aria-labelledby={requirementsId}>
            {requirements.map((requirement) => (
              <li key={requirement.id}>
                {hasChoice ? (
                  <RequirementChoice
                    event={event}
                    requirement={requirement}
                    isSelected={requirement.id === selectedRequirement?.id}
                    onSelect={onSelectRequirement}
                  />
                ) : (
                  <RequirementSummary event={event} requirement={requirement} />
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {hasChoice && selectedRequirement !== null && hasChangedFilters && (
        <p className="small muted">
          Filters changed by hand. Select {requirementName(event, selectedRequirement)} again to
          restore its own filters.
        </p>
      )}
    </section>
  )
}
