/**
 * Story 5.2 - fe/be: reassign a coordinator-holding event to a different coordinator.
 *
 * AC3 the event page has a Reassign action with a list of eligible coordinators and a
 *     confirmation step; the assignment change takes effect immediately (the page shows the new
 *     coordinator without a reload).
 *
 * Boundary, permission and conflict detail (AC4, AC6, AC7) are backend cases, covered by
 * backend/tests/coordination/test_reassign_coordinator.py. This spec covers the flow a
 * coordinator actually clicks through.
 *
 * The event used here is a fresh one created and submitted through the UI, not an existing seed
 * row: story 5.1's round robin means a submission can land on either seeded coordinator, and
 * reassigning a *shared* seed event (used by several other specs for its bookings, equipment and
 * accessibility data) would leave it permanently changed for the rest of this parallel run (see
 * tests/CLAUDE.md on why specs must not mutate shared seed state). Whichever coordinator the
 * round robin lands on is discovered from the page itself, the same way a person would look.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  COORDINATORS,
  EVENTS,
  assignByLead,
  corsHeaders,
  createAndSubmitRequest,
  signIn,
  uniqueName,
} from './support'

test('5.2 AC3: a coordinator reassigns an event to another coordinator', async ({ page }) => {
  // Two full sign-in cycles (organiser, then the auto-assigned coordinator) genuinely take
  // longer than the default per-test budget - see bookings.spec.ts's AC3/AC4 test for the
  // same reasoning.
  test.setTimeout(60_000)

  const name = uniqueName('Reassign')
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, name)

  await page.goto(`/events/${eventId}`)
  const { account, other } = await assignByLead(page)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, account)
  await page.goto(`/events/${eventId}`)

  await page.getByRole('button', { name: 'Reassign' }).click()
  await page.getByLabel('New coordinator').selectOption({ label: other.name })
  await page.getByRole('button', { name: 'Confirm reassignment' }).click()

  await expect(page.getByText(other.name)).toBeVisible()
})

/* ---------- Story 5.6: the Event Coordinator Lead reassigns ---------- */

const [CHLOE, CARL] = COORDINATORS
const PHONE = { width: 375, height: 667 }
const TABLET = { width: 768, height: 1024 }
const DESKTOP = { width: 1280, height: 800 }
const MIN_TOUCH_TARGET = 44
const STALE_MESSAGE = "This event's coordinator changed just now. Reload the event and try again."
/** How the picker names a coordinator: their name and their number of active events (5.4 AC3). */
const WITH_COUNT = /· \d+ active events?$/

/**
 * A fresh request, submitted by Olivia and assigned to Chloe by the Lead (5.4), so reassigning it
 * changes no shared seed row. Leaves the Lead signed in; returns the request's id and name.
 */
async function freshEventWithChloe(page: Page, label: string) {
  const name = uniqueName(label)
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, name)
  await page.goto(`/events/${eventId}`)
  await assignByLead(page)
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.lead)
  return { eventId, name }
}

function reassignDialog(page: Page, name: string) {
  return page.getByRole('dialog', { name: `Reassign "${name}"?` })
}

/** In the open dialog: the picker offers Carl with his count and not Chloe; choose Carl and
 * confirm, waiting for the dialog to close. */
async function reassignToCarl(page: Page, name: string) {
  const dialog = reassignDialog(page, name)
  const picker = dialog.getByLabel('New coordinator')
  await expect(picker.getByRole('option', { name: new RegExp(`^${CARL.name} `) })).toHaveText(
    WITH_COUNT,
  )
  await expect(picker.getByRole('option', { name: new RegExp(`^${CHLOE.name}`) })).toHaveCount(0)
  await picker.selectOption(CARL.id)
  await dialog.getByRole('button', { name: 'Confirm reassignment' }).click()
  await expect(dialog).toHaveCount(0)
}

function overviewCard(page: Page, name: string) {
  return page
    .getByRole('list', { name: 'Active events' })
    .getByRole('listitem')
    .filter({ has: page.getByRole('link', { name, exact: true }) })
}

async function expectNoSidewaysScroll(page: Page) {
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )
  expect(fits).toBe(true)
}

/** The element sits wholly inside the viewport. */
async function expectInsideScreen(page: Page, element: Locator) {
  const box = (await element.boundingBox())!
  const { width, height } = page.viewportSize()!
  expect(box.x).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(width)
  expect(box.y + box.height).toBeLessThanOrEqual(height)
}

