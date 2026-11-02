/**
 * Story 12.8 - fe/be: cancel an approved venue booking.
 * AC1 the assigned coordinator cancels an approved booking from the event page, giving a reason;
 *     a blank reason is refused in the dialog before anything is sent.
 * AC2 the cancelled booking stays in the event's booking list as Cancelled, with its reason, and
 *     its requirement needs a venue again.
 * AC4 the cancel is not offered once cancelling has closed (stubbed: the seeded event is far off).
 * AC7 the cancel is not offered while a replacement is pending (stubbed: the seed has none here).
 * AC8 only the assigned coordinator is offered the cancel, and only on an approved booking. Every
 *     refusal the API makes is a backend case.
 * Every other AC (AC3, AC5, AC6, AC9), and the API's own refusals for AC4 and AC7, are backend
 * cases: backend/tests/bookings/test_cancel_approved_booking.py.
 *
 * The tests run in order on one seeded event, the riverside product briefing. The first four leave
 * its booking approved; the fifth cancels it for good and the sixth reads what that left. A retry
 * could only fail on the cancelled booking and hide the first trace: serial, no retries.
 */
import { expect, test, type Page, type Request } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

test.describe.configure({ mode: 'serial', retries: 0 })

const EVENT_NAME = 'Riverside Product Briefing'
const CANCEL_BUTTON = 'Cancel the booking of Seminar Room 2.1 for Main hall'
const REASON = 'The client moved the briefing online.'
const REASON_REQUIRED = 'Enter a reason for cancelling this booking.'
const CANCELLED_LINE = 'Cancelled by the coordinator'
const CANCELLED_MESSAGE =
  'The coordinator cancelled this booking, so the venue is free for other events.'

function section(page: Page, name: string) {
  return page.getByRole('region', { name, exact: true })
}

async function openCancelDialog(page: Page) {
  await section(page, 'Venue booking').getByRole('button', { name: CANCEL_BUTTON }).click()
  return page.getByRole('dialog', { name: 'Cancel this venue booking?' })
}

/** Answer the page's call to `path` with what the server sends, changed by `change`. */
async function changeCall(page: Page, path: string, change: (body: never) => unknown) {
  await page.route(
    (url) => url.pathname === path,
    async (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      const response = await route.fetch()
      return route.fulfill({ response, json: change(await response.json()) })
    },
  )
}

test('12.8 AC8: only the assigned coordinator is offered the cancel', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto(`/events/${EVENTS.productBriefing}`)
  await expect(page.getByRole('heading', { name: EVENT_NAME })).toBeVisible()
  await expect(page.getByRole('main')).toContainText('Seminar Room 2.1')
  await expect(page.getByRole('button', { name: CANCEL_BUTTON })).toHaveCount(0)
})

test('12.8 AC4: the cancel is not offered once cancelling has closed', async ({ page }) => {
  const windowPath = `/events/${EVENTS.productBriefing}/change-request-window`
  await changeCall(page, windowPath, (window: object) => ({ ...window, is_open: false }))
  await signIn(page, ACCOUNTS.coordinator)
  const windowRead = page.waitForResponse((response) => response.url().endsWith(windowPath))
  await page.goto(`/events/${EVENTS.productBriefing}`)

  await windowRead
  await expect(section(page, 'Venue booking')).toContainText('Approved')
  await expect(page.getByRole('button', { name: CANCEL_BUTTON })).toHaveCount(0)
})

test('12.8 AC7: the cancel is not offered while a replacement is pending', async ({ page }) => {
  await changeCall(
    page,
    `/bookings/for-event/${EVENTS.productBriefing}`,
    (bookings: Record<string, unknown>[]) =>
      bookings.map((booking) => ({
        ...booking,
        pending_replacement_venue_name: 'Exhibition Foyer',
      })),
  )
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.productBriefing}`)

  const bookings = section(page, 'Venue booking')
  await expect(bookings).toContainText('Replacement requested: Exhibition Foyer')
  await expect(bookings.getByRole('button', { name: CANCEL_BUTTON })).toHaveCount(0)
})

test('12.8 AC1: a blank reason is refused before anything is sent', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.productBriefing}`)
  const sent: string[] = []
  page.on('request', (request) => {
    if (request.url().endsWith('/cancel')) sent.push(request.url())
  })

  const dialog = await openCancelDialog(page)
  await dialog.getByLabel('Reason for cancelling').fill('   ')
  await dialog.getByRole('button', { name: 'Cancel booking' }).click()

  await expect(dialog.getByRole('alert')).toHaveText(REASON_REQUIRED)
  expect(sent).toEqual([])
  await dialog.getByRole('button', { name: 'Keep booking' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(section(page, 'Venue booking')).toContainText('Approved')
})

test('12.8 AC1: the coordinator cancels an approved booking with a reason', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.productBriefing}`)

  const dialog = await openCancelDialog(page)
  await dialog.getByLabel('Reason for cancelling').fill(REASON)
  await dialog.getByRole('button', { name: 'Cancel booking' }).click()

  await expect(dialog).toHaveCount(0)
  await expect(
    section(page, 'Venue booking').getByText(CANCELLED_LINE, { exact: true }),
  ).toBeVisible()
})

test('12.8 AC2: the cancelled booking stays listed with its reason, and its requirement needs a venue again', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.productBriefing}`)

  const bookings = section(page, 'Venue booking')
  await expect(bookings).toContainText('Seminar Room 2.1')
  await expect(bookings).toContainText('Cancelled')
  await expect(bookings.getByText(CANCELLED_LINE, { exact: true })).toBeVisible()
  await expect(bookings).toContainText(CANCELLED_MESSAGE)
  await expect(bookings.getByText('Reason', { exact: true })).toBeVisible()
  await expect(bookings).toContainText(REASON)
  // AC8: a booking no longer approved offers no cancel.
  await expect(bookings.getByRole('button', { name: CANCEL_BUTTON })).toHaveCount(0)

  await page.getByRole('link', { name: 'Find a venue' }).click()
  const main = page
    .getByRole('region', { name: `Finding a venue for ${EVENT_NAME}` })
    .getByRole('listitem')
    .filter({ hasText: 'Main hall' })
  await expect(main).toContainText('Needs a venue')
})
