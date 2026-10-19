import { useId, useRef, useState, type ReactNode } from 'react'
import {
  getChangeRequestImpact,
  type BookingImpact,
  type CapacityShortfall,
  type ChangeRequest,
  type ChangeRequestImpact as Impact,
  type EquipmentImpact,
  type EquipmentImpactChange,
  type RegistrationImpact,
  type ShortPeriod,
} from '../api/changeRequests'
import type { BookingStatus } from '../api/bookings'
import type { EquipmentItemStatus } from '../api/events'
import { formatApiError } from '../api/client'
import { UNAVAILABILITY_REASON_NAMES } from '../api/venues'
import { Icon, type IconName } from '../components/Icon'
import { LoadingState } from '../layout/LoadingState'
import { EQUIPMENT_STATUS_LABELS } from '../shared/equipmentStatus'
import { ADDITIONAL_VENUE, formatSchedule } from '../shared/format'
import { describeFailure } from '../shared/suitability'
import { NOT_THERE_REQUESTED, OUT_OF_DATE_NOTE } from './changeRequestValues'

/** Story 19.3 AC1: what the assessment says when the change touches nothing already arranged. */
const NO_IMPACT_MESSAGE = 'No existing arrangements are affected.'

/** Shown while the backend works the assessment out, on the request and in the approval dialog. */
export const IMPACT_LOADING_LABEL = 'Assessing the impact…'

/** How strongly something is coloured: cancelled or short, needs a look, or fine as it is. */
type ImpactTone = 'danger' | 'warning' | 'success'

/** AC2/AC5: an equipment item's outcome once approved, by the status 19.2 leaves it in. */
const EQUIPMENT_STATUS_AFTER: Partial<
  Record<EquipmentItemStatus, { label: string; tone: ImpactTone }>
> = {
  PENDING: { label: 'Back to Technical Support', tone: 'warning' },
  REQUESTED: { label: 'Held again', tone: 'success' },
  UNAVAILABLE: { label: 'Not enough available', tone: 'danger' },
  CANCELLED: { label: NOT_THERE_REQUESTED, tone: 'warning' },
}

/** AC7: where a booking stands now, so a decision Venue Staff make while the coordinator looks
 *  shows on its card. Only a pending or approved booking is ever affected. */
const BOOKING_STATUS_NOW: Partial<Record<BookingStatus, string>> = {
  PENDING: 'Pending request',
  APPROVED: 'Approved',
}

/** What each kind of equipment change is, under the item's name. */
const EQUIPMENT_CHANGE_NOTES: Record<EquipmentImpactChange, string> = {
  removed: 'Removed by this change',
  changed: 'Changed by this change',
  added: 'Added by this change',
  rechecked: 'Rechecked for the new dates',
}

/** A story c3 badge in the tone of what it says. */
function Pill({ tone, children }: { tone: ImpactTone; children: ReactNode }) {
  return <span className={`badge badge-sm badge-${tone}`}>{children}</span>
}

/** A labelled line of an arrangement's card: the label in a column of its own on a wide screen,
 *  above the value on a phone. */
