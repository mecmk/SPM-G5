/**
 * Story 1.2 - fe/be: enforce role-based access control.
 * AC1 each role has a defined set of permitted functions.
 * AC2 navigation outside the role's permitted set is not displayed; everything inside it is
 *     listed in the sidebar and on the main page (team decision, 17 Sep 2026).
 * AC3 users can only view the functions permitted for their role.
 * AC4 direct URLs to functions outside the role are rejected.
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
  {
    role: 'organiser',
    email: ACCOUNTS.organiser,
    visible: ['My events', 'Change requests', 'Registrations'],
    hidden: ['Manage venues', 'Events inbox', 'Upcoming events', 'Venue catalogue'],
  },
  {
    role: 'coordinator',
    email: ACCOUNTS.coordinator,
    visible: ['Events inbox', 'Change requests', 'Registrations', 'Venue catalogue', 'Equipment requests'],
    hidden: ['Manage venues', 'My events', 'Bookings & schedule', 'Equipment holds'],
  },
  {
    role: 'venue staff',
    email: ACCOUNTS.venueStaff,
    visible: ['All events', 'Manage venues', 'Bookings & schedule'],
    hidden: ['Venue catalogue', 'Events inbox', 'Equipment requests', 'My events'],
  },
  {
    role: 'technical support',
    email: ACCOUNTS.techSupport,
    visible: ['All events', 'Venue catalogue', 'Equipment holds', 'Catalogue & availability'],
    hidden: ['Manage venues', 'Equipment requests', 'Bookings & schedule'],
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

  for (const name of ['All events', 'Manage venues', 'Bookings & schedule']) {
    await expect(main.getByRole('heading', { name, exact: true })).toBeVisible()
  }
  const sidebarLinks = await mainNav(page).getByRole('link').count()
  // The sidebar also links to the main page itself.
  await expect(main.getByRole('link')).toHaveCount(sidebarLinks - 1)
})

test('1.2 AC3: a page inside the role opens normally', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)

  await mainNav(page).getByRole('link', { name: 'Manage venues', exact: true }).click()

  await expect(page).toHaveURL(/\/venues\/manage$/)
  await expect(page.getByRole('heading', { name: 'Manage venues', level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Not permitted' })).toHaveCount(0)
})

test('1.2 AC4: a direct URL outside the role shows Not permitted', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await expectSignedIn(page)

  await page.goto('/venues/manage')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Manage venues' })).toHaveCount(0)
})

test('1.2: the sidebar collapses to icons and remembers the choice', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  const nav = mainNav(page)
  await expect(nav.getByText('Manage venues', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Collapse sidebar' }).click()

  await expect(page.getByRole('button', { name: 'Expand sidebar' })).toBeVisible()
  await expect(nav.getByText('Manage venues', { exact: true })).toBeHidden()
  await expect(nav.getByRole('link', { name: 'Manage venues', exact: true })).toBeVisible()

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
  await mainNav(page).getByRole('link', { name: 'Manage venues', exact: true }).click()

  await expect(page).toHaveURL(/\/venues\/manage$/)
  await expect(mainNav(page)).toHaveCount(0)
})
