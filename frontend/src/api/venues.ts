import { api } from './client'

/** Mirrors `ReferenceItem` in backend/app/venues/schemas.py. */
export interface ReferenceItem {
  code: string
  name: string
  description: string | null
}

/** Mirrors `VenueReferenceData`: the pick-lists for the venue form. */
export interface VenueReferenceData {
  facilities: ReferenceItem[]
  layouts: ReferenceItem[]
  accessibility_features: ReferenceItem[]
}

export type VenueStatus = 'ACTIVE' | 'WITHDRAWN'

/** Mirrors `VenueSummary`: one row of the venue list. */
export interface VenueSummary {
  id: string
  name: string
  location: string
  capacity: number
  status: VenueStatus
}

/** Mirrors `VenueFacilityOut`. */
export interface VenueFacility {
  code: string
  name: string
  quantity: number | null
  notes: string | null
}

/** Mirrors `VenueLayoutOut`. */
export interface VenueLayout {
  code: string
  name: string
  layout_capacity: number | null
}

/** Mirrors `VenueAccessibilityFeatureOut`. */
export interface VenueAccessibilityFeature {
  code: string
  name: string
  notes: string | null
}

/** Mirrors `VenueOut`. A null characteristic means "not recorded" (story 8.2 AC2). */
export interface Venue extends VenueSummary {
  description: string | null
  /** A decimal, serialised by the backend as a string, e.g. "120.50". */
  floor_area_sqm: string | null
  /** "HH:MM:SS". */
  operating_hours_start: string | null
  operating_hours_end: string | null
  operating_notes: string | null
  setup_minutes_default: number
  teardown_minutes_default: number
  facilities: VenueFacility[]
  layouts: VenueLayout[]
  accessibility_features: VenueAccessibilityFeature[]
  created_by_id: string | null
  created_at: string
  updated_at: string
}

/** Mirrors `VenueCreate` / `VenueUpdate`. On update, a list sent replaces the stored list. */
export interface VenueInput {
  name: string
  location: string
  capacity: number
  description: string | null
  floor_area_sqm: string | null
  operating_hours_start: string | null
  operating_hours_end: string | null
  operating_notes: string | null
  setup_minutes_default: number
  teardown_minutes_default: number
  facilities: { code: string; quantity: number | null; notes: string | null }[]
  layouts: { code: string; layout_capacity: number | null }[]
  accessibility_features: { code: string; notes: string | null }[]
  /** Update only (story 8.4 withdraws a venue). */
  status?: VenueStatus
}

export function fetchVenueReferenceData(): Promise<VenueReferenceData> {
  return api<VenueReferenceData>('/venues/reference-data')
}

export function listVenues(includeWithdrawn: boolean): Promise<VenueSummary[]> {
  return api<VenueSummary[]>(`/venues?include_withdrawn=${includeWithdrawn}`)
}

export function getVenue(venueId: string): Promise<Venue> {
  return api<Venue>(`/venues/${venueId}`, { errorCodes: { 404: 'VENUE_NOT_FOUND' } })
}

/** Story 8.3 AC1. */
export function createVenue(input: VenueInput): Promise<Venue> {
  return api<Venue>('/venues', {
    method: 'POST',
    body: input,
    errorCodes: { 409: 'VENUE_NAME_TAKEN' },
    notify: {
      title: 'Venue created',
      message: `${input.name} was added to the catalogue.`,
    },
  })
}

/** Story 8.3 AC2. */
export function updateVenue(venueId: string, input: VenueInput): Promise<Venue> {
  return api<Venue>(`/venues/${venueId}`, {
    method: 'PATCH',
    body: input,
    errorCodes: { 404: 'VENUE_NOT_FOUND', 409: 'VENUE_NAME_TAKEN' },
    notify: {
      title: 'Venue updated',
      message: `Changes to ${input.name} were saved.`,
    },
  })
}

/** Team decision, 17 Sep 2026: Venue Staff can delete a venue that has no bookings. */
export function deleteVenue(venueId: string, venueName: string): Promise<void> {
  return api<void>(`/venues/${venueId}`, {
    method: 'DELETE',
    errorCodes: { 404: 'VENUE_NOT_FOUND', 409: 'VENUE_IN_USE' },
    notify: {
      title: 'Venue deleted',
      message: `${venueName} was removed from the catalogue.`,
      importance: 'important',
    },
  })
}

/** Sentinel `reason` for an approved booking - distinct from venue_unavailability_periods' own
 * reason codes (MAINTENANCE, RENOVATION, SAFETY, INTERNAL_USE, OTHER). Mirrors BOOKING_REASON
 * in backend/app/venues/schemas.py. */
export const BOOKING_REASON = 'BOOKED'

/** Mirrors `VenueUnavailableWindowOut` (story 9.1). One blocked period - a flat list, not
 * pre-expanded per day. */
export interface VenueUnavailableWindow {
  starts_at: string
  ends_at: string
  reason: string
  label: string
}

/** Story 9.1 AC1/AC2. `startsAt`/`endsAt` are ISO datetimes covering the visible range. */
export function getVenueCalendar(
  venueId: string,
  startsAt: string,
  endsAt: string,
): Promise<VenueUnavailableWindow[]> {
  const params = new URLSearchParams({ starts_at: startsAt, ends_at: endsAt })
  return api<VenueUnavailableWindow[]>(`/venues/${venueId}/calendar?${params}`, {
    errorCodes: { 404: 'VENUE_NOT_FOUND' },
  })
}