function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="impact-fact">
      <dt className="fact-label">{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

/** One check of the same venue for the period a replacement needs, passed or failed. */
function Check({ isOk, label, detail }: { isOk: boolean; label: string; detail?: string }) {
  return (
    <li className={isOk ? 'impact-check impact-check-ok' : 'impact-check impact-check-failed'}>
      <Icon name={isOk ? 'check-circle' : 'x-circle'} size={16} />
      <span>
        {label}
        {detail !== undefined && <span className="impact-check-detail"> {detail}</span>}
      </span>
    </li>
  )
}

/** AC4/AC5: whether the same venue could be requested again for the new times. */
function SameVenueChecks({ booking }: { booking: BookingImpact }) {
  const { held_by: holding, closure } = booking
  return (
    <ul className="impact-checks">
      <Check
        isOk={holding === null}
        label={holding === null ? 'No other booking' : `Held for ${holding.event_name}`}
        detail={
          holding === null ? undefined : formatSchedule(holding.held_from, holding.held_until)
        }
      />
      <Check
        isOk={closure === null}
        label={
          closure === null
            ? 'Not blocked off'
            : `Unavailable: ${UNAVAILABILITY_REASON_NAMES[closure.reason]}`
        }
        detail={closure === null ? undefined : formatSchedule(closure.starts_at, closure.ends_at)}
      />
      <Check
        isOk={!booking.is_outside_opening_hours}
        label={booking.is_outside_opening_hours ? 'Closed at those hours' : 'Open at those hours'}
      />
    </ul>
  )
}

/** The card's last line: what approving does to the arrangement (AC2). */
function AfterApproval({ children }: { children: ReactNode }) {
  return (
    <p className="impact-after">
      <Icon name="arrow-right" size={16} />
      <span>
        <span className="impact-after-label">After approval</span> {children}
      </span>
    </p>
  )
}

/** AC1/AC2/AC4/AC5: one venue booking - whether it is cancelled and why, capacity and facility
 *  warnings apart from that, whether the same venue is free for the new times, and what happens
 *  next. */
function BookingRow({ booking }: { booking: BookingImpact }) {
  const warning = booking.capacity_warning
  const facilities = booking.facility_warnings
  const hasNewTimes = booking.needed_starts_at !== null && booking.needed_ends_at !== null
  return (
    <li className="impact-item">
      <div className="impact-item-header">
        <div>
          <p className="impact-item-name">{booking.venue_name}</p>
          <p className="small muted">
            {booking.requirement_name ?? ADDITIONAL_VENUE} ·{' '}
            {BOOKING_STATUS_NOW[booking.status] ?? booking.status} for{' '}
            {formatSchedule(booking.starts_at, booking.ends_at)}
          </p>
        </div>
        <div className="impact-item-pills">
          {booking.will_be_cancelled ? (
            <Pill tone="danger">Will be cancelled</Pill>
          ) : (
            <Pill tone="success">Kept</Pill>
          )}
          {warning !== null && <Pill tone="warning">Too small</Pill>}
          {facilities.length > 0 && <Pill tone="warning">Missing a facility</Pill>}
        </div>
      </div>
      <dl className="impact-facts">
        {booking.reasons.length > 0 && (
          <Fact label="Why">
            {booking.reasons.map((reason) => (
              <p key={reason}>{reason}</p>
            ))}
          </Fact>
        )}
        {warning !== null && (
          <Fact label="Capacity">
            Needs room for {warning.people_needed}; {booking.venue_name} holds{' '}
            {warning.venue_capacity}
            {warning.layout_name === null ? '' : ` in the ${warning.layout_name} layout`}.
          </Fact>
        )}
        {facilities.length > 0 && (
          <Fact label="Facilities">
            {facilities.map((failure) => (
              <p key={failure.code}>{describeFailure(failure)}</p>
            ))}
          </Fact>
        )}
        {hasNewTimes && (
          <Fact label="New times">
            {formatSchedule(booking.needed_starts_at ?? '', booking.needed_ends_at ?? '')}
          </Fact>
        )}
        {hasNewTimes && (
          <Fact label="Same venue">
            <SameVenueChecks booking={booking} />
          </Fact>
        )}
      </dl>
      <AfterApproval>{booking.after_approval}</AfterApproval>
    </li>
  )
}

/** One figure of an item's or the registrations' card. */
function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: ImpactTone }) {
  return (
    <div className={tone === undefined ? 'impact-stat' : `impact-stat impact-stat-${tone}`}>
      <p className="fact-label">{label}</p>
      <p className="impact-stat-value">{value}</p>
    </div>
  )
}

/** AC1/AC4: one stretch of the event the venues in use then are too small for. */
function ShortPeriodFacts({ period }: { period: ShortPeriod }) {
  return (
    <dl className="impact-facts">
      <Fact label="When">{formatSchedule(period.starts_at, period.ends_at)}</Fact>
      <Fact label="In use">
        {period.venues.map((venue) => (
          <p key={venue.venue_id}>
            {venue.venue_name}: holds {venue.capacity}
            {venue.layout_name === null ? '' : ` in the ${venue.layout_name} layout`}
          </p>
        ))}
      </Fact>
      <Fact label="Short by">
        {period.shortfall}, with room for {period.capacity}
      </Fact>
    </dl>
  )
}

/** AC1/AC4: at some moments the venues the approval keeps hold fewer people, between the ones
 *  in use then, than the attendance asked for - a warning; no booking is cancelled for it. */
