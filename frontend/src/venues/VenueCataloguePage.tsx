import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { formatApiError } from '../api/client'
import { listVenues, type VenueSummary } from '../api/venues'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { LoadingState } from '../layout/LoadingState'
import { venuePath } from '../routes'

function numberOrNull(value: string): number | null {
  const parsed = Number(value)
  return value.trim() === '' || !Number.isFinite(parsed) ? null : parsed
}

function matchesCapacity(venue: VenueSummary, minCapacity: string, maxCapacity: string): boolean {
  const min = numberOrNull(minCapacity)
  const max = numberOrNull(maxCapacity)
  return (min === null || venue.capacity >= min) && (max === null || venue.capacity <= max)
}

/**
 * Story 8.1: an Event Coordinator browses venues in service. AC1 name/location/capacity, AC2 a
 * link to the full record, AC3 withdrawn venues excluded. The capacity range filter (team
 * decision, 17 Sep 2026, frontend design prototype) is applied client-side, the same way story
 * 8.3's Venue Staff list filters by capacity.
 */
export function VenueCataloguePage() {
  const [venues, setVenues] = useState<VenueSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [minCapacity, setMinCapacity] = useState('')
  const [maxCapacity, setMaxCapacity] = useState('')

  useEffect(() => {
    let cancelled = false
    listVenues(false)
      .then((data) => {
        if (!cancelled) setVenues(data)
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const shownVenues = useMemo(
    () => (venues ?? []).filter((venue) => matchesCapacity(venue, minCapacity, maxCapacity)),
    [venues, minCapacity, maxCapacity],
  )

  const isFiltered = minCapacity !== '' || maxCapacity !== ''

  function clearFilters() {
    setMinCapacity('')
    setMaxCapacity('')
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Venue catalogue"
        subtitle="Venues currently in service. Select one to see its full record."
      />

      <div className="catalogue-layout">
        <aside className="filter-column">
          <label>
            Capacity from
            <input
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              placeholder="Any"
              value={minCapacity}
              onChange={(e) => setMinCapacity(e.target.value)}
            />
          </label>
          <label>
            Capacity to
            <input
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              placeholder="Any"
              value={maxCapacity}
              onChange={(e) => setMaxCapacity(e.target.value)}
            />
          </label>
          {isFiltered && (
            <button type="button" className="link" onClick={clearFilters}>
              Clear all filters
            </button>
          )}
        </aside>

        <div className="stack">
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {venues === null && !error && <LoadingState label="Loading venues…" />}

          {venues !== null && venues.length === 0 && (
            <EmptyState>No venues are currently in service.</EmptyState>
          )}

          {venues !== null && venues.length > 0 && shownVenues.length === 0 && (
            <EmptyState>No venues match these filters.</EmptyState>
          )}

          {shownVenues.length > 0 && (
            <>
              <p className="small muted">
                Showing {shownVenues.length} of {venues?.length ?? 0} venues
              </p>
              <div className="item-grid item-grid-2">
                {shownVenues.map((venue) => (
                  <article key={venue.id} className="item-card">
                    <div className="item-card-picture" aria-hidden="true">
                      <Icon name="building" size={28} />
                    </div>
                    <div className="item-card-body">
                      <div className="item-card-header">
                        <div>
                          <h3 className="item-card-title">
                            <Link to={venuePath(venue.id)}>{venue.name}</Link>
                          </h3>
                          <p className="small muted">{venue.location}</p>
                        </div>
                        <div className="item-card-capacity">
                          <div className="item-card-capacity-value">{venue.capacity}</div>
                          <div className="item-card-capacity-label">capacity</div>
                        </div>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
