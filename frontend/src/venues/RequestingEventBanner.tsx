import { useId } from 'react'
import { Link } from 'react-router'
import type { BookingOutcome } from '../api/bookings'
import type { EventDetail, VenueRequirement } from '../api/events'
import { eventPath } from '../routes'
import { formatSchedule } from '../shared/format'
import {
  coveringBooking,
  isBooked,
  requirementName,
  venueRequirementTerms,
} from '../shared/venueRequest'

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

/** Story 12.5 AC2: "Needs a venue", "Requested: <venue>" while its request is pending, or
 *  "Booked: <venue>" once approved. */
function describeCoverage(covering: BookingOutcome | null): string {
  if (covering === null) return 'Needs a venue'
  return `${isBooked(covering) ? 'Booked' : 'Requested'}: ${covering.venue_name}`
}

/** One venue requirement as the banner lists it. */
interface ListedRequirement {
  requirement: VenueRequirement
  /** Story 12.5 AC2: its pending or approved request, null while it needs a venue - or undefined
   *  when the event's bookings are not known, and nothing is said either way. */
  covering: BookingOutcome | null | undefined
}

/**
 * Story 12.5 (decided 10 Oct 2026): the requirements that still need a venue, then those that
 * have one, each group in the event's own order. Unchanged while the bookings are not known.
 */
function listRequirements(
  requirements: readonly VenueRequirement[],
  bookings: readonly BookingOutcome[] | null,
): ListedRequirement[] {
  const listed = requirements.map((requirement) => ({
    requirement,
    covering: bookings === null ? undefined : coveringBooking(requirement, bookings),
  }))
  return [
    ...listed.filter((item) => !item.covering),
    ...listed.filter((item) => Boolean(item.covering)),
  ]
}

/** The class of a requirement in the banner: greyed once it has a venue (decided 10 Oct 2026). */
function requirementClassName(base: string, covering: BookingOutcome | null | undefined): string {
  return covering ? `${base} requirement-covered` : base
}

/** Story 12.5 AC2: its status line, when the event's bookings are known. */
function CoverageLine({ id, covering }: { id?: string; covering: BookingOutcome | null }) {
  return (
    <span id={id} className="small requirement-coverage">
      {describeCoverage(covering)}
    </span>
  )
}

interface RequirementChoiceProps {
  event: EventDetail
  listed: ListedRequirement
  isSelected: boolean
  onSelect: (requirement: VenueRequirement) => void
}

/**
 * Story 8.4 AC1/AC3/AC7: one venue requirement to search for. Pressed while it is the one
 * selected; pressing it again restores its own filters, so it never disables itself. Named by the
 * requirement alone, with its facts as the description - and, story 12.5 AC2, whether it has a
 * venue. One that has a venue stays selectable, to show that venue (decided 10 Oct 2026).
 */
function RequirementChoice({ event, listed, isSelected, onSelect }: RequirementChoiceProps) {
  const nameId = useId()
  const factsId = useId()
  const coverageId = useId()
  const { requirement, covering } = listed

  function select() {
    onSelect(requirement)
  }

  return (
    <button
      type="button"
      className={requirementClassName('requirement-choice', covering)}
      aria-pressed={isSelected}
      aria-labelledby={nameId}
      aria-describedby={covering === undefined ? factsId : `${factsId} ${coverageId}`}
      onClick={select}
    >
      <span id={nameId} className="requirement-choice-name">
        {requirementName(event, requirement)}
      </span>
      <span id={factsId} className="small muted">
        {describeRequirement(event, requirement)}
      </span>
      {covering !== undefined && <CoverageLine id={coverageId} covering={covering} />}
    </button>
  )
}

/** Story 8.4 AC5: the event's one venue requirement, shown alone - there is nothing to choose. */
function RequirementSummary({ event, listed }: { event: EventDetail; listed: ListedRequirement }) {
  const { requirement, covering } = listed
  return (
    <div className={requirementClassName('requirement-summary', covering)}>
      <span className="requirement-choice-name">{requirementName(event, requirement)}</span>
      <span className="small muted">{describeRequirement(event, requirement)}</span>
      {covering !== undefined && <CoverageLine covering={covering} />}
    </div>
  )
}

interface RequestingEventBannerProps {
  event: EventDetail
  /** Story 12.5 AC2: the event's venue bookings, or null when they are not known. */
  bookings: readonly BookingOutcome[] | null
  /** Story 8.4: the requirement the page address selects, if it names one of the event's. */
  selectedRequirement: VenueRequirement | null
  /** Story 8.4 AC7: the filters are no longer the selected requirement's own. */
  hasChangedFilters: boolean
  /** Story 12.5 AC5: no requirement is selected, so a venue requested now is an additional one. */
  isAdditionalVenue: boolean
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
 *
 * Story 12.5 AC2: for whoever may read the event's bookings, each requirement also says whether it
 * has a venue. As decided on 10 Oct 2026, those that do are greyed and listed after those that
 * still need one. AC5: with none selected, it says a venue requested now is an additional venue.
 */
export function RequestingEventBanner({
  event,
  bookings,
  selectedRequirement,
  hasChangedFilters,
  isAdditionalVenue,
  onSelectRequirement,
}: RequestingEventBannerProps) {
  const requirementsId = useId()
  const listed = listRequirements(event.venue_requirements, bookings)
  const hasChoice = listed.length > 1
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
      {listed.length > 0 && (
        <div>
          <p id={requirementsId} className="eyebrow">
            {hasChoice ? 'Venue requirements' : 'Venue requirement'}
          </p>
          <ul className="requirement-choices" aria-labelledby={requirementsId}>
            {listed.map((item) => (
              <li key={item.requirement.id}>
                {hasChoice ? (
                  <RequirementChoice
                    event={event}
                    listed={item}
                    isSelected={item.requirement.id === selectedRequirement?.id}
                    onSelect={onSelectRequirement}
                  />
                ) : (
                  <RequirementSummary event={event} listed={item} />
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
      {isAdditionalVenue && (
        <p className="small muted">
          No venue requirement is selected, so a venue requested now is an additional venue for the
          event.
        </p>
      )}
    </section>
  )
}