function CapacityShortfallCard({ shortfall }: { shortfall: CapacityShortfall }) {
  const largest = Math.max(...shortfall.periods.map((period) => period.shortfall))
  return (
    <div className="impact-item">
      <div className="impact-item-header">
        <div>
          <p className="impact-item-name">Not enough room for the new attendance</p>
          <p className="small muted">
            At these times, the venues in use hold fewer people between them.
          </p>
        </div>
        <div className="impact-item-pills">
          <Pill tone="warning">Too small</Pill>
        </div>
      </div>
      <div className="impact-stats">
        <Stat label="Proposed attendance" value={shortfall.proposed_attendance} />
        <Stat label="Short by up to" value={largest} tone="warning" />
      </div>
      <ul className="impact-items">
        {shortfall.periods.map((period) => (
          <li key={period.starts_at}>
            <ShortPeriodFacts period={period} />
          </li>
        ))}
      </ul>
      <AfterApproval>
        The bookings stay as they are: approving cancels none of them, and a booked venue cannot be
        swapped for a larger one. If everyone needs room at those times, request an additional venue
        from the event page (one smaller than the whole attendance needs a justification), or reject
        the change and tell the organiser why.
      </AfterApproval>
    </div>
  )
}

/** AC2/AC5: one equipment item - what the change does to it, the units it needs against those
 *  available, the shortfall, and what happens next. */
function EquipmentRow({ item }: { item: EquipmentImpact }) {
  const outcome =
    item.status_after === null
      ? { label: NOT_THERE_REQUESTED, tone: 'warning' as const }
      : EQUIPMENT_STATUS_AFTER[item.status_after]
  return (
    <li className="impact-item">
      <div className="impact-item-header">
        <div>
          <p className="impact-item-name">{item.equipment_type_name}</p>
          <p className="small muted">
            {EQUIPMENT_CHANGE_NOTES[item.change]}
            {item.current_status === null
              ? ''
              : ` · Now ${EQUIPMENT_STATUS_LABELS[item.current_status]}`}
          </p>
        </div>
        <div className="impact-item-pills">
          {outcome !== undefined && <Pill tone={outcome.tone}>{outcome.label}</Pill>}
        </div>
      </div>
      {item.required !== null && (
        <div className="impact-stats">
          <Stat label="Required" value={item.required} />
          <Stat label="Available" value={item.available} />
          <Stat
            label="Shortfall"
            value={item.shortfall}
            tone={item.shortfall > 0 ? 'danger' : undefined}
          />
        </div>
      )}
      <AfterApproval>{item.after_approval}</AfterApproval>
    </li>
  )
}

/** AC1: the registrations, counted - never named - and kept as they are. */
function RegistrationsSummary({ registrations }: { registrations: RegistrationImpact }) {
  const isOver = registrations.over_by > 0
  return (
    <div className="impact-item">
      <div className="impact-item-header">
        <div>
          <p className="impact-item-name">Attendee registrations</p>
          <p className="small muted">
            {isOver
              ? 'More are registered than the proposed attendance allows.'
              : 'Every registration is for the current dates, which this changes.'}
          </p>
        </div>
        <div className="impact-item-pills">
          <Pill tone="warning">{isOver ? `${registrations.over_by} over` : 'Dates move'}</Pill>
        </div>
      </div>
      <div className="impact-stats">
        <Stat label="Registered" value={registrations.active_count} />
        {registrations.proposed_attendance !== null && (
          <Stat label="Proposed attendance" value={registrations.proposed_attendance} />
        )}
        {isOver && <Stat label="Over by" value={registrations.over_by} tone="warning" />}
      </div>
      <AfterApproval>Kept as they are.</AfterApproval>
    </div>
  )
}

/** One category's line at a glance: its pill and its one-sentence summary. */
interface CategorySummary {
  tone: ImpactTone
  pill: string
  summary: string
}

const NO_IMPACT_PILL = 'No impact'

