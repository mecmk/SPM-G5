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

/** Mirrors `VenueSummary`: one row of the venue list. Story 8.3 AC6: `cover_image_url` is the
 * venue's first picture, for its card; null shows the placeholder. Load it through `mediaUrl`. */
export interface VenueSummary {
  id: string
  name: string
  location: string
  capacity: number
  status: VenueStatus
  cover_image_url: string | null
}

/** Mirrors `VenueImageOut`: one of a venue's pictures (story 8.3 AC5/AC6). `url` is where the
 * backend serves it; load it through `mediaUrl`. */
export interface VenueImage {
  id: string
  url: string
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
  /** Story 8.3 AC6: the venue's pictures in their order; the first is `cover_image_url`. */
  images: VenueImage[]
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

const VENUE_IMAGE_ERROR_CODES = {
  404: 'VENUE_NOT_FOUND',
  409: 'VENUE_PICTURES_TOO_MANY',
  413: 'VENUE_PICTURE_TOO_LARGE',
  422: 'VENUE_PICTURE_TYPE_INVALID',
} as const

/**
 * Story 8.3 AC5: add a picture after the venue's others. It is sent as part of saving the venue,
 * whose own notice ("Venue created" or "Venue updated") covers it, so it adds no notice of its
 * own - one save, one notice, as 2.1 AC15 does with an event's picture. The form shows a refusal.
 */
export function addVenueImage(venueId: string, file: File): Promise<Venue> {
  const body = new FormData()
  body.append('file', file)
  return api<Venue>(`/venues/${venueId}/images`, {
    method: 'POST',
    body,
    errorCodes: VENUE_IMAGE_ERROR_CODES,
    notify: false,
  })
}

/** Story 8.3 AC5: take a picture off a venue. Silent for the reason `addVenueImage` gives. */
export function removeVenueImage(venueId: string, imageId: string): Promise<Venue> {
  return api<Venue>(`/venues/${venueId}/images/${imageId}`, {
    method: 'DELETE',
    errorCodes: { 404: 'VENUE_NOT_FOUND' },
    notify: false,
  })
}

/**
 * Story 8.3 AC5: put a venue's pictures in a new order, naming every one of them once; the first
 * becomes the cover. Silent for the reason `addVenueImage` gives. AC10: refused (409) when the
 * venue's pictures changed since the order was made.
 */
export function reorderVenueImages(venueId: string, imageIds: string[]): Promise<Venue> {
  return api<Venue>(`/venues/${venueId}/images/order`, {
    method: 'PUT',
    body: { image_ids: imageIds },
    errorCodes: { 404: 'VENUE_NOT_FOUND', 409: 'VENUE_PICTURES_CHANGED' },
    notify: false,
  })
}

/** Story 8.1 AC12: Venue Staff can delete a venue that has no bookings. */
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

/** Mirrors `VenueSearchQuery`: the filters of `GET /venues/search` (story 8.1, Sprint 2).
 * `starts_at` / `ends_at` are instants with their offset; send both or neither. */
export interface VenueSearchQuery {
  search?: string
  capacity?: number
  capacity_max?: number
  starts_at?: string
  ends_at?: string
  layout?: string
  facility?: readonly string[]
  accessibility?: readonly string[]
  include_withdrawn?: boolean
  /** Story 11.1 AC1: the event to judge each result against. The catalogue sends it only once the
   * event in its address is one the user may request a venue for. */
  event?: string
}

/** Mirrors `Criterion` in backend/app/venues/suitability.py: what a failed criterion is about. */
export type SuitabilityCriterion =
  'CAPACITY' | 'LAYOUT' | 'FACILITY' | 'FACILITY_QUANTITY' | 'ACCESSIBILITY'

/** Mirrors `Outcome`: UNKNOWN when the venue has not recorded it - never treated as met (AC5). */
export type SuitabilityOutcome = 'NOT_MET' | 'UNKNOWN'

/** Mirrors `FailedCriterionOut`: one criterion a venue fails, with the requirement's value
 * (`required`) and the venue's (`venue_value`) where it has numbers. For CAPACITY, `code` and
 * `name` are the layout whose capacity was compared, or null for the venue's maximum. */
export interface FailedCriterion {
  criterion: SuitabilityCriterion
  outcome: SuitabilityOutcome
  code: string | null
  name: string | null
  required: number | null
  venue_value: number | null
}

/** Mirrors `VenueSuitabilityOut` (story 11.1 AC1/AC3): whether a venue suits the venue
 * requirement it was judged against. The requirement is null for an event with none. */
export interface VenueSuitability {
  requirement_id: string | null
  requirement_name: string | null
  is_suitable: boolean
  failures: FailedCriterion[]
}

/** Mirrors `VenueSearchHit`: a venue the search found. Its hours are "HH:MM:SS", or null when
 * not recorded - such a venue is kept when a period is searched (story 8.1 AC3). Story 11.1:
 * `suitability` is null outside event context and for anyone but the event's coordinator. */
export interface VenueSearchHit extends VenueSummary {
  operating_hours_start: string | null
  operating_hours_end: string | null
  suitability: VenueSuitability | null
}

/** The filter groups a search can relax (story 8.1 AC9); `SEARCH_GROUP_LABELS` in
 * backend/app/venues/service.py. */
export type RelaxFilter =
  'search' | 'capacity' | 'dates' | 'layout' | 'facilities' | 'accessibility'

/** Mirrors `RelaxHint`: a filter group whose removal alone would give results, and how many. */
export interface RelaxHint {
  filter: RelaxFilter
  label: string
  count: number
}

/** Mirrors `VenueSearchResult`. `total` counts every venue searched through, for "Showing N of
 * M"; `relax` is filled only when nothing matched. */
export interface VenueSearchResult {
  venues: VenueSearchHit[]
  total: number
  relax: RelaxHint[]
}

/** Story 11.1 AC2/AC3: whether one venue suits the event it is being requested for, with every
 * criterion it fails - the request step's read. Only the event's assigned coordinator may ask; an
 * event that cannot be judged is refused with a 422 whose sentence says why. */
export function getVenueSuitability(venueId: string, eventId: string): Promise<VenueSuitability> {
  const params = new URLSearchParams({ event: eventId })
  return api<VenueSuitability>(`/venues/${venueId}/suitability?${params}`)
}

/** Story 8.1 AC3/AC4: the catalogue's search, run on the server. A search that cannot be run
 * (AC8) is refused with a 422 whose sentence says why. */
export function searchVenues(query: VenueSearchQuery): Promise<VenueSearchResult> {
  const params = new URLSearchParams()
  if (query.search) params.set('search', query.search)
  if (query.capacity !== undefined) params.set('capacity', String(query.capacity))
  if (query.capacity_max !== undefined) params.set('capacity_max', String(query.capacity_max))
  if (query.starts_at) params.set('starts_at', query.starts_at)
  if (query.ends_at) params.set('ends_at', query.ends_at)
  if (query.layout) params.set('layout', query.layout)
  for (const code of query.facility ?? []) params.append('facility', code)
  for (const code of query.accessibility ?? []) params.append('accessibility', code)
  if (query.include_withdrawn) params.set('include_withdrawn', 'true')
  if (query.event) params.set('event', query.event)
  return api<VenueSearchResult>(`/venues/search?${params}`)
}

/** Sentinel `reason` values for a booking on the calendar: an approved booking (BOOKED) and a
 * pending request that holds the venue (HELD, story 9.1 AC2). Neither is one of
 * venue_unavailability_periods' own reason codes (MAINTENANCE, RENOVATION, SAFETY, INTERNAL_USE,
 * OTHER). Mirror BOOKING_REASON and HELD_REASON in backend/app/venues/schemas.py. */
export const BOOKING_REASON = 'BOOKED'
export const HELD_REASON = 'HELD'

/** Mirrors `VenueUnavailableWindowOut` (story 9.1). One blocked period - a flat list, not
 * pre-expanded per day. `starts_at` / `ends_at` are the period the venue is blocked: for a
 * booking, its held period, setup and teardown included. `booking_starts_at` / `booking_ends_at`
 * (AC5) are the booking's own requested period inside it - which may cover only part of its
 * event's own schedule - null for a closure. */
export interface VenueUnavailableWindow {
  starts_at: string
  ends_at: string
  booking_starts_at: string | null
  booking_ends_at: string | null
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
