/**
 * Story 1.2 AC1: the permission codes a role can hold, mirrored by hand from
 * backend/app/auth/permissions.py, which is the source of truth. A code renamed on one side fails
 * silently (the nav item simply disappears), so grep both sides when changing one.
 */
export const PERMISSIONS = {
  VENUES_READ: 'venues:read',
  VENUES_MANAGE: 'venues:manage',
  VENUE_UNAVAILABILITY_MANAGE: 'venue_unavailability:manage',
  VENUE_CALENDAR_READ: 'venue_calendar:read',
  EVENTS_CREATE: 'events:create',
  EVENTS_READ_OWN: 'events:read_own',
  EVENTS_READ_ALL: 'events:read_all',
  EVENTS_REVIEW: 'events:review',
  EVENTS_EDIT_ROUTINE: 'events:edit_routine',
  EVENTS_CANCEL: 'events:cancel',
  EVENT_CHANGE_REQUESTS_CREATE: 'event_change_requests:create',
  EVENT_CHANGE_REQUESTS_DECIDE: 'event_change_requests:decide',
  BOOKINGS_READ: 'bookings:read',
  BOOKINGS_REQUEST: 'bookings:request',
  BOOKINGS_DECIDE: 'bookings:decide',
  EQUIPMENT_READ: 'equipment:read',
  EQUIPMENT_REQUEST: 'equipment:request',
  EQUIPMENT_MANAGE: 'equipment:manage',
  REGISTRATIONS_SELF: 'registrations:self',
  REGISTRATIONS_VIEW: 'registrations:view',
  NOTIFICATIONS_READ_OWN: 'notifications:read_own',
  USERS_READ_INTERNAL: 'users:read_internal',
} as const

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS]
