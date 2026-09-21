import { PERMISSIONS, type Permission } from '../auth/permissions'
import type { IconName } from '../components/Icon'
import {
  BOOKING_REQUEST_NEW_PATH,
  EVENT_NEW_PATH,
  EVENTS_INBOX_PATH,
  EVENTS_MINE_PATH,
  VENUES_MANAGE_PATH,
} from '../routes'

/**
 * Story 1.2 AC1/AC2: every section of the app, and the permission a role needs to see it.
 *
 * The sidebar and the main page are both built from this list, so a role sees everything it can
 * use and nothing else (team decision, 17 Sep 2026). A section whose page is still being built
 * is listed with `isAvailable: false` and opens a "coming soon" page naming its story; the story
 * that builds the page flips the flag and adds its own route in App.tsx.
 */
export interface NavItem {
  /** Route path, unique across the app. */
  to: string
  label: string
  description: string
  icon: IconName
  /** Shown only to roles holding this permission. */
  permission: Permission
  /** Hidden from roles that also hold this permission, because another item covers it. */
  hiddenWith?: Permission
  /** Backlog story that delivers the page. */
  story: string
  isAvailable: boolean
}

export interface NavSection {
  label: string
  items: NavItem[]
}

export const NAV_SECTIONS: NavSection[] = [
  {
    label: 'Events',
    items: [
      {
        to: EVENT_NEW_PATH,
        label: 'New event request',
        description:
          'Tell us about your event, the venue and accessibility it needs, and the equipment you want.',
        icon: 'plus',
        permission: PERMISSIONS.EVENTS_CREATE,
        story: '2.1',
        isAvailable: true,
      },
      {
        to: EVENTS_MINE_PATH,
        label: 'My events',
        description: 'Your requests, drafts and their progress. Start a new request from here.',
        icon: 'calendar',
        permission: PERMISSIONS.EVENTS_READ_OWN,
        story: '2.6',
        isAvailable: true,
      },
      {
        to: EVENTS_INBOX_PATH,
        label: 'Events inbox',
        description: 'Requests assigned to you that are waiting for your decision.',
        icon: 'inbox',
        permission: PERMISSIONS.EVENTS_REVIEW,
        story: '4.1',
        isAvailable: true,
      },
      {
        to: '/events/all',
        label: 'All events',
        description: 'Every event on record, to plan venues and equipment around.',
        icon: 'calendar',
        permission: PERMISSIONS.EVENTS_READ_ALL,
        hiddenWith: PERMISSIONS.EVENTS_REVIEW,
        story: '7.1',
        isAvailable: false,
      },
      {
        to: '/change-requests',
        label: 'Change requests',
        description: 'Ask for changes to a confirmed event and follow each decision.',
        icon: 'swap',
        permission: PERMISSIONS.EVENT_CHANGE_REQUESTS_CREATE,
        story: '19.1',
        isAvailable: false,
      },
      {
        to: '/change-requests/review',
        label: 'Change requests',
        description: 'Review requested changes against the event as it stands.',
        icon: 'swap',
        permission: PERMISSIONS.EVENT_CHANGE_REQUESTS_DECIDE,
        story: '19.2',
        isAvailable: false,
      },
      {
        to: '/registrations/report',
        label: 'Registrations',
        description: 'Who has registered for the events you manage.',
        icon: 'people',
        permission: PERMISSIONS.REGISTRATIONS_VIEW,
        story: '18.6',
        isAvailable: false,
      },
    ],
  },
  {
    label: 'Venues',
    items: [
      {
        to: '/venues',
        label: 'Venue catalogue',
        description: 'Browse venues and compare capacity, layouts and availability.',
        icon: 'building',
        permission: PERMISSIONS.VENUES_READ,
        hiddenWith: PERMISSIONS.VENUES_MANAGE,
        story: '8.1',
        isAvailable: true,
      },
      {
        to: VENUES_MANAGE_PATH,
        label: 'Manage venues',
        description: 'Create, update and remove the venue records everyone plans with.',
        icon: 'building',
        permission: PERMISSIONS.VENUES_MANAGE,
        story: '8.3',
        isAvailable: true,
      },
      {
        to: BOOKING_REQUEST_NEW_PATH,
        label: 'Request a venue',
        description: 'Ask Venue Staff to hold a venue for one of your approved events.',
        icon: 'calendar-check',
        permission: PERMISSIONS.BOOKINGS_REQUEST,
        story: '12.1',
        isAvailable: true,
      },
      {
        to: '/bookings',
        label: 'Bookings & schedule',
        description: 'Approve or reject venue booking requests.',
        icon: 'calendar-check',
        permission: PERMISSIONS.BOOKINGS_DECIDE,
        story: '13.1',
        isAvailable: false,
      },
    ],
  },
  {
    label: 'Equipment',
    items: [
      {
        to: '/equipment/requests',
        label: 'Equipment requests',
        description: 'Request equipment for your events. Available items are held straight away.',
        icon: 'box',
        permission: PERMISSIONS.EQUIPMENT_REQUEST,
        story: '15.1',
        isAvailable: false,
      },
      {
        to: '/equipment/holds',
        label: 'Equipment holds',
        description: 'Equipment held for upcoming events, releases and the waitlist.',
        icon: 'box',
        permission: PERMISSIONS.EQUIPMENT_MANAGE,
        story: '15.3',
        isAvailable: false,
      },
      {
        to: '/equipment/catalogue',
        label: 'Catalogue & availability',
        description: 'Stock levels, and how much is free for any date and time.',
        icon: 'grid',
        permission: PERMISSIONS.EQUIPMENT_MANAGE,
        story: '16.1',
        isAvailable: false,
      },
    ],
  },
  {
    label: 'Attend',
    items: [
      {
        to: '/browse',
        label: 'Upcoming events',
        description: 'Search confirmed events and register for them.',
        icon: 'ticket',
        permission: PERMISSIONS.REGISTRATIONS_SELF,
        story: '18.1',
        isAvailable: false,
      },
      {
        to: '/registrations',
        label: 'My registrations',
        description: 'The events you have registered for, and your place at each.',
        icon: 'ticket',
        permission: PERMISSIONS.REGISTRATIONS_SELF,
        story: '18.3',
        isAvailable: false,
      },
    ],
  },
]

export const NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((section) => section.items)

/** Story 1.2 AC2: the sections, trimmed to the items the signed-in role may use. */
export function visibleNavSections(can: (permission: Permission) => boolean): NavSection[] {
  return NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter(
      (item) => can(item.permission) && !(item.hiddenWith && can(item.hiddenWith)),
    ),
  })).filter((section) => section.items.length > 0)
}
