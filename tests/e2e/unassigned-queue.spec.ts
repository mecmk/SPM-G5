/**
 * Story 5.4 - fe: the Event Coordinator Lead's unassigned queue, and assigning from it.
 *
 * AC1 the Lead's sidebar offers the unassigned queue (and not the coordinators' inbox).
 * AC2 a submitted request waits in the queue with its name, dates, attendance, organiser and
 *     submission time; opening it shows the event read-only.
 * AC3 the Lead assigns it to a coordinator picked from a list showing each one's active events,
 *     after confirming; it leaves the queue.
 * AC5 an empty queue says so; with no active coordinators the queue says why it cannot assign.
 * AC6 the organiser's submitted request reads "Not yet assigned".
 * AC7 a coordinator who opens the queue's address directly is not permitted.
 * AC8 a Lead who loses the race to another Lead is told who got the event, and the queue reloads.
 * AC9 submitting leaves the request unassigned, waiting for the Lead.
 * Responsive: the queue and the assign dialog fit a phone (375 x 667) and a desktop (1280 x 800),
 *     with no sideways scroll, the queue's rows stacked as cards and touch targets 44px tall.
 *
 * Rules, refusals (401/403/404/409/422), the count of active events, notifications and the race
 * between two Leads are backend cases: backend/tests/coordination/test_unassigned_queue.py.
 *
 * Every test that assigns works on a request it submits itself, with a unique name: other specs
 * submit requests too, and since 5.4 they all wait in the same queue, so the queue is only ever
 * asserted by name, never by its length. The empty and no-coordinator states are reached by
 * stubbing the one fetch, as tests/CLAUDE.md allows.
 */
import { expect, test, type Page, type Request } from '@playwright/test'
import {
  ACCOUNTS,
  DESKTOP,
  MIN_TOUCH_TARGET,
  PHONE,
  corsHeaders,
  createAndSubmitRequest,
  expectNoSidewaysScroll,
  signIn,
  uniqueName,
} from './support'

const QUEUE_PATH = '/events/unassigned'
const QUEUE_API = '/coordination/unassigned-events'
const COORDINATORS_API = '/coordinators'
const QUEUE_LABEL = 'Unassigned events'
const CARL = { id: '11111111-0000-0000-0000-000000000004', name: 'Carl Coordinator' }
const EMPTY_MESSAGE = 'No events are waiting for a coordinator.'
const NO_COORDINATOR_MESSAGE = 'No Event Coordinator is active, so events cannot be assigned yet.'

function mainNav(page: Page) {
  return page.getByRole('navigation', { name: 'Main' })
}

function queueItem(page: Page, eventName: string) {
  return page
    .getByRole('list', { name: QUEUE_LABEL })
    .getByRole('listitem')
    .filter({ hasText: eventName })
}

function assignDialog(page: Page, eventName: string) {
  return page.getByRole('dialog', { name: `Assign "${eventName}"?` })
}

/** A request the organiser submits now, so it waits unassigned; returns its name. */
async function submitRequest(page: Page, label: string): Promise<string> {
  const name = uniqueName(label)
  await signIn(page, ACCOUNTS.organiser)
  await createAndSubmitRequest(page, name)
  await page.getByRole('button', { name: 'Sign out' }).click()
  return name
}

async function openQueueAsLead(page: Page) {
  await signIn(page, ACCOUNTS.lead)
  await page.goto(QUEUE_PATH)
  await expect(page.getByRole('heading', { name: QUEUE_LABEL, level: 1 })).toBeVisible()
}

/** Serve one API path with a fixed JSON body, for states the seed cannot reach. */
async function stubFetch(page: Page, path: string, body: unknown) {
  await page.route(
    (url) => url.pathname === path,
    (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
        headers: corsHeaders(request),
      })
    },
  )
}

test("5.4 AC1: the Lead's sidebar offers the unassigned queue", async ({ page }) => {
  await signIn(page, ACCOUNTS.lead)

  await expect(mainNav(page).getByRole('link', { name: QUEUE_LABEL })).toBeVisible()
  await expect(mainNav(page).getByRole('link', { name: 'Events inbox' })).toHaveCount(0)
})

test('5.4 AC9/AC6: a submitted request waits unassigned for the Lead', async ({ page }) => {
  const name = uniqueName('Waiting')
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, name)

  // AC6: the organiser sees nobody yet.
  await page.goto(`/events/${eventId}`)
  await expect(page.getByText('Not yet assigned')).toBeVisible()

  await page.getByRole('button', { name: 'Sign out' }).click()
  await openQueueAsLead(page)
  await expect(queueItem(page, name)).toBeVisible()
})

