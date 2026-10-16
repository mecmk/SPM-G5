import { useCallback } from 'react'
import { Link, useParams } from 'react-router'
import { getSafetyCheck, type FactChange, type SafetyFact } from '../api/safety'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { SAFETY_CHECKS_PATH } from '../routes'
import { NOT_RECORDED, formatDateTime, formatSchedule } from '../shared/format'
import { ARRANGEMENT_LABELS } from '../shared/safetyReview'
import { useLoaded } from '../shared/useLoaded'
import { SafetyDecisionForm } from './SafetyDecisionForm'

/** The shapes `safety_facts` (backend/app/safety/service.py) writes its list facts in. */
interface VenueFact {
  name: string
  capacity: number
  people_to_hold: number
  layout_name: string | null
}

interface AccessibilityFact {
  feature_name: string
  notes: string | null
}

interface EquipmentFact {
  equipment_type_name: string
  quantity: number
  technical_notes: string | null
}

const FACT_LABELS: Record<SafetyFact, string> = {
  description: 'Description',
  expected_attendance: 'Expected attendance',
  starts_at: 'Start',
  ends_at: 'End',
  venues: 'Venues',
  accessibility: 'Accessibility needs',
  accessibility_notes: 'Accessibility notes',
  equipment: 'Equipment',
}

const NONE = 'None'

function listOrNone(items: string[]): string {
  return items.length > 0 ? items.join('; ') : NONE
}

/** Story 21.1 AC5: one side of a changed fact, in words. */
function describeFact(fact: SafetyFact, value: unknown): string {
  if (value === null || value === undefined) return NOT_RECORDED
  switch (fact) {
    case 'starts_at':
    case 'ends_at':
      return formatDateTime(value as string)
    case 'venues':
      return listOrNone(
        (value as VenueFact[]).map(
          (venue) =>
            `${venue.name} (${venue.people_to_hold} people, holds ${venue.capacity}, ${venue.layout_name ?? NOT_RECORDED})`,
        ),
      )
    case 'accessibility':
      return listOrNone(
        (value as AccessibilityFact[]).map((need) =>
          need.notes ? `${need.feature_name}: ${need.notes}` : need.feature_name,
        ),
      )
    case 'equipment':
      return listOrNone(
        (value as EquipmentFact[]).map((item) =>
          item.technical_notes
            ? `${item.quantity} × ${item.equipment_type_name} (${item.technical_notes})`
            : `${item.quantity} × ${item.equipment_type_name}`,
        ),
      )
    default:
      return String(value)
  }
}

function operatingHours(start: string | null, end: string | null): string {
  return start && end ? `${start.slice(0, 5)}–${end.slice(0, 5)}` : NOT_RECORDED
}

function ChangesList({ changes }: { changes: FactChange[] }) {
  return (
    <ul className="stack safety-fact-list">
      {changes.map((change) => (
        <li key={change.fact} className="subtle-block">
          <p className="fact-label">{FACT_LABELS[change.fact]}</p>
          <p>
            Was: {describeFact(change.fact, change.before)}
            <br />
            Now: {describeFact(change.fact, change.after)}
          </p>
        </li>
      ))}
    </ul>
  )
}

/**
 * Story 21.1 - one event awaiting the safety check, read-only, opened from the queue.
 * AC3: the event and its description, each approved venue with its record (story 8.2) and the
 * layout booked, accessibility needs, accepted equipment with technical notes, and the previous
 * reviews, newest first. AC4: a venue whose booking must hold more people than the venue holds
 * in the booked layout is flagged Over capacity, with both figures shown. AC5: a detail never
 * recorded says so, and what changed since the last review is listed, fact by fact.
 * Story 21.2 AC2: the review factors, and the decision form while the event awaits the check;
 * AC4: each previous review lists its findings.
 */
