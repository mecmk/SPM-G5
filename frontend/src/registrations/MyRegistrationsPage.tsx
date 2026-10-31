import { Link } from 'react-router'
import { mediaUrl } from '../api/client'
import { listMyRegistrations, type MyRegistration } from '../api/registrations'
import { EmptyState } from '../components/EmptyState'
import { EventCard, EventCardGrid, type EventCardBackState } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { MY_REGISTRATIONS_PATH, UPCOMING_EVENTS_PATH, upcomingEventPath } from '../routes'
import { formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import {
  MY_REGISTRATIONS_TITLE,
  STANDING_BADGES,
  describeActiveRegistration,
} from './registrationLabels'

/** Story 18.2 AC9 (fix f18.2.1): an event's page opened from here links back here. */
const BACK_TO_MY_REGISTRATIONS: EventCardBackState = {
  from: MY_REGISTRATIONS_PATH,
  fromLabel: MY_REGISTRATIONS_TITLE,
}

/**
 * Story 18.2 AC1/AC8: one registration's card - its event's name, picture, date and time, where
 * the attendee stands, and when they registered, while they still are. Story 18.5 AC3: the guests
 * registered with them. AC9 (fix f18.2.1): a click anywhere on it opens the event's page (story
 * 18.1 AC9), where the attendee withdraws or changes their guests; the card itself offers neither.
 */
function MyRegistrationCard({ registration }: { registration: MyRegistration }) {
  const badge = STANDING_BADGES[registration.status]
  const details = [
    <StatusBadge key="status" status={badge.status} label={badge.label} />,
    formatSchedule(registration.starts_at, registration.ends_at),
    ...describeActiveRegistration(registration),
  ]
  return (
    <EventCard
      title={registration.event_name}
      imageUrl={mediaUrl(registration.cover_image_url)}
      details={details}
      to={upcomingEventPath(registration.event_id)}
      state={BACK_TO_MY_REGISTRATIONS}
    />
  )
}

/**
 * Story 18.2 - view and withdraw my registrations.
 * AC1: the attendee's registrations, one per event, with its name, picture, date and time, status
 *      and, while they are registered, when they registered; with none, the page says so and
 *      points to Upcoming events. Withdrawing is on the event's page (AttendeeEventPage), and
 *      so, story 18.5 AC3, is changing the guests each registration names.
 * AC5: attendees only - App.tsx guards the route, and the backend sends only their own.
 * AC9 (fix f18.2.1): each card opens its event's page.
 */
export function MyRegistrationsPage() {
  const { data: registrations, error, isLoading } = useLoaded(listMyRegistrations)

  return (
    <div className="page page-wide">
      <p className="eyebrow">Attend</p>
      <PageHeader
        title={MY_REGISTRATIONS_TITLE}
        subtitle="The events you have registered for, and where you stand at each."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading your registrations…" />}

      {registrations !== null && registrations.length === 0 && (
        <EmptyState>
          You have not registered for any events yet.{' '}
          <Link to={UPCOMING_EVENTS_PATH}>Browse upcoming events</Link>
        </EmptyState>
      )}

      {registrations !== null && registrations.length > 0 && (
        <EventCardGrid>
          {registrations.map((registration) => (
            <MyRegistrationCard key={registration.id} registration={registration} />
          ))}
        </EventCardGrid>
      )}
    </div>
  )
}
