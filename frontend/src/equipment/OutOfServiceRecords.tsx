import { useState } from 'react'
import { ApiError, formatApiError } from '../api/client'
import { endOutOfServiceNow, removeOutOfService, type OutOfServiceRecord } from '../api/equipment'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { StatusBadge } from '../components/StatusBadge'
import {
  REASON_LABELS,
  describeOutPeriod,
  describeUnitsOut,
  hasStarted,
} from './outOfServiceLabels'

/** What End does to a record: ends one in force now, or removes one not yet started. */
type Ending = { record: OutOfServiceRecord; action: 'end' | 'remove' }

export interface OutOfServiceRecordsProps {
  typeId: string
  typeName: string
  /** The type's current records, soonest first, as the server lists them. */
  records: OutOfServiceRecord[]
  /** When they were loaded, which labels each In force or Scheduled. */
  loadedAt: number
  /** Edit was pressed: the page opens its form on this record. */
  onEdit: (record: OutOfServiceRecord) => void
  /** A record was ended or removed, so the page loads the type again. */
  onChanged: () => void
}

/**
 * Story 16.2 AC2 - a type's current records: each one's units, reason, note and period, whether
 * it is in force or still to come, and Edit and End. End asks first: a record in force is ended
 * now, and one not yet started is removed, as it never took effect. The page's clock decides which
 * at the press, and the server decides again, so a press that races the start shows the server's
 * sentence in the dialog, and the list is loaded again once the dialog closes.
 */
export function OutOfServiceRecords({
  typeId,
  typeName,
  records,
  loadedAt,
  onEdit,
  onChanged,
}: OutOfServiceRecordsProps) {
  const [ending, setEnding] = useState<Ending | null>(null)
  const [isBusy, setIsBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isOutOfDate, setIsOutOfDate] = useState(false)

  function askToEnd(record: OutOfServiceRecord) {
    setError(null)
    setEnding({ record, action: hasStarted(record, Date.now()) ? 'end' : 'remove' })
  }

  function handleCancel() {
    setEnding(null)
    if (isOutOfDate) {
      setIsOutOfDate(false)
      onChanged()
    }
  }

  async function handleConfirm() {
    if (ending === null) return
    setIsBusy(true)
    setError(null)
    try {
      if (ending.action === 'end') await endOutOfServiceNow(typeId, typeName, ending.record.id)
      else await removeOutOfService(typeId, typeName, ending.record.id)
      setEnding(null)
      onChanged()
    } catch (err) {
      setError(formatApiError(err))
      // Gone (404) or no longer what the row showed (409): the list is loaded again on closing.
      if (err instanceof ApiError && (err.status === 404 || err.status === 409)) {
        setIsOutOfDate(true)
      }
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <section className="card stack" aria-labelledby="current-records-heading">
      <h2 id="current-records-heading">Current records</h2>
      {records.length === 0 ? (
        <EmptyState>No units are out of service.</EmptyState>
      ) : (
        <ul className="check-list out-of-service-records">
          {records.map((record) => (
            <RecordRow
              key={record.id}
              record={record}
              now={loadedAt}
              onEdit={onEdit}
              onEnd={askToEnd}
            />
          ))}
        </ul>
      )}

      {ending?.action === 'end' && (
        <ConfirmDialog
          title="End this record now?"
          confirmLabel="End now"
          tone="primary"
          isBusy={isBusy}
          error={error}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
        >
          <p>
            These {typeName} units are back in service from now. The record is kept up to this
            moment.
          </p>
        </ConfirmDialog>
      )}
      {ending?.action === 'remove' && (
        <ConfirmDialog
          title="Remove this record?"
          confirmLabel="Remove"
          isBusy={isBusy}
          error={error}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
        >
          <p>This record has not started, so it is removed: its units were never taken out.</p>
        </ConfirmDialog>
      )}
    </section>
  )
}

interface RecordRowProps {
  record: OutOfServiceRecord
  /** The page's clock when the list was drawn, which labels the record In force or Scheduled. */
  now: number
  onEdit: (record: OutOfServiceRecord) => void
  onEnd: (record: OutOfServiceRecord) => void
}

/** Story 16.2 AC2: one current record - its units, reason, note and period - with Edit and End. */
function RecordRow({ record, now, onEdit, onEnd }: RecordRowProps) {
  const isInForce = hasStarted(record, now)

  function handleEdit() {
    onEdit(record)
  }

  function handleEnd() {
    onEnd(record)
  }

  return (
    <li>
      <span className="grow-text">
        <strong>{describeUnitsOut(record.quantity)}</strong> · {REASON_LABELS[record.reason]}
        {record.notes && (
          <>
            <br />
            <span className="small">{record.notes}</span>
          </>
        )}
        <br />
        <span className="item-timing">{describeOutPeriod(record)}</span>
      </span>
      <StatusBadge
        status={isInForce ? 'warning' : 'info'}
        label={isInForce ? 'In force' : 'Scheduled'}
      />
      <span className="row-actions">
        <button type="button" className="secondary button-sm" onClick={handleEdit}>
          Edit
        </button>
        <button type="button" className="secondary button-sm" onClick={handleEnd}>
          End
        </button>
      </span>
    </li>
  )
}
