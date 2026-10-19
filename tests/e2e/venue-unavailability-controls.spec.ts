/**
 * Story 9.4, fix f9.4.1: the venue unavailability ("block off time") controls live on the Edit
 * venue page, not the venue's details page.
 *
 * 9.4 AC1 Venue Staff add a closure from the venue's Edit venue page, where Availability and
 *         Block off time are sections of the page like the form's own, after the form that Save
 *         changes closes, under a note that closures save at once.
 * 9.4 AC6 Venue Staff edit, end ("End now") and remove a closure from the Edit venue page only.
 * 9.4 AC9 The venue's details page, and the calendar on it (9.1), keep showing each period with
 *         its reason to every internal role, Venue Staff included, with no add, edit, end or
 *         remove control. Both pages are usable at 1280x720 and 390x844.
 *
 * Nothing about 9.4's rules changes - the overlap, the marking, what End now and Remove do - so
 * the steps that add, edit, end and remove are venue-unavailability.spec.ts's, which reaches them
 * through the Edit venue page. This file only says where the controls are and are not.
 *
 * It makes its own closure, on the Garden Atrium (no booking; 9.4's venue for this), on a day
 * venue-unavailability.spec.ts leaves alone, and its tests run in order since the later ones read
 * what the first adds. The browser's clock is pinned to 10 October 2028, as that spec pins its
 * own, so the calendar opens on the month the closure is in; the server keeps real time, so the
 * closure has not started and is one to Remove.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, signIn, uniqueName, venueCard } from './support'

test.use({ timezoneId: 'Asia/Singapore' })

const VENUE = 'Garden Atrium'
const PINNED_NOW = new Date('2028-10-10T10:00:00+08:00')
const CLOSURE_DAY = /^28 October 2028/
const CLOSURE_DESCRIPTION = uniqueName('Atrium skylight cleaning')
const CLOSURE_LABEL = 'Unavailable – Maintenance'
const CLOSURES_NOTE = 'Closures are saved as soon as you add them; Save changes is not needed.'

const DESKTOP = { width: 1280, height: 720 }
const PHONE = { width: 390, height: 844 }

function availability(page: Page) {
  // A region on the details page, a group - a form section - on the Edit venue page.
  return page
    .getByRole('region', { name: 'Availability', exact: true })
    .or(page.getByRole('group', { name: 'Availability', exact: true }))
}

function blockOff(page: Page) {
  const name = /^(Block off time|Edit blocked-off time)$/
  return page.getByRole('region', { name }).or(page.getByRole('group', { name }))
}

/** The closure's row in the day's list, which holds its actions when there are any. */
function closureRow(page: Page) {
  return page.getByRole('listitem').filter({ hasText: CLOSURE_DESCRIPTION })
}

/** Venue Staff's Edit venue page, from the venue's card in the catalogue. */
async function openEditPage(page: Page) {
  await page.clock.setFixedTime(PINNED_NOW)
  await page.goto('/venues')
  await venueCard(page, VENUE).getByRole('link', { name: 'Edit' }).click()
  await expect(page).toHaveURL(/\/venues\/[0-9a-f-]{36}\/edit$/)
  await expect(availability(page)).toBeVisible()
  await expect(page.getByText('Loading availability…')).toHaveCount(0)
}

/** The venue's details page, as any internal role opens it. */
async function openDetailsPage(page: Page) {
  await page.clock.setFixedTime(PINNED_NOW)
  await page.goto('/venues')
  await page.getByRole('link', { name: VENUE }).click()
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

test.describe('the block-off controls on the Edit venue page', () => {
  test.describe.configure({ mode: 'serial' })

  test('9.4 AC1: Venue Staff add a closure from the Edit venue page, and its day offers Edit and Remove', async ({
    page,
  }) => {
    await signIn(page, ACCOUNTS.venueStaff)
    await openEditPage(page)

    const card = blockOff(page)
    await card.getByRole('button', { name: 'Block off time' }).click()
    await card.getByLabel('Starts').fill('2028-10-28T10:00')
    await card.getByLabel('Ends').fill('2028-10-28T16:00')
    await card.getByLabel('Reason').selectOption({ label: 'Maintenance' })
    await card.getByLabel('Description').fill(CLOSURE_DESCRIPTION)
    await expect(card.getByText('No bookings are affected.')).toBeVisible()
    const landed = page.waitForResponse(
      (response) =>
        /\/unavailability$/.test(new URL(response.url()).pathname) &&
        response.request().method() === 'POST',
    )
    await card.getByRole('button', { name: 'Save closure' }).click()
    expect((await landed).ok()).toBe(true)

    // The closure has not started, so its row offers Edit and Remove (End now is for one in force).
    await openClosureDay(page)
    await expect(closureRow(page).getByRole('button', { name: 'Edit' })).toBeVisible()
    await expect(closureRow(page).getByRole('button', { name: 'Remove' })).toBeVisible()
  })

  test('9.4 AC1: the Edit venue page closes its form with Save changes, then the closure sections', async ({
    page,
  }) => {
    await signIn(page, ACCOUNTS.venueStaff)
    await openEditPage(page)

    // Availability and Block off time are sections of the page like Accessibility is.
    const accessibility = page.getByRole('group', { name: 'Accessibility', exact: true })
    const save = page.getByRole('button', { name: 'Save changes' })
    const note = page.getByText(CLOSURES_NOTE)
    const calendar = page.getByRole('group', { name: 'Availability', exact: true })
    const blockOffSection = page.getByRole('group', { name: 'Block off time', exact: true })
    const parts = [accessibility, save, note, calendar, blockOffSection]
    for (const part of parts) await expect(part).toBeVisible()

    // In that order down the page: the form ends at Save changes, then the note, then the closures.
    const boxes = await Promise.all(parts.map((part) => part.boundingBox()))
    const ys = boxes.map((box) => box?.y ?? Number.NaN)
    expect(ys).toEqual([...ys].sort((a, b) => a - b))
    expect(new Set(ys).size).toBe(parts.length)
    // and they are cards as wide and as far left as the form's own.
    const [first, , , second, third] = boxes
    for (const closure of [second, third]) {
      expect(Math.abs((closure?.x ?? 0) - (first?.x ?? 1))).toBeLessThan(1)
      expect(Math.abs((closure?.width ?? 0) - (first?.width ?? 1))).toBeLessThan(1)
    }
  })

  test('9.4 AC9: the details page shows the period and its reason but no controls', async ({
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
    test(`9.4 AC9: the Edit venue page's controls and the details page's calendar are usable at ${size}`, async ({
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
})
