/**
 * Stories 5.2 and 5.6 - reassigning an event to another coordinator.
 *
 * Story 5.6 (Q16) gave reassignment to the Event Coordinator Lead and took it from coordinators,
 * replacing 5.2 AC1 and AC6; 5.2 AC3's Reassign action on the event page is now the Lead's.
 *
 * 5.6 AC1 the Lead reassigns from the event page and from the overview (5.5), choosing from the
 *     other active coordinators, each with their active-event count; the page shows the new
 *     coordinator at once.
 * 5.6 AC5 a coordinator no longer sees Reassign.
 * 5.6 AC6 a reassignment refused because the assignment changed says why.
 * Responsive: the flow at a phone (375 x 667) and a desktop (1280 x 800), and the page and dialog
 *     at a tablet (768 x 1024): no sideways scroll, the dialog and picker inside the screen, and
 *     44px targets on the phone.
 *
 * The rules - who may reassign (401/403), which coordinators may be chosen (422), closed and
 * unknown events (409/404), the stale and simultaneous reassignments (409), the notifications and
 * what moves with the event - are backend cases:
 * backend/tests/coordination/test_lead_reassign_coordinator.py.
 *
 * A reassignment is made on a fresh request, submitted through the UI and assigned to Chloe by the
 * Lead, so no shared seed event changes (tests/CLAUDE.md). The cases that only look, or whose
 * write is answered by a stub, use the seeded EVENTS.approved, Chloe's, in Planning.
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
