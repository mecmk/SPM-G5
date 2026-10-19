import { useCallback, useState } from 'react'
import { getVenueCalendar } from '../api/venues'
import { VenueAvailabilityCalendar } from '../components/VenueAvailabilityCalendar'
import type { DayClosure } from '../components/venueCalendarDays'
import { useVenueCalendar, VENUE_CALENDAR_DAY_PANEL_ID } from '../shared/useVenueCalendar'
import { AVAILABILITY_LABEL, blockOffLabel, CLOSURES_SAVED_NOTE } from './blockOffLabels'
import { ClosureActions } from './ClosureActions'
import { VenueUnavailabilitySection } from './VenueUnavailabilitySection'

export interface VenueUnavailabilityManagerProps {
  venueId: string
  venueName: string
}

/**
 * Story 9.4 AC1/AC6/AC9, placed by fix f9.4.1: Venue Staff's own controls for a venue's
 * unavailable periods - the calendar whose day lists carry each period's Edit, End now and Remove,
 * and the Block off time card that adds one. They live on the Edit venue page only; the venue's
 * details page keeps a calendar that shows each period and its reason and nothing to change.
 * Rendered only for whoever holds the permission to manage unavailability, and the backend
 * refuses the writes to anyone else. 9.4's rules are the same as when the controls were on the
 * details page; what is new with the move is each day row's hint beside Remove and End now, and
 * an ended closure showing as Ended.
 */
export function VenueUnavailabilityManager({
  venueId,
  venueName,
}: VenueUnavailabilityManagerProps) {
  const loadWindows = useCallback(
    (startsAt: string, endsAt: string) => getVenueCalendar(venueId, startsAt, endsAt),
    [venueId],
  )
  /** Counts the closures saved from this page, so the calendar loads them again. */
  const [closureVersion, setClosureVersion] = useState(0)
  const calendar = useVenueCalendar(loadWindows, new Date(), String(closureVersion))
  /** Story 9.4 AC6: the closure whose row's Edit was pressed, while the form is open on it. */
  const [editingClosure, setEditingClosure] = useState<DayClosure | null>(null)

  function handleClosureSaved() {
    setClosureVersion((version) => version + 1)
  }

  function handleEditFinished() {
    setEditingClosure(null)
  }

  function renderClosureActions(closure: DayClosure) {
    /** Ended or removed from its row: if its form is open, there is nothing left to edit. */
    function handleClosureChanged() {
      if (editingClosure?.id === closure.id) setEditingClosure(null)
      handleClosureSaved()
    }

    return (
      <ClosureActions
        key={`${closure.id}:${closure.startsAt}:${closure.endsAt}`}
        venueId={venueId}
        closure={closure}
        onEdit={setEditingClosure}
        onChanged={handleClosureChanged}
      />
    )
  }

  return (
    <div className="stack venue-form">
      <p className="form-hint">{CLOSURES_SAVED_NOTE}</p>
      <fieldset className="card stack">
        <legend>{AVAILABILITY_LABEL}</legend>
        <VenueAvailabilityCalendar
          month={calendar.month}
          onMonthChange={calendar.setMonth}
          windows={calendar.windows}
          error={calendar.error}
          isLoading={calendar.isLoading}
          dayPanelId={VENUE_CALENDAR_DAY_PANEL_ID}
          renderClosureActions={renderClosureActions}
        />
      </fieldset>

      <fieldset className="card stack">
        <legend>{blockOffLabel(editingClosure !== null)}</legend>
        <p className="muted">
          Close this venue for a period, for example for maintenance. Any bookings in that period
          will be flagged and their coordinators told.
        </p>
        <VenueUnavailabilitySection
          key={editingClosure?.id ?? 'new'}
          venueId={venueId}
          venueName={venueName}
          onSaved={handleClosureSaved}
          editing={editingClosure}
          onEditFinished={handleEditFinished}
        />
      </fieldset>
    </div>
  )
}