test('5.6 AC1: the Lead reassigns an event from its page', async ({ page }) => {
  test.setTimeout(90_000)
  const { eventId, name } = await freshEventWithChloe(page, 'Lead reassigns')
  await page.goto(`/events/${eventId}`)
  await expect(page.getByText(CHLOE.account, { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Reassign' }).click()
  await reassignToCarl(page, name)

  // The page shows the new coordinator straight away (AC1), and a reload agrees.
  await expect(page.getByText(CARL.account, { exact: true })).toBeVisible()
  await expect(page.getByText(CHLOE.account, { exact: true })).toHaveCount(0)
  await page.reload()
  await expect(page.getByText(CARL.account, { exact: true })).toBeVisible()
})

test('5.6 AC1: the Lead reassigns an event from the overview', async ({ page }) => {
  test.setTimeout(90_000)
  const { name } = await freshEventWithChloe(page, 'Overview reassign')
  await page.goto(`/events/assignments?coordinator=${CHLOE.id}`)
  const card = overviewCard(page, name)
  await expect(card).toContainText(`Coordinator: ${CHLOE.name}`)

  await card.getByRole('button', { name: 'Reassign' }).click()
  await reassignToCarl(page, name)

  await page.goto(`/events/assignments?coordinator=${CARL.id}`)
  await expect(overviewCard(page, name)).toContainText(`Coordinator: ${CARL.name}`)
  await expect(overviewCard(page, name)).toContainText('Assigned by Lena Lead')
})

test('5.6 AC5: a coordinator no longer sees Reassign', async ({ page }) => {
  // Read only: Chloe opens her own seeded event, which she could reassign under 5.2.
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.approved}`)
  await expect(page.getByText('Assigned coordinator')).toBeVisible()

  await expect(page.getByRole('button', { name: 'Reassign' })).toHaveCount(0)
})

test('5.6 AC6: a reassignment refused as stale says why', async ({ page }) => {
  // The refusal itself is a backend case; here the page shows it. The PUT is answered with the
  // server's 409, so the seeded event is never changed.
  await page.route(
    (url) => url.pathname === `/events/${EVENTS.approved}/coordinator`,
    (route) => {
      const request = route.request()
      if (request.method() !== 'PUT') return route.fallback()
      return route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: STALE_MESSAGE }),
        headers: corsHeaders(request),
      })
    },
  )
  await signIn(page, ACCOUNTS.lead)
  await page.goto(`/events/${EVENTS.approved}`)
  const name = (await page.getByRole('heading', { level: 1 }).textContent())!.trim()

  await page.getByRole('button', { name: 'Reassign' }).click()
  const dialog = reassignDialog(page, name)
  await dialog.getByLabel('New coordinator').selectOption(CARL.id)
  await dialog.getByRole('button', { name: 'Confirm reassignment' }).click()

  await expect(dialog.getByRole('alert')).toHaveText(STALE_MESSAGE)
})

for (const { device, viewport } of [
  { device: 'a phone', viewport: PHONE },
  { device: 'a desktop', viewport: DESKTOP },
]) {
  test(`5.6 responsive: the Lead reassigns on ${device}`, async ({ page }) => {
    test.setTimeout(90_000)
    await page.setViewportSize(viewport)
    const { eventId, name } = await freshEventWithChloe(page, `Reassign ${viewport.width}`)

    // The overview: each card's Reassign is in reach, and nothing scrolls sideways.
    await page.goto(`/events/assignments?coordinator=${CHLOE.id}`)
    const cardButton = overviewCard(page, name).getByRole('button', { name: 'Reassign' })
    await expect(cardButton).toBeVisible()
    await expectNoSidewaysScroll(page)
    if (viewport === PHONE) {
      expect((await cardButton.boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET)
    }

    // The event page: Reassign, then the dialog and its picker inside the screen.
    await page.goto(`/events/${eventId}`)
    const reassign = page.getByRole('button', { name: 'Reassign' })
    await expect(reassign).toBeVisible()
    await expectNoSidewaysScroll(page)
    if (viewport === PHONE) {
      expect((await reassign.boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET)
    }
    await reassign.click()
    const dialog = reassignDialog(page, name)
    await expectInsideScreen(page, dialog)
    await expectInsideScreen(page, dialog.getByLabel('New coordinator'))
    if (viewport === PHONE) {
      for (const target of [
        dialog.getByLabel('New coordinator'),
        dialog.getByRole('button', { name: 'Confirm reassignment' }),
        dialog.getByRole('button', { name: 'Cancel' }),
      ]) {
        expect((await target.boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET)
      }
    }
    await reassignToCarl(page, name)
    await expect(page.getByText(CARL.account, { exact: true })).toBeVisible()
    await expectNoSidewaysScroll(page)
  })
}

test('5.6 responsive: reassigning fits a tablet', async ({ page }) => {
  // Read only: the dialog is opened on the seeded event and cancelled.
  await page.setViewportSize(TABLET)
  await signIn(page, ACCOUNTS.lead)
  await page.goto(`/events/${EVENTS.approved}`)
  await expectNoSidewaysScroll(page)
  const name = (await page.getByRole('heading', { level: 1 }).textContent())!.trim()

  await page.getByRole('button', { name: 'Reassign' }).click()
  const dialog = reassignDialog(page, name)
  await expectInsideScreen(page, dialog)
  await dialog.getByRole('button', { name: 'Cancel' }).click()

  await page.goto(`/events/assignments?coordinator=${CHLOE.id}`)
  await expect(page.getByRole('list', { name: 'Active events' })).toBeVisible()
  await expectNoSidewaysScroll(page)
})