export function SafetyCheckDetailPage() {
  const { eventId = '' } = useParams()
  const loadCheck = useCallback(() => getSafetyCheck(eventId), [eventId])
  const { data: check, error, isLoading, setData } = useLoaded(loadCheck)

  return (
    <div className="page page-wide">
      {check === null && (
        <Link to={SAFETY_CHECKS_PATH} className="back-link">
          ← Safety Checks
        </Link>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading the safety check…" />}

      {check !== null && (
        <div className="stack">
          <PageHeader
            title={check.name}
            backTo={SAFETY_CHECKS_PATH}
            backLabel="Safety Checks"
            action={<EventStatusBadge status={check.status} />}
          />

          <section className="card stack" aria-labelledby="safety-event-heading">
            <h2 id="safety-event-heading">Event</h2>
            <div className="subtle-block">
              <p className="fact-label">Description</p>
              <p>{check.description ?? NOT_RECORDED}</p>
            </div>
            <div className="fact-grid">
              <div className="subtle-block">
                <p className="fact-label">Date and time</p>
                <p className="fact-value">{formatSchedule(check.starts_at, check.ends_at)}</p>
              </div>
              <div className="subtle-block">
                <p className="fact-label">Expected attendance</p>
                <p className="fact-value">{check.expected_attendance}</p>
              </div>
            </div>
          </section>

          <section className="card stack" aria-labelledby="safety-venues-heading">
            <h2 id="safety-venues-heading">Venues</h2>
            {check.venues.length === 0 && <p className="muted">No approved venues.</p>}
            {check.venues.map(({ venue, layout, capacity, people_to_hold, over_capacity }) => (
              <div key={venue.id} className="subtle-block stack">
                <div className="cluster">
                  <h3>{venue.name}</h3>
                  {over_capacity && <span className="badge badge-warning">Over capacity</span>}
                </div>
                <div className="fact-grid">
                  <div>
                    <p className="fact-label">Capacity in this layout</p>
                    <p className="fact-value">{capacity}</p>
                  </div>
                  <div>
                    <p className="fact-label">People to hold</p>
                    <p className="fact-value">{people_to_hold}</p>
                  </div>
                  <div>
                    <p className="fact-label">Layout</p>
                    <p className="fact-value">{layout ?? NOT_RECORDED}</p>
                  </div>
                  <div>
                    <p className="fact-label">Location</p>
                    <p className="fact-value">{venue.location}</p>
                  </div>
                  <div>
                    <p className="fact-label">Floor area</p>
                    <p className="fact-value">
                      {venue.floor_area_sqm ? `${venue.floor_area_sqm} m²` : NOT_RECORDED}
                    </p>
                  </div>
                  <div>
                    <p className="fact-label">Operating hours</p>
                    <p className="fact-value">
                      {operatingHours(venue.operating_hours_start, venue.operating_hours_end)}
                    </p>
                  </div>
                  <div>
                    <p className="fact-label">Operating notes</p>
                    <p className="fact-value">{venue.operating_notes || NOT_RECORDED}</p>
                  </div>
                  <div>
                    <p className="fact-label">Accessibility features</p>
                    <p className="fact-value">
                      {venue.accessibility_features.length > 0
                        ? venue.accessibility_features.map((feature) => feature.name).join(', ')
                        : NOT_RECORDED}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </section>

          <section className="card stack" aria-labelledby="safety-accessibility-heading">
            <h2 id="safety-accessibility-heading">Accessibility</h2>
            {check.accessibility_needs.length === 0 ? (
              <p className="muted">No accessibility needs.</p>
            ) : (
              <ul className="stack safety-fact-list">
                {check.accessibility_needs.map((need) => (
                  <li key={need.code} className="subtle-block">
                    <p className="fact-label">{need.name}</p>
                    <p>{need.notes ?? NOT_RECORDED}</p>
                  </li>
                ))}
              </ul>
            )}
            {check.accessibility_notes && <p>{check.accessibility_notes}</p>}
          </section>

          <section className="card stack" aria-labelledby="safety-equipment-heading">
            <h2 id="safety-equipment-heading">Equipment</h2>
            {check.equipment.length === 0 ? (
              <p className="muted">No accepted equipment.</p>
            ) : (
              <ul className="stack safety-fact-list">
                {check.equipment.map((item) => (
                  <li key={item.id} className="subtle-block">
                    <p className="fact-label">
                      {item.quantity} × {item.equipment_type_name}
                    </p>
                    <p>{item.technical_notes ?? 'No technical notes.'}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card stack" aria-labelledby="safety-changes-heading">
            <h2 id="safety-changes-heading">Changes since last review</h2>
            {check.previous_reviews.length === 0 ? (
              <p className="muted">Not reviewed before, so there is nothing to compare.</p>
            ) : check.changes_since_last_review.length === 0 ? (
              <p className="muted">Nothing has changed since the last review.</p>
            ) : (
              <ChangesList changes={check.changes_since_last_review} />
            )}
          </section>

          <section className="card stack" aria-labelledby="safety-factors-heading">
            <h2 id="safety-factors-heading">Review factors</h2>
            <ul className="stack safety-fact-list">
              {check.factors.map((factor) => (
                <li key={factor.code} className="subtle-block">
                  <p className="fact-label">{factor.name}</p>
                  {factor.description && <p>{factor.description}</p>}
                </li>
              ))}
            </ul>
          </section>

          {check.status === 'AWAITING_SAFETY_CHECK' && (
            <SafetyDecisionForm key={check.id} check={check} onDecided={setData} />
          )}

          <section className="card stack" aria-labelledby="safety-reviews-heading">
            <h2 id="safety-reviews-heading">Previous reviews</h2>
            {check.previous_reviews.length === 0 ? (
              <p className="muted">No previous reviews.</p>
            ) : (
              <ul className="stack safety-fact-list">
                {check.previous_reviews.map((review) => (
                  <li key={review.id} className="subtle-block stack">
                    <div className="cluster">
                      <StatusBadge status={review.outcome} />
                      <span className="small muted">
                        {formatDateTime(review.reviewed_at)} by {review.reviewed_by_name}
                      </span>
                    </div>
                    {review.findings.length > 0 && (
                      <ol className="stack">
                        {review.findings.map((finding, index) => (
                          <li key={index}>
                            <p className="fact-label">
                              {finding.factor_name}
                              {finding.arrangement &&
                                ` · ${ARRANGEMENT_LABELS[finding.arrangement]} must change`}
                            </p>
                            <p>{finding.required_change}</p>
                          </li>
                        ))}
                      </ol>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