function counted(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

/** `parts` as one sentence: "a; b." */
function sentence(parts: string[]): string {
  return `${parts.join('; ')}.`
}

/** AC1: cancellations first, then capacity and facility warnings, which never mean a
 *  cancellation. */
function bookingSummary(
  bookings: BookingImpact[],
  shortfall: CapacityShortfall | null,
): CategorySummary {
  if (bookings.length === 0 && shortfall === null) {
    return { tone: 'success', pill: NO_IMPACT_PILL, summary: 'No venue bookings are affected.' }
  }
  const cancelled = bookings.filter((booking) => booking.will_be_cancelled).length
  const warned = bookings.filter((booking) => booking.capacity_warning !== null).length
  const lacking = bookings.filter((booking) => booking.facility_warnings.length > 0).length
  const parts: string[] = []
  if (cancelled > 0) {
    parts.push(`${counted(cancelled, 'booking')} will be cancelled on approval`)
  }
  if (warned > 0) {
    parts.push(`${counted(warned, 'venue')} too small for the people now needed`)
  }
  if (lacking > 0) {
    parts.push(`${counted(lacking, 'venue')} missing a facility the change needs`)
  }
  if (shortfall !== null) {
    parts.push(
      `venues in use are too small for the ${shortfall.proposed_attendance} now expected during ${counted(shortfall.periods.length, 'period')}`,
    )
  }
  const text = sentence(parts)
  return {
    tone: cancelled > 0 ? 'danger' : 'warning',
    pill: bookings.length > 0 ? `${bookings.length} affected` : 'Too small',
    summary: text.charAt(0).toUpperCase() + text.slice(1),
  }
}

/** What approving does to one item, as a phrase its category's summary counts. */
function equipmentOutcome(item: EquipmentImpact): string {
  if (item.change === 'removed') return 'removed'
  if (item.status_after === 'UNAVAILABLE') return 'short, and flagged Unavailable'
  if (item.status_after === 'PENDING') return 'back to Technical Support for rechecking'
  if (item.change === 'rechecked' && item.current_status === item.status_after) {
    return 'held again for the new dates'
  }
  return 'back with you to send to Technical Support'
}

/** AC2/AC5: each kind of outcome counted, in the order first met. */
function equipmentSummary(items: EquipmentImpact[]): CategorySummary {
  if (items.length === 0) {
    return { tone: 'success', pill: NO_IMPACT_PILL, summary: 'No equipment is affected.' }
  }
  const counts = new Map<string, number>()
  for (const item of items) {
    const outcome = equipmentOutcome(item)
    counts.set(outcome, (counts.get(outcome) ?? 0) + 1)
  }
  const parts = [...counts].map(([outcome, count]) => `${counted(count, 'item')} ${outcome}`)
  return {
    tone: items.some((item) => item.shortfall > 0) ? 'danger' : 'warning',
    pill: `${items.length} affected`,
    summary: sentence(parts),
  }
}

/** AC1: counted, never named. */
function registrationSummary(registrations: RegistrationImpact | null): CategorySummary {
  if (registrations === null) {
    return { tone: 'success', pill: NO_IMPACT_PILL, summary: 'No registrations are affected.' }
  }
  const registered = counted(registrations.active_count, 'attendee')
  const summary =
    registrations.over_by > 0
      ? `${registered} registered, ${registrations.over_by} more than the proposed attendance of ${registrations.proposed_attendance}.`
      : `${registered} registered for the current dates, which this change moves.`
  return { tone: 'warning', pill: `${registrations.active_count} affected`, summary }
}

interface ImpactCategoryProps {
  title: string
  icon: IconName
  summary: CategorySummary
  /** The arrangements one by one; null when nothing in the category is affected. */
  children: ReactNode | null
}

/** One category of the assessment: its line at a glance, opening onto each arrangement. */
function ImpactCategory({ title, icon, summary, children }: ImpactCategoryProps) {
  const [isOpen, setIsOpen] = useState(false)
  const detailsId = useId()
  const glance = (
    <>
      <span className={`impact-category-icon impact-tone-${summary.tone}`}>
        <Icon name={icon} size={20} />
      </span>
      <span className="impact-category-text">
        <span className="impact-category-title">
          {title}
          <Pill tone={summary.tone}>{summary.pill}</Pill>
        </span>
        <span className="impact-category-summary">{summary.summary}</span>
      </span>
    </>
  )

  function toggleDetails() {
    setIsOpen((wasOpen) => !wasOpen)
  }

  if (children === null) {
    return (
      <div className="impact-category">
        <div className="impact-category-header">{glance}</div>
      </div>
    )
  }
  return (
    <div className="impact-category">
      <button
        type="button"
        className="impact-category-header"
        aria-expanded={isOpen}
        aria-controls={detailsId}
        onClick={toggleDetails}
      >
        {glance}
        <span className="impact-category-chevron">
          <Icon name={isOpen ? 'chevron-up' : 'chevron-down'} />
        </span>
      </button>
      {isOpen && (
        <div
          id={detailsId}
          role="region"
          aria-label={`${title} affected`}
          className="impact-details"
        >
          {children}
        </div>
      )}
    </div>
  )
}

export interface ChangeRequestImpactProps {
  impact: Impact
  /** AC7: an approval found the impact had changed, so this is the assessment as it stands now. */
  isUpdated?: boolean
}

/**
 * Story 19.3 - what approving a change request would affect, as the backend assessed it. AC1: one
 * row each for venue bookings, equipment and registrations, its pill and summary saying at a
 * glance whether and how much is affected; opening a row lists each arrangement with why, a
 * capacity warning shown apart from a cancellation. A change that affects nothing says so. AC2:
 * each arrangement says what the approval does to it. A change 19.2 would refuse, or one that is
 * out of date, says that instead. AC7: marked when it replaced an assessment that had changed.
 */
export function ChangeRequestImpact({ impact, isUpdated = false }: ChangeRequestImpactProps) {
  const {
    venue_bookings: bookings,
    equipment,
    registrations,
    capacity_shortfall: shortfall,
  } = impact
  return (
    <div className={isUpdated ? 'impact-panel impact-panel-updated' : 'impact-panel'}>
      <div>
        <h4 className="impact-panel-title">
          {isUpdated
            ? 'Updated impact of approving this change'
            : 'Impact of approving this change'}
        </h4>
        <p className="small muted">
          {isUpdated
            ? 'The records changed since you opened this request. This is what approving would do now.'
            : 'How existing arrangements would be affected, worked out from current records.'}
        </p>
      </div>
      {impact.is_out_of_date && <p className="warning">{OUT_OF_DATE_NOTE}</p>}
      {impact.refused_because !== null && (
        <p className="warning">Approving would be refused: {impact.refused_because}</p>
      )}
      {!impact.is_out_of_date && impact.refused_because === null && (
        <>
          {!impact.has_impact && <p className="impact-none">{NO_IMPACT_MESSAGE}</p>}
          <div className="impact-categories">
            <ImpactCategory
              title="Venue bookings"
              icon="building"
              summary={bookingSummary(bookings, shortfall)}
            >
              {bookings.length === 0 && shortfall === null ? null : (
                <div className="impact-items">
                  {shortfall !== null && <CapacityShortfallCard shortfall={shortfall} />}
                  {bookings.length > 0 && (
                    <ul className="impact-items">
                      {bookings.map((booking) => (
                        <BookingRow key={booking.booking_id} booking={booking} />
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </ImpactCategory>
            <ImpactCategory title="Equipment" icon="box" summary={equipmentSummary(equipment)}>
              {equipment.length === 0 ? null : (
                <ul className="impact-items">
                  {equipment.map((item, index) => (
                    <EquipmentRow
                      key={item.item_id ?? `added-${item.equipment_type_code}-${index}`}
                      item={item}
                    />
                  ))}
                </ul>
              )}
            </ImpactCategory>
            <ImpactCategory
              title="Registrations"
              icon="people"
              summary={registrationSummary(registrations)}
            >
              {registrations === null ? null : (
                <RegistrationsSummary registrations={registrations} />
              )}
            </ImpactCategory>
          </div>
        </>
      )}
    </div>
  )
}

/**
 * Story 19.3 AC1/AC3 - on a pending request's card, for its assigned coordinator: "Show impact"
 * asks the backend for a fresh assessment each time it is opened, so it reflects the records as
 * they stand then.
 */
export function ChangeRequestImpactToggle({ request }: { request: ChangeRequest }) {
  const [isOpen, setIsOpen] = useState(false)
  const [impact, setImpact] = useState<Impact | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Each opening's assessment, numbered, so an answer to an earlier opening is never shown.
  const latestLoad = useRef(0)

  async function toggle() {
    if (isOpen) {
      setIsOpen(false)
      return
    }
    const load = ++latestLoad.current
    setIsOpen(true)
    setImpact(null)
    setError(null)
    try {
      const assessed = await getChangeRequestImpact(request.event_id, request.id)
      if (load === latestLoad.current) setImpact(assessed)
    } catch (err) {
      if (load === latestLoad.current) setError(formatApiError(err))
    }
  }

  return (
    <div className="stack">
      <div>
        <button
          type="button"
          className="secondary button-sm button-with-icon"
          aria-expanded={isOpen}
          onClick={toggle}
        >
          <Icon name={isOpen ? 'chevron-up' : 'chevron-down'} size={16} />
          {isOpen ? 'Hide impact' : 'Show impact'}
        </button>
      </div>
      {isOpen && error !== null && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isOpen && error === null && impact === null && <LoadingState label={IMPACT_LOADING_LABEL} />}
      {isOpen && impact !== null && <ChangeRequestImpact impact={impact} />}
    </div>
  )
}
