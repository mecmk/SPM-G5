import type { CoordinatorOption } from '../api/coordination'

/** Story 5.4 AC3: a coordinator as the picker names them - their name and active-event count. */
function describeCoordinator(coordinator: CoordinatorOption): string {
  const count = coordinator.active_event_count
  return `${coordinator.full_name} · ${count} active ${count === 1 ? 'event' : 'events'}`
}

interface CoordinatorPickerProps {
  label: string
  /** Null while the list loads. */
  coordinators: CoordinatorOption[] | null
  value: string
  onChange: (coordinatorId: string) => void
}

/**
 * Stories 5.4 and 5.6: choose an active Event Coordinator, each shown with their number of active
 * events (5.4 AC3) - for the Lead's first assignment and for a reassignment, whose list leaves the
 * event's current coordinator out (5.6 AC3, `listCoordinators(eventId)`).
 */
export function CoordinatorPicker({
  label,
  coordinators,
  value,
  onChange,
}: CoordinatorPickerProps) {
  return (
    <label>
      {label}
      <select
        value={value}
        onChange={(change) => onChange(change.target.value)}
        disabled={coordinators === null || coordinators.length === 0}
      >
        {coordinators === null && <option value="">Loading…</option>}
        {coordinators?.length === 0 && <option value="">No other coordinators available</option>}
        {coordinators?.map((coordinator) => (
          <option key={coordinator.id} value={coordinator.id}>
            {describeCoordinator(coordinator)}
          </option>
        ))}
      </select>
    </label>
  )
}
