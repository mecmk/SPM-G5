import { PERMISSIONS, type Permission } from '../auth/permissions'
import type { IconName } from '../components/Icon'
import {
  BOOKING_REQUESTS_PATH,
  CHANGE_REQUEST_QUEUE_PATH,
  CHANGE_REQUESTS_TITLE,
  EQUIPMENT_CATALOGUE_PATH,
  EQUIPMENT_CATALOGUE_TITLE,
  EQUIPMENT_REQUESTS_PATH,
  EVENTS_INBOX_PATH,
  EVENTS_UNASSIGNED_PATH,
  EVENTS_ASSIGNMENTS_PATH,
  EVENTS_MINE_PATH,
  REGISTRATIONS_REPORT_PATH,
  ROOM_LAYOUTS_PATH,
  SAFETY_CHECKS_PATH,
  UPCOMING_EVENTS_PATH,
  MY_CHANGE_REQUESTS_PATH,
  MY_REGISTRATIONS_PATH,
  PROFILE_PATH,
  VENUE_CATALOGUE_PATH,
} from '../routes'

/**
 * Story 1.2 AC1/AC2: every section of the app, and the permission a role needs to see it.
 *
 * The sidebar and the main page are both built from this list, so a role sees everything it can
 * use and nothing else (team decision, 17 Sep 2026). A section is listed only once a backlog story
 * delivers its page (1.2 AC5): the story that builds the page adds its item here and its route in
 * App.tsx. A story that puts the work on another page adds no item.
 */
export interface NavItem {
  /** Route path, unique across the app. */
  to: string
  label: string
  description: string
  icon: IconName
  /** Shown only to roles holding this permission. */
  permission: Permission
  /** Backlog story that delivers the page. */
  story: string
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
        to: EVENTS_MINE_PATH,
        label: 'My events',
        description: 'Your requests, drafts and their progress. Start a new request from here.',
        icon: 'calendar',
        permission: PERMISSIONS.EVENTS_READ_OWN,
        story: '2.6',
      },
      {
        to: EVENTS_INBOX_PATH,
        label: 'Events inbox',
        description: 'Requests assigned to you that are waiting for your decision.',
        icon: 'inbox',
        permission: PERMISSIONS.EVENTS_REVIEW,
        story: '4.1',
      },
      {
        to: EVENTS_UNASSIGNED_PATH,
        label: 'Unassigned events',
        description: 'Submitted requests waiting for a coordinator. Assign each one from here.',
        icon: 'inbox',
        permission: PERMISSIONS.EVENTS_ASSIGN,
        story: '5.4',
      },
      {
        to: EVENTS_ASSIGNMENTS_PATH,
        label: 'Assignments',
        description: 'Every active event and who coordinates it, to balance the team’s workload.',
        icon: 'people',
        permission: PERMISSIONS.EVENTS_ASSIGN,
        story: '5.5',
      },
      // Story 19.4: the organiser's change requests across all their events, added back after
      // c9 removed the placeholder (decided 2 Nov 2026). Raising and withdrawing one stays on the
      // event's page (19.1).
      {
        to: MY_CHANGE_REQUESTS_PATH,
        label: CHANGE_REQUESTS_TITLE,
        description: 'Every change you have asked for on your events, and where each one stands.',
        icon: 'swap',
        permission: PERMISSIONS.EVENT_CHANGE_REQUESTS_CREATE,
        story: '19.4',
      },
      {
        to: CHANGE_REQUEST_QUEUE_PATH,
        label: CHANGE_REQUESTS_TITLE,
        description: 'Changes organisers have asked for on your events, waiting for your decision.',
        icon: 'swap',
        permission: PERMISSIONS.EVENT_CHANGE_REQUESTS_DECIDE,
        story: '19.2',
      },
      {
        to: REGISTRATIONS_REPORT_PATH,
        label: 'Registrations',
        description: 'Who has registered for the events you manage.',
        icon: 'people',
        permission: PERMISSIONS.REGISTRATIONS_VIEW,
        story: '18.3',
      },
    ],
  },
  {
    label: 'Venues',
    items: [
      // f8.1.1 (8.1 AC12): one catalogue for every role that reads venues. Venue Staff also
      // create, update and remove venues there, so there is no separate "Manage venues" section.
      {
        to: VENUE_CATALOGUE_PATH,
        label: 'Venue catalogue',
        description: 'Browse venues and compare capacity, layouts and availability.',
        icon: 'building',
        permission: PERMISSIONS.VENUES_READ,
        story: '8.1',
      },
      // f12.1.1: no "Request a venue" section. A venue is requested from its event: Find a venue
      // on the event's page, then Request this venue in the catalogue (12.1 AC15).
      {
        to: BOOKING_REQUESTS_PATH,
        label: 'Booking Requests',
        description: 'Venue booking requests to decide, and the decisions already made.',
        icon: 'calendar-check',
        permission: PERMISSIONS.BOOKINGS_DECIDE,
        story: '13.1',
      },
      // Story 8.6 AC1/AC9: every role that reads venues sees the room layouts; Venue Staff also
      // add, rename and delete them there.
      {
        to: ROOM_LAYOUTS_PATH,
        label: 'Room layouts',
        description: 'The room layouts venues can offer and events can ask for.',
        icon: 'grid',
        permission: PERMISSIONS.VENUES_READ,
        story: '8.6',
      },
      // c9 (1.2 AC5): no Venue Schedule section. The availability calendar is on each venue's
      // page (9.1) and on each booking request's (13.1.3).
    ],
  },
  {
    label: 'Equipment',
    items: [
      {
        to: EQUIPMENT_REQUESTS_PATH,
        label: 'Equipment requests',
        description: 'Equipment requests to work through, with what is available for each.',
        icon: 'inbox',
        permission: PERMISSIONS.EQUIPMENT_MANAGE,
        story: '15.2',
      },
      {
        to: EQUIPMENT_CATALOGUE_PATH,
        label: EQUIPMENT_CATALOGUE_TITLE,
        description: 'Stock levels, and the units out of service and until when.',
        icon: 'grid',
        permission: PERMISSIONS.EQUIPMENT_MANAGE,
        story: '16.2',
      },
    ],
  },
  {
    label: 'Safety',
    items: [
      {
        to: SAFETY_CHECKS_PATH,
        label: 'Safety checks',
        description: 'Events awaiting the operational safety check, with what affects each.',
        icon: 'check-circle',
        permission: PERMISSIONS.SAFETY_REVIEW,
        story: '21.1',
      },
    ],
  },
  {
    label: 'Attend',
    items: [
      {
        to: UPCOMING_EVENTS_PATH,
        label: 'Upcoming events',
        description: 'Browse confirmed events and register for them.',
        icon: 'ticket',
        permission: PERMISSIONS.REGISTRATIONS_SELF,
        story: '18.1',
      },
      {
        to: MY_REGISTRATIONS_PATH,
        label: 'My registrations',
        description: 'The events you have registered for, and your place at each.',
        icon: 'ticket',
        permission: PERMISSIONS.REGISTRATIONS_SELF,
        story: '18.2',
      },
      {
        to: PROFILE_PATH,
        label: 'My profile',
        description: 'Your phone number and dietary requirements, filled in when you register.',
        icon: 'person',
        permission: PERMISSIONS.REGISTRATIONS_SELF,
        story: '18.4',
      },
    ],
  },
]

/** Story 1.2 AC2: the sections, trimmed to the items the signed-in role may use. */
export function visibleNavSections(can: (permission: Permission) => boolean): NavSection[] {
  return NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => can(item.permission)),
  })).filter((section) => section.items.length > 0)
}
