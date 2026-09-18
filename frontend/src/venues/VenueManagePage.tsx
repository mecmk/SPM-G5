import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { formatApiError } from '../api/client'
import { deleteVenue, listVenues, type VenueSummary } from '../api/venues'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { VENUE_NEW_PATH, venueEditPath } from '../routes'

const STATUS_LABELS: Record<VenueSummary['status'], string> = {
  ACTIVE: 'In service',
  WITHDRAWN: 'Withdrawn',
}

function matchesFilters(venue: VenueSummary, search: string, minimumCapacity: string): boolean {
  const term = search.trim().toLowerCase()
  const isSearchMatch =
    term === '' ||
    venue.name.toLowerCase().includes(term) ||
    venue.location.toLowerCase().includes(term)
  const minimum = Number(minimumCapacity)
  const hasMinimum = minimumCapacity.trim() !== '' && Number.isFinite(minimum)
  return isSearchMatch && (!hasMinimum || venue.capacity >= minimum)
}

/**
 * Story 8.3: the Venue Staff entry point. Find a venue, then create, edit or delete one (delete,
 * search and the capacity filter: team decision, 17 Sep 2026).
 */
export function VenueManagePage() {
  const [venues, setVenues] = useState<VenueSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isShowingWithdrawn, setIsShowingWithdrawn] = useState(false)
  const [search, setSearch] = useState('')
  const [minimumCapacity, setMinimumCapacity] = useState('')
  const [pendingDelete, setPendingDelete] = useState<VenueSummary | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  useEffect(() => {
    let cancelled = false
    listVenues(isShowingWithdrawn)
      .then((data) => {
        if (cancelled) return
        setVenues(data)
        setError(null)
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [isShowingWithdrawn])

  const shownVenues = useMemo(
    () => (venues ?? []).filter((venue) => matchesFilters(venue, search, minimumCapacity)),
    [venues, search, minimumCapacity],
  )

  function clearFilters() {
    setSearch('')
    setMinimumCapacity('')
  }

  function askToDelete(venue: VenueSummary) {
    setDeleteError(null)
    setPendingDelete(venue)
  }

  function cancelDelete() {
    setPendingDelete(null)
  }

  async function confirmDelete() {
    if (!pendingDelete) return
    const { id, name } = pendingDelete
    setIsDeleting(true)
    setDeleteError(null)
    try {
      await deleteVenue(id, name)
      setVenues((current) => current && current.filter((venue) => venue.id !== id))
      setPendingDelete(null)
    } catch (err) {
      setDeleteError(formatApiError(err))
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <div className="page page-wide">
      <p className="eyebrow">Venue catalogue</p>
      <PageHeader
        title="Manage venues"
        subtitle="Keep the venue records accurate. Coordinators plan every event against them."
        action={
          <Link to={VENUE_NEW_PATH} className="button button-with-icon">
            <Icon name="plus" size={16} /> New venue
          </Link>
        }
      />

      <div className="stack">
        <div className="filter-bar">
          <label className="filter-grow">
            Search venues
            <input
              type="search"
              placeholder="Name or location"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <label>
            Minimum capacity
            <input
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              placeholder="Any"
              value={minimumCapacity}
              onChange={(e) => setMinimumCapacity(e.target.value)}
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={isShowingWithdrawn}
              onChange={(e) => setIsShowingWithdrawn(e.target.checked)}
            />
            Show withdrawn venues
          </label>
        </div>

        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {venues === null && !error && <LoadingState label="Loading venues…" />}

        {venues !== null && venues.length === 0 && (
          <EmptyState>
            No venues recorded yet. <Link to={VENUE_NEW_PATH}>Add the first venue</Link> so
            coordinators can plan with it.
          </EmptyState>
        )}

        {venues !== null && venues.length > 0 && shownVenues.length === 0 && (
          <EmptyState>
            No venues match these filters.{' '}
            <button type="button" className="link" onClick={clearFilters}>
              Clear filters
            </button>
          </EmptyState>
        )}

        {shownVenues.length > 0 && (
          <div className="card table-card">
            <p className="table-summary">
              Showing {shownVenues.length} of {venues?.length ?? 0} venues
            </p>
            <div className="table-wrap">
              <table>
                <caption className="visually-hidden">Venues</caption>
                <thead>
                  <tr>
                    <th scope="col">Venue</th>
                    <th scope="col">Location</th>
                    <th scope="col" className="num">
                      Capacity
                    </th>
                    <th scope="col">Status</th>
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {shownVenues.map((venue) => (
                    <tr key={venue.id}>
                      <td className="cell-strong">{venue.name}</td>
                      <td>{venue.location}</td>
                      <td className="num mono">{venue.capacity}</td>
                      <td>
                        <StatusBadge status={venue.status} label={STATUS_LABELS[venue.status]} />
                      </td>
                      <td className="num">
                        <div className="row-actions">
                          <Link
                            to={venueEditPath(venue.id)}
                            className="button secondary button-sm button-with-icon"
                          >
                            <Icon name="pencil" size={14} /> Edit
                          </Link>
                          <button
                            type="button"
                            className="danger button-sm button-with-icon"
                            onClick={() => askToDelete(venue)}
                          >
                            <Icon name="trash" size={14} /> Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {pendingDelete && (
        <ConfirmDialog
          title={`Delete ${pendingDelete.name}?`}
          confirmLabel="Delete venue"
          isBusy={isDeleting}
          error={deleteError}
          onConfirm={confirmDelete}
          onCancel={cancelDelete}
        >
          <p>
            This removes the venue with its facilities, layouts and accessibility details. It cannot
            be undone.
          </p>
          <p className="muted">
            A venue with bookings cannot be deleted. Withdraw it from service instead.
          </p>
        </ConfirmDialog>
      )}
    </div>
  )
}
