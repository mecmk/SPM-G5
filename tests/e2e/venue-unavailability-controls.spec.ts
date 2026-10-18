/**
 * Story 12.6 AC12 (PO decision): the venue unavailability ("block off time") controls live on the
 * Edit venue page, not the venue's details page.
 *
 * AC12 Venue Staff add, edit, end ("End now") and remove unavailable periods from the Edit venue
 *      page only. The details page, and the calendar on it (9.1), keep showing each period with
 *      its reason to every internal role, with no add, edit, end or remove control. Both pages
 *      are usable at 1280x720 and 390x844.
 *
 * Nothing about 9.4's rules changes - the overlap, the marking, what End now and Remove do - so
 * the steps that add, edit, end and remove are venue-unavailability.spec.ts's, which reaches them
 * through the Edit venue page. This file only says where the controls are and are not.
 *
 * Seed (backend/db/seed/020_sample_data.sql, "Story 12.6"): Exhibition Foyer is closed on 5
 * February 2029 for floor resurfacing, a closure no spec changes. The browser's clock is pinned to
 * the month before, as venue-unavailability.spec.ts pins its own, so the calendar opens on
 * February 2029; the server keeps real time, so the closure has not started and is one to Remove.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, signIn, venueCard } from './support'

test.use({ timezoneId: 'Asia/Singapore' })

const FOYER = 'Exhibition Foyer'
const PINNED_NOW = new Date('2029-02-01T10:00:00+08:00')
const CLOSURE_DAY = /^5 February 2029/
const CLOSURE_DESCRIPTION = 'Floor resurfacing'
const CLOSURE_LABEL = 'Unavailable – Maintenance'

const DESKTOP = { width: 1280, height: 720 }
const PHONE = { width: 390, height: 844 }

function availability(page: Page) {
  return page.getByRole('region', { name: 'Availability', exact: true })
}

function blockOff(page: Page) {
  return page.getByRole('region', { name: /^(Block off time|Edit blocked-off time)$/ })
}

/** The closure's row in the day's list, which holds its actions when there are any. */
function closureRow(page: Page) {
  return page.getByRole('listitem').filter({ hasText: CLOSURE_DESCRIPTION })
}

/** Venue Staff's Edit venue page for the foyer, from its card in the catalogue. */
async function openEditPage(page: Page) {
  await page.clock.setFixedTime(PINNED_NOW)
  await page.goto('/venues')
  await venueCard(page, FOYER).getByRole('link', { name: 'Edit' }).click()
  await expect(page).toHaveURL(/\/venues\/[0-9a-f-]{36}\/edit$/)
  await expect(availability(page)).toBeVisible()
  await expect(page.getByText('Loading availability…')).toHaveCount(0)
}

/** The foyer's details page, as any internal role opens it. */
async function openDetailsPage(page: Page) {
  await page.clock.setFixedTime(PINNED_NOW)
  await page.goto('/venues')
  await page.getByRole('link', { name: FOYER }).click()
  await expect(page).toHaveURL(/\/venues\/[0-9a-f-]{36}$/)
  await expect(availability(page)).toBeVisible()
  await expect(page.getByText('Loading availability…')).toHaveCount(0)
}

async function openClosureDay(page: Page) {
  await availability(page).getByRole('button', { name: CLOSURE_DAY }).click()
  await expect(closureRow(page)).toBeVisible()
}

/** Assert nothing runs off the side of the page, and `target` sits inside it. */
async function expectFitsPage(page: Page, target: Locator) {
  await expect(target).toBeVisible()
  const box = await target.boundingBox()
  const viewport = page.viewportSize()
  if (box === null || viewport === null) throw new Error('nothing to measure')
  expect(box.x).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

test('12.6 AC12: the controls are on the Edit venue page', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await openEditPage(page)

  // Add: the Block off time card and its button.
  await expect(blockOff(page).getByRole('button', { name: 'Block off time' })).toBeVisible()
  // Edit, and Remove (the closure has not started; End now is for one in force): on the day's row.
  await openClosureDay(page)
  await expect(closureRow(page).getByRole('button', { name: 'Edit' })).toBeVisible()
  await expect(closureRow(page).getByRole('button', { name: 'Remove' })).toBeVisible()
})

test('12.6 AC12: the details page shows the period and its reason but no controls', async ({
  page,
  browser,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await openDetailsPage(page)

  await openClosureDay(page)
  await expect(closureRow(page)).toContainText(CLOSURE_LABEL)
  await expect(closureRow(page)).toContainText(CLOSURE_DESCRIPTION)
  // Venue Staff, who have the controls elsewhere, have none here.
  await expect(page.getByRole('button', { name: 'Block off time' })).toHaveCount(0)
  await expect(blockOff(page)).toHaveCount(0)
  for (const control of ['Edit', 'End now', 'Remove']) {
    await expect(closureRow(page).getByRole('button', { name: control })).toHaveCount(0)
  }

  // Every other internal role sees the period and its reason, and no more than before.
  for (const email of [ACCOUNTS.coordinator, ACCOUNTS.safetyOfficer]) {
    const other = await browser
      .newContext({ timezoneId: 'Asia/Singapore' })
      .then((context) => context.newPage())
    await signIn(other, email)
    await openDetailsPage(other)
    await openClosureDay(other)
    await expect(closureRow(other)).toContainText(CLOSURE_LABEL)
    await expect(closureRow(other).getByRole('button')).toHaveCount(0)
    await other.context().close()
  }
})

for (const [size, viewport] of [
  ['1280x720', DESKTOP],
  ['390x844', PHONE],
] as const) {
  test(`12.6 AC12: the Edit venue page's controls and the details page's calendar are usable at ${size}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await signIn(page, ACCOUNTS.venueStaff)

    await openEditPage(page)
    await expectFitsPage(page, blockOff(page).getByRole('button', { name: 'Block off time' }))
    await openClosureDay(page)
    await expectFitsPage(page, closureRow(page).getByRole('button', { name: 'Edit' }))

    await openDetailsPage(page)
    await openClosureDay(page)
    await expectFitsPage(page, closureRow(page))
  })
}