test('5.4 AC2/AC3: the Lead assigns a new request from the queue', async ({ page }) => {
  test.setTimeout(60_000)
  const name = await submitRequest(page, 'Assign me')
  await openQueueAsLead(page)

  // AC2: what the Lead needs to choose, on the request's row.
  const item = queueItem(page, name)
  await expect(item).toContainText('Olivia Organiser')
  await expect(item).toContainText('60 people')
  await expect(item).toContainText('Submitted')
  await expect(item).not.toContainText('Not recorded') // a real submission time
  await expect(item).toContainText('09:00–17:00') // createAndSubmitRequest's proposed hours

  // AC2: the request opens read-only - the Lead decides nothing about it.
  await item.getByRole('link', { name }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Reject' })).toHaveCount(0)
  await page.goBack()

  // AC3: pick a coordinator, who is shown with their active events, and confirm.
  await queueItem(page, name).getByRole('button', { name: 'Assign' }).click()
  const dialog = assignDialog(page, name)
  const picker = dialog.getByLabel('Coordinator')
  await expect(picker.locator('option', { hasText: CARL.name })).toHaveText(
    new RegExp(`^${CARL.name} · \\d+ active events?$`),
  )
  await picker.selectOption(CARL.id)
  await dialog.getByRole('button', { name: 'Assign' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(queueItem(page, name)).toHaveCount(0)
})

test('5.4 AC5: an empty queue says there is nothing to assign', async ({ page }) => {
  await stubFetch(page, QUEUE_API, [])
  await openQueueAsLead(page)

  await expect(page.getByText(EMPTY_MESSAGE)).toBeVisible()
})

test('5.4 AC5: with no active coordinators the queue says why', async ({ page }) => {
  const name = uniqueName('Nobody to assign')
  await stubFetch(page, COORDINATORS_API, [])
  await stubFetch(page, QUEUE_API, [
    {
      id: '00000000-0000-0000-0000-000000000054',
      name,
      starts_at: '2027-06-01T01:00:00Z',
      ends_at: '2027-06-01T09:00:00Z',
      expected_attendance: 40,
      organiser_name: 'Olivia Organiser',
      submitted_at: '2026-10-12T01:00:00Z',
    },
  ])
  await openQueueAsLead(page)

  await expect(page.getByText(NO_COORDINATOR_MESSAGE)).toBeVisible()
  await expect(queueItem(page, name).getByRole('button', { name: 'Assign' })).toBeDisabled()
})

test("5.4 AC7: a coordinator who opens the queue's address is not permitted", async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)

  await page.goto(QUEUE_PATH)

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
  await expect(page.getByRole('list', { name: QUEUE_LABEL })).toHaveCount(0)
})

test('5.4 AC8: a Lead who loses the race is told who got the event', async ({ page }) => {
  const name = uniqueName('Taken')
  const winner = 'This event has already been assigned to Chloe Coordinator.'
  let isTaken = false
  // The queue holds the event until the refusal; after it, it has gone, as another Lead assigned
  // it. (Counting calls would not do: the dev build loads the page twice.)
  await page.route(
    (url) => url.pathname === QUEUE_API,
    (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      const entries = [
        {
          id: '00000000-0000-0000-0000-000000000058',
          name,
          starts_at: '2027-06-01T01:00:00Z',
          ends_at: '2027-06-01T09:00:00Z',
          expected_attendance: 40,
          organiser_name: 'Olivia Organiser',
          submitted_at: '2026-10-12T01:00:00Z',
        },
      ]
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(isTaken ? [] : entries),
        headers: corsHeaders(request),
      })
    },
  )
  await page.route(
    (url) => /\/events\/[^/]+\/coordinator$/.test(url.pathname),
    (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch' || request.method() !== 'PUT') return route.fallback()
      isTaken = true
      return route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: winner }),
        headers: corsHeaders(request),
      })
    },
  )
  await openQueueAsLead(page)

  await queueItem(page, name).getByRole('button', { name: 'Assign' }).click()
  await assignDialog(page, name).getByRole('button', { name: 'Assign' }).click()

  await expect(assignDialog(page, name)).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveText(winner)
  await expect(queueItem(page, name)).toHaveCount(0)
})

for (const { device, viewport } of [
  { device: 'a phone', viewport: PHONE },
  { device: 'a desktop', viewport: DESKTOP },
]) {
  test(`5.4 responsive: the queue and the assign dialog fit ${device}`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.setViewportSize(viewport)
    const name = await submitRequest(page, `Fits ${viewport.width}`)
    await openQueueAsLead(page)

    const item = queueItem(page, name)
    await expect(item).toBeVisible()
    await expectNoSidewaysScroll(page)

    // The row is a card inside the screen, with the whole name readable.
    const card = await item.boundingBox()
    expect(card).not.toBeNull()
    expect(card!.x + card!.width).toBeLessThanOrEqual(viewport.width)
    await expect(item).toContainText(name)

    const assign = item.getByRole('button', { name: 'Assign' })
    if (viewport === PHONE) {
      expect((await assign.boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET)
    }

    await assign.click()
    const dialog = assignDialog(page, name)
    const box = await dialog.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width)
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height)
    if (viewport === PHONE) {
      for (const control of [
        dialog.getByLabel('Coordinator'),
        dialog.getByRole('button', { name: 'Assign' }),
        dialog.getByRole('button', { name: 'Cancel' }),
      ]) {
        expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET)
      }
    }
    await expectNoSidewaysScroll(page)
  })
}
