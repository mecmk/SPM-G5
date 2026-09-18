/** Route paths used by more than one file (frontend/STYLE.md: one constant per shared literal). */
export const HOME_PATH = '/'
export const LOGIN_PATH = '/login'

/** Story c3's component gallery, served in development builds only. */
export const COMPONENT_GALLERY_PATH = '/dev/components'

// Story 8.3: venue records.
export const VENUES_MANAGE_PATH = '/venues/manage'
export const VENUE_NEW_PATH = '/venues/new'
export const VENUE_EDIT_PATH = '/venues/:venueId/edit'

export function venueEditPath(venueId: string): string {
  return VENUE_EDIT_PATH.replace(':venueId', encodeURIComponent(venueId))
}
