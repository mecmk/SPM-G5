import { useState } from 'react'
import { ApiError, formatApiError } from '../api/client'
import {
  assignUnassignedEvent,
  listCoordinators,
  listUnassignedEvents,
  type CoordinatorOption,
  type UnassignedEventEntry,
} from '../api/coordination'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { CoordinatorPicker } from '../components/CoordinatorPicker'
import { EmptyState } from '../components/EmptyState'
import { EventCard, EventCardGrid } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { LoadingState } from '../layout/LoadingState'
import { EVENTS_UNASSIGNED_PATH, eventPath } from '../routes'
import { formatDateTime, formatSchedule, NOT_RECORDED } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'

const QUEUE_LABEL = 'Unassigned events'
const BACK_TO_QUEUE = { from: EVENTS_UNASSIGNED_PATH, fromLabel: QUEUE_LABEL }

/** What the queue needs on arrival: the events waiting, and who they can go to. */
interface UnassignedQueue {
  events: UnassignedEventEntry[]
  coordinators: CoordinatorOption[]
}

async function loadQueue(): Promise<UnassignedQueue> {
  const [events, coordinators] = await Promise.all([listUnassignedEvents(), listCoordinators()])
  return { events, coordinators }
}

/**
 * Story 5.4 - the Event Coordinator Lead's unassigned queue.
 * AC2: every submitted event with no coordinator, oldest submission first (the backend's order),
 * with its name, dates, attendance, organiser and submission time. The name opens it read-only.
 * AC3: Assign opens a picker of the active coordinators, each with their active-event count; on
 * confirming, the event leaves the queue.
 * AC5: an empty queue says so, and with no active coordinator Assign is disabled and the page
 * says why.
 * AC8: if another Lead assigned the event first, the dialog closes, the page shows the backend's
 * 409 sentence naming who got it, and the queue reloads, so the event leaves it and the counts
 * include the other Lead's assignment.
 */
export function UnassignedQueuePage() {
  const { data: queue, error, isLoading, setData: setQueue } = useLoaded(loadQueue)
  const [assigning, setAssigning] = useState<UnassignedEventEntry | null>(null)
  const [selectedCoordinatorId, setSelectedCoordinatorId] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [assignError, setAssignError] = useState<string | null>(null)
  const [conflict, setConflict] = useState<string | null>(null)

  const hasCoordinators = queue !== null && queue.coordinators.length > 0

  function askToAssign(entry: UnassignedEventEntry) {
    setAssignError(null)
    setConflict(null)
    setSelectedCoordinatorId(queue?.coordinators[0]?.id ?? '')
    setAssigning(entry)
  }

  function cancelAssign() {
    setAssigning(null)
  }

  function removeFromQueue(eventId: string, coordinatorId: string | null) {
    setQueue((current) =>
      current === null
        ? current
        : {
            events: current.events.filter((entry) => entry.id !== eventId),
            coordinators: current.coordinators.map((coordinator) =>
              coordinator.id === coordinatorId
                ? { ...coordinator, active_event_count: coordinator.active_event_count + 1 }
                : coordinator,
            ),
          },
    )
  }

  /** AC8: after losing to another Lead, read the queue and the counts afresh; if that fails, at
   *  least drop the event this Lead was told is taken. */
  async function reloadQueue(takenEventId: string) {
    try {
      setQueue(await loadQueue())
    } catch {
      removeFromQueue(takenEventId, null)
    }
  }

  async function confirmAssign() {
    if (assigning === null) return
    setIsSaving(true)
    setAssignError(null)
    try {
      await assignUnassignedEvent(assigning.id, selectedCoordinatorId)
      removeFromQueue(assigning.id, selectedCoordinatorId)
      setAssigning(null)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'CONFLICT') {
        // AC8: another Lead assigned it first. Close the dialog, say who got it, and reload, so
        // the event leaves the queue and the winner's count is current.
        setAssigning(null)
        setConflict(formatApiError(err))
        await reloadQueue(assigning.id)
      } else {
        setAssignError(formatApiError(err))
      }
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="page page-wide unassigned-queue">
      <p className="eyebrow">Events</p>
      <PageHeader
        title={QUEUE_LABEL}
        subtitle="Submitted requests waiting for an Event Coordinator, oldest first."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading the unassigned queue…" />}
      {conflict && (
        <p role="alert" className="error">
          {conflict}
        </p>
      )}

      {queue !== null && (
        <div className="stack">
          {!hasCoordinators && (
            <p className="warning">
              No Event Coordinator is active, so events cannot be assigned yet.
            </p>
          )}

          {queue.events.length === 0 && (
            <EmptyState>No events are waiting for a coordinator.</EmptyState>
          )}

          {queue.events.length > 0 && (
            <EventCardGrid label={QUEUE_LABEL}>
              {queue.events.map((entry) => (
                <EventCard
                  key={entry.id}
                  title={entry.name}
                  imageUrl={null}
                  to={eventPath(entry.id)}
                  state={BACK_TO_QUEUE}
                  details={[
                    formatSchedule(entry.starts_at, entry.ends_at),
                    `${entry.expected_attendance} people`,
                    `Requested by ${entry.organiser_name}`,
                    `Submitted ${entry.submitted_at ? formatDateTime(entry.submitted_at) : NOT_RECORDED}`,
                  ]}
                  action={
                    <button
                      type="button"
                      className="brand"
                      disabled={!hasCoordinators}
                      onClick={() => askToAssign(entry)}
                    >
                      Assign
                    </button>
                  }
                />
              ))}
            </EventCardGrid>
          )}
        </div>
      )}

      {assigning !== null && queue !== null && (
        <ConfirmDialog
          title={`Assign "${assigning.name}"?`}
          confirmLabel="Assign"
          tone="primary"
          isBusy={isSaving}
          error={assignError}
          onConfirm={confirmAssign}
          onCancel={cancelAssign}
        >
          <p>The coordinator and the organiser are both told.</p>
          <CoordinatorPicker
            label="Coordinator"
            coordinators={queue.coordinators}
            value={selectedCoordinatorId}
            onChange={setSelectedCoordinatorId}
          />
        </ConfirmDialog>
      )}
    </div>
  )
}
