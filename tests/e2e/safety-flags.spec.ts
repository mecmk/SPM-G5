/**
 * Fix f21.2.1 (story 21.2) - the safety review flags the venue bookings it was about, not the
 * whole Venue booking section.
 * AC22 a booking a finding about venue bookings named - which the review released (21.3) - is
 *      highlighted and says "Flagged by the safety review" on its card.
 * AC23 a finding about venue bookings that names none flags the bookings pending or approved when
 *      the review was made, not one rejected before it.
 * AC24 a booking requested after the review is never flagged.
 * AC25 the section keeps its "Flagged by the safety review" line, but is not highlighted itself.
 * AC26 the coordinator's Venue booking and the organiser's Venue bookings show the same flags.
 * AC27 nothing is flagged once the event leaves Planning or a later review approves it.
 * That both booking lists say when each booking was requested is a backend case:
 * backend/tests/bookings/test_safety_flag_bookings.py.
 *
 * Every test only reads EVENTS.studioShowcase or EVENTS.makersFair, which no other spec uses.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

const FLAGGED = 'Flagged by the safety review'

function section(page: Page, name: string) {
  return page.getByRole('region', { name, exact: true })
}

function bookingCard(bookings: Locator, venue: string) {
  return bookings.getByRole('listitem').filter({ hasText: venue })
}

function background(locator: Locator) {
  return locator.evaluate((element) => getComputedStyle(element).backgroundColor)
}

/** The cards of `flagged` are outlined and say so (AC22, AC23); those of `notFlagged` neither
 * (AC24). The section says it once more, on its own line, and is not highlighted itself (AC25). */
async function expectFlags(page: Page, bookings: Locator, flagged: string[], notFlagged: string[]) {
  for (const venue of flagged) {
    const card = bookingCard(bookings, venue)
    await expect(card).toContainText(FLAGGED)
    await expect(card).not.toHaveCSS('box-shadow', 'none')
  }
  for (const venue of notFlagged) {
    const card = bookingCard(bookings, venue)
    await expect(card).toBeVisible()
    await expect(card).not.toContainText(FLAGGED)
    await expect(card).toHaveCSS('box-shadow', 'none')
  }
  await expect(bookings.getByText(FLAGGED, { exact: true })).toHaveCount(flagged.length + 1)
  expect(await background(bookings)).toBe(await background(section(page, 'Safety review')))
}

test('21.2 AC22/AC24/AC25: the coordinator sees the booking the review named flagged, not the one requested after it', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.studioShowcase}`)

  await expectFlags(
    page,
    section(page, 'Venue booking'),
    ['Seminar Room 2.1'],
    ['Exhibition Foyer'],
  )
})

test('21.2 AC22/AC24/AC26: the organiser sees the same flags on their Venue bookings', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.studioShowcase}`)

  await expectFlags(
    page,
    section(page, 'Venue bookings'),
    ['Seminar Room 2.1'],
    ['Exhibition Foyer'],
  )
})

test('21.2 AC23/AC24: a finding that names no booking flags the pending and approved bookings the review saw', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.makersFair}`)

  // Seminar Room 2.1 was approved and Grand Hall pending when the review was made; Garden
  // Atrium, asked for before it too, was rejected; Exhibition Foyer was asked for after it.
  await expectFlags(
    page,
    section(page, 'Venue booking'),
    ['Seminar Room 2.1', 'Grand Hall'],
    ['Exhibition Foyer', 'Garden Atrium'],
  )
})

test('21.2 AC23/AC26: the organiser sees the bookings the review saw flagged', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.makersFair}`)

  // The organiser's list leaves the rejected Garden Atrium out (fix f7.1.2).
  await expectFlags(
    page,
    section(page, 'Venue bookings'),
    ['Seminar Room 2.1', 'Grand Hall'],
    ['Exhibition Foyer'],
  )
})

test('21.2 AC27: nothing is flagged once the event leaves Planning or a later review approves it', async ({
  page,
}) => {
  // The rule is the page's own, so the event's safety review is read as the server sends it and
  // then changed, rather than moving a shared seed event on for good.
  let change: (safety: { status: string; latest_review: { outcome: string } }) => void = () => {}
  await page.route(`**/events/${EVENTS.studioShowcase}/safety-review`, async (route) => {
    const response = await route.fetch()
    const safety = await response.json()
    change(safety)
    await route.fulfill({ response, json: safety })
  })
  await signIn(page, ACCOUNTS.coordinator)

  for (const changeTo of [
    (safety: { status: string }) => (safety.status = 'AWAITING_SAFETY_CHECK'),
    (safety: { latest_review: { outcome: string } }) => (safety.latest_review.outcome = 'APPROVED'),
  ]) {
    change = changeTo
    await page.goto(`/events/${EVENTS.studioShowcase}`)
    const bookings = section(page, 'Venue booking')
    await expect(bookingCard(bookings, 'Seminar Room 2.1')).toBeVisible()
    await expect(bookings.getByText(FLAGGED, { exact: true })).toHaveCount(0)
    await expect(bookingCard(bookings, 'Seminar Room 2.1')).toHaveCSS('box-shadow', 'none')
  }
})
