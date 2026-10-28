import { useState } from 'react'
import { formatApiError } from '../api/client'
import { listRoomLayouts, type RoomLayout } from '../api/venues'
import { useAuth } from '../auth/authContext'
import { PERMISSIONS } from '../auth/permissions'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { LoadingState } from '../layout/LoadingState'
import { useLoaded } from '../shared/useLoaded'
import { DeleteRoomLayoutDialog } from './DeleteRoomLayoutDialog'
import { RoomLayoutDialog } from './RoomLayoutDialog'

const PAGE_TITLE = 'Room layouts'

/** Which dialog is open: adding a layout, or changing or deleting one. */
type OpenDialog =
  { kind: 'add' } | { kind: 'edit'; layout: RoomLayout } | { kind: 'delete'; layout: RoomLayout }

/**
 * Story 8.6 - the room layouts venues can offer. AC1: every layout with its name and description,
 * in the server's order: the standard ones first, then the others from A to Z. AC9: every role
 * that reads venues sees the list; only Venue Staff (venues:manage) get Add layout, and Edit and
 * Delete on each layout (AC2-AC4). The server refuses everyone else regardless. After a change, or
 * a refusal that found a layout deleted elsewhere (AC12), the list is read again.
 */
export function RoomLayoutsPage() {
  const { can } = useAuth()
  const canManage = can(PERMISSIONS.VENUES_MANAGE)
  const { data: layouts, error, isLoading, setData: setLayouts } = useLoaded(listRoomLayouts)
  const [openDialog, setOpenDialog] = useState<OpenDialog | null>(null)
  const [reloadError, setReloadError] = useState<string | null>(null)

  /** The list in the server's order again. A failed read is shown on the page, since the dialog
   *  that asked for it may have closed. */
  async function reloadLayouts() {
    setReloadError(null)
    try {
      setLayouts(await listRoomLayouts())
    } catch (err) {
      setReloadError(formatApiError(err))
    }
  }

  function openAddDialog() {
    setOpenDialog({ kind: 'add' })
  }

  function closeDialog() {
    setOpenDialog(null)
  }

  /** AC2-AC4: the change is saved, so the dialog closes and the list shows it in its place. */
  function finishChange() {
    setOpenDialog(null)
    void reloadLayouts()
  }

  return (
    <div className="stack">
      <PageHeader
        title={PAGE_TITLE}
        subtitle={
          canManage
            ? 'Add, rename and delete the room layouts venues can offer. Venue records, event requests and the catalogue’s filter offer these.'
            : 'The room layouts venues can offer and events can ask for. Venue Staff keep this list.'
        }
        action={
          canManage ? (
            <button type="button" className="button-with-icon" onClick={openAddDialog}>
              <Icon name="plus" size={16} /> Add layout
            </button>
          ) : undefined
        }
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {reloadError && (
        <p role="alert" className="error">
          {reloadError}
        </p>
      )}
      {isLoading && <LoadingState label="Loading room layouts…" />}
      {layouts !== null && layouts.length === 0 && (
        <EmptyState>There are no room layouts yet.</EmptyState>
      )}
      {layouts !== null && layouts.length > 0 && (
        <ul className="stack queue-list" aria-label={PAGE_TITLE}>
          {layouts.map((layout) => (
            <li key={layout.code} className="card card-tight">
              <div className="item-card-header">
                <div>
                  <h2 className="item-card-title">{layout.name}</h2>
                  <p className="small muted">{layout.description ?? 'No description.'}</p>
                </div>
                {canManage && (
                  <div className="row-actions">
                    <button
                      type="button"
                      className="secondary button-sm button-with-icon"
                      aria-label={`Edit ${layout.name}`}
                      onClick={() => setOpenDialog({ kind: 'edit', layout })}
                    >
                      <Icon name="pencil" size={14} /> Edit
                    </button>
                    <button
                      type="button"
                      className="danger button-sm button-with-icon"
                      aria-label={`Delete ${layout.name}`}
                      onClick={() => setOpenDialog({ kind: 'delete', layout })}
                    >
                      <Icon name="trash" size={14} /> Delete
                    </button>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {openDialog?.kind === 'add' && (
        <RoomLayoutDialog
          layout={null}
          onSaved={finishChange}
          onCancel={closeDialog}
          onGone={reloadLayouts}
        />
      )}
      {openDialog?.kind === 'edit' && (
        <RoomLayoutDialog
          layout={openDialog.layout}
          onSaved={finishChange}
          onCancel={closeDialog}
          onGone={reloadLayouts}
        />
      )}
      {openDialog?.kind === 'delete' && (
        <DeleteRoomLayoutDialog
          layout={openDialog.layout}
          onDeleted={finishChange}
          onCancel={closeDialog}
          onGone={reloadLayouts}
        />
      )}
    </div>
  )
}
