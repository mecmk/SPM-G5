/**
 * Story 1.2 - fe/be: enforce role-based access control.
 * AC1 each role has a defined set of permitted functions.
 * AC2 navigation outside the role's permitted set is not displayed to them.
 *     Team decision, 17 Sep 2026: everything inside it is listed in the sidebar and on the main
 *     page.
 * AC3 users can only view the functions permitted for their role.
 * AC4 direct URLs to functions outside the role are rejected.
 * AC5 a section no backlog story delivers is not listed, and its old address opens the main page
 *     (chore c9).
 * The API-level refusals (401/403) are backend cases: backend/tests/auth/test_rbac.py.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, expectSignedIn, signIn } from './support'

interface SidebarExpectation {
  role: string
  email: string
  visible: string[]
  hidden: string[]
}

const SIDEBAR_EXPECTATIONS: SidebarExpectation[] = [
  // c9 (1.2 AC5): an organiser raises and follows a change request on the event's page
  // (19.1 AC1), so unlike the coordinator they have no Change requests section.
  {
    role: 'organiser',
    email: ACCOUNTS.organiser,
    visible: ['My events', 'Registrations'],
    hidden: [
      'Manage venues',
      'Events inbox',
      'Upcoming events',
      'Venue catalogue',
      'Change requests',
    ],
  },
  {
    role: 'coordinator',
    email: ACCOUNTS.coordinator,
    visible: ['Events inbox', 'Change requests', 'Registrations', 'Venue catalogue'],
    // Story 15.1 AC1 (CL-041): equipment is requested from the event page, so there is no
    // separate Equipment requests section.
    hidden: [
      'Manage venues',
      'My events',
      'Booking Requests',
      'Equipment holds',
      'Request a venue',
      'Equipment requests',
      'Safety checks',
    ],
  },
  // Stories 5.4 and 5.5: the Lead works from the unassigned queue and the assignments overview.
  // c9 (1.2 AC5): they were the last role listing All events, which no story delivers.
  {
    role: 'coordinator lead',
    email: ACCOUNTS.lead,
    visible: ['Unassigned events', 'Assignments', 'Venue catalogue'],
    hidden: ['All events', 'Events inbox', 'My events', 'Booking Requests', 'Equipment requests'],
  },
  // c9 (1.2 AC5): no Venue Schedule section. The calendar is on each venue's page (9.1)
  // and on each booking request's (13.1.3).
  {
    role: 'venue staff',
    email: ACCOUNTS.venueStaff,
    visible: ['Venue catalogue', 'Booking Requests', 'Room layouts'],
    hidden: [
      'Manage venues',
      'Events inbox',
      'Equipment requests',
      'My events',
      'All events',
      'Venue Schedule',
    ],
  },
  // c9 (1.2 AC5): no Equipment holds section. Story 15.3 merged into the queue (15.2).
  {
    role: 'technical support',
    email: ACCOUNTS.techSupport,
    visible: ['Venue catalogue', 'Equipment requests', 'Equipment catalogue'],
    hidden: ['All events', 'Manage venues', 'Booking Requests', 'Equipment holds'],
  },
  // Story 21.1 AC1: the Safety Officer works from the safety queue, and reads venues in the
  // catalogue (venues:read).
  {
    role: 'safety officer',
    email: ACCOUNTS.safetyOfficer,
    visible: ['Safety checks', 'Venue catalogue'],
    hidden: [
      'All events',
      'Events inbox',
      'My events',
      'Booking Requests',
      'Equipment requests',
    ],
  },
  {
    role: 'attendee',
    email: ACCOUNTS.attendee,
    visible: ['Upcoming events', 'My registrations'],
    hidden: ['All events', 'Venue catalogue', 'My events', 'Registrations'],
  },
]

function mainNav(page: Page) {
  return page.getByRole('navigation', { name: 'Main' })
}

for (const expectation of SIDEBAR_EXPECTATIONS) {
  test(`1.2 AC1/AC2: the ${expectation.role} sidebar shows exactly their sections`, async ({
    page,
  }) => {
    await signIn(page, expectation.email)
    const nav = mainNav(page)

    for (const name of expectation.visible) {
      await expect(nav.getByRole('link', { name, exact: true })).toBeVisible()
    }
    for (const name of expectation.hidden) {
      await expect(nav.getByRole('link', { name, exact: true })).toHaveCount(0)
    }
  })
}

test('1.2 AC2: the main page lists every section from the sidebar', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  const main = page.getByRole('main')

  for (const name of ['Venue catalogue', 'Booking Requests', 'Room layouts']) {
    await expect(main.getByRole('heading', { name, exact: true })).toBeVisible()
  }
  const sidebarLinks = await mainNav(page).getByRole('link').count()
  // The sidebar also links to the main page itself.
  await expect(main.getByRole('link')).toHaveCount(sidebarLinks - 1)
})

test('1.2 AC3: a page inside the role opens normally', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)

  await mainNav(page).getByRole('link', { name: 'Venue catalogue', exact: true }).click()

  await expect(page).toHaveURL(/\/venues$/)
  await expect(page.getByRole('heading', { name: 'Venue catalogue', level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Not permitted' })).toHaveCount(0)
})

test('1.2 AC4: a direct URL outside the role shows Not permitted', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await expectSignedIn(page)

  await page.goto('/venues/manage')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Venue catalogue' })).toHaveCount(0)
})

// c9 (1.2 AC5): the address of each section removed, with the role that was offered it. Stories
// 19.4 and 17.3 bring back the first and the last: each drops its row when it ships.
const RETIRED_SECTIONS = [
  { role: 'an organiser', email: ACCOUNTS.organiser, address: '/change-requests' },
  { role: 'a coordinator lead', email: ACCOUNTS.lead, address: '/events/all' },
  { role: 'venue staff', email: ACCOUNTS.venueStaff, address: '/venue-staff/schedule' },
  { role: 'technical support', email: ACCOUNTS.techSupport, address: '/equipment/holds' },
]

for (const { role, email, address } of RETIRED_SECTIONS) {
  test(`1.2 AC5: ${address} opens the main page for ${role}`, async ({ page }) => {
    await signIn(page, email)
    await expectSignedIn(page)

    await page.goto(address)

    await expect(page).toHaveURL('/')
    await expect(page.getByRole('heading', { name: /^Welcome, /, level: 1 })).toBeVisible()
  })
}

test('1.2: the sidebar collapses to icons and remembers the choice', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  const nav = mainNav(page)
  await expect(nav.getByText('Venue catalogue', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Collapse sidebar' }).click()

  await expect(page.getByRole('button', { name: 'Expand sidebar' })).toBeVisible()
  await expect(nav.getByText('Venue catalogue', { exact: true })).toBeHidden()
  await expect(nav.getByRole('link', { name: 'Venue catalogue', exact: true })).toBeVisible()

  await page.reload()
  await expect(page.getByRole('button', { name: 'Expand sidebar' })).toBeVisible()
})

test('1.2: on a phone the sidebar opens as a drawer and closes after choosing', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 })
  await signIn(page, ACCOUNTS.venueStaff)
  await expectSignedIn(page)
  await expect(mainNav(page)).toHaveCount(0)

  await page.getByRole('button', { name: 'Open menu' }).click()
  await mainNav(page).getByRole('link', { name: 'Venue catalogue', exact: true }).click()

  await expect(page).toHaveURL(/\/venues$/)
  await expect(mainNav(page)).toHaveCount(0)
})
