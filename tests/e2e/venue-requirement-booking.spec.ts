/**
 * Story 12.5 - request a venue for each venue requirement and see when all are covered.
 *
 * AC1  Request this venue requests the venue for the requirement selected in the banner; the
 *      request step names it and carries its own times and number of people.
 * AC2  The banner marks each requirement "Needs a venue", "Requested: <venue>" or "Booked: <venue>",
 *      and Find a venue selects the first that needs a venue. Decided 10 Oct 2026: covered
 *      requirements are greyed and listed after the ones that still need a venue; selecting one
 *      shows its venue first, then the other venues that fit it, none offering a request.
 * AC3  After a request, while a requirement still needs a venue, the catalogue opens on it; a
 *      notice names the venue and the requirement.
 * AC4  Once every requirement has a request, the event's page opens instead, and its booking list
 *      names each booking's requirement.
 * AC5  Then Find a venue is greyed and reads "All required venues booked"; it opens the catalogue
 *      with no requirement selected, for an additional venue, which the booking list names so.
 * AC6  An event with one requirement goes straight to its page: booking-requests.spec.ts's
 *      '12.1 AC1/AC3' send.
 * AC7  An event marked "No venue requirements" keeps Find a venue's normal look.
 * AC8  A requirement whose request is withdrawn needs a venue again.
 * AC9  A venue requested for one requirement drops out for another whose times overlap.
 *
 * The rules - one request per requirement, refusals, the race, independence, suitability per
 * requirement - are backend cases: backend/tests/bookings/test_request_per_requirement.py.
 *
 * Seed (backend/db/seed/020_sample_data.sql), both Chloe's and only used here:
 * - Urban Mobility Forum, 11-12 Apr 2028, 200 people, no bookings: Expo hall (200, Standing, both
 *   days: Grand Hall and Exhibition Foyer), Workshop room (40, Classroom, 12 Apr 13:00-17:00:
 *   Seminar Room 2.1), Networking lounge (100, Standing, 11 Apr 17:00-20:00: Grand Hall and
 *   Exhibition Foyer). Its one test requests a venue for each in turn, so it runs once, on its own.
 * - Coastal Resilience Workshop, 6 Jun 2028, 12 people: its one requirement, Meeting room, already
 *   booked (Boardroom 3.4, approved).
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn, venueCard } from './support'

const FORUM = { id: EVENTS.mobilityForum, name: 'Urban Mobility Forum' }
const WORKSHOP = { id: EVENTS.resilienceWorkshop, name: 'Coastal Resilience Workshop' }
const SUMMIT = { id: EVENTS.planning, name: 'Regional Sales Summit' }

const EXPO_HALL = 'Expo hall'
const WORKSHOP_ROOM = 'Workshop room'
const NETWORKING_LOUNGE = 'Networking lounge'
const WORKSHOP_ROOM_ID = 'cccccccc-0000-0000-0029-000000000002'

const FIND_A_VENUE = 'Find a venue'
const ALL_BOOKED = 'All required venues booked'
const REQUEST_THIS_VENUE = 'Request this venue'

function catalogueBanner(page: Page, eventName: string) {
  return page.getByRole('region', { name: `Finding a venue for ${eventName}` })
}

function requirementChoice(page: Page, name: string) {
  return catalogueBanner(page, FORUM.name).getByRole('button', { name, exact: true })
}

function bookingList(page: Page) {
  return page.getByRole('region', { name: 'Venue booking' })
}

async function openEvent(page: Page, event: { id: string; name: string }) {
  await page.goto(`/events/${event.id}`)
  await expect(page.getByRole('heading', { name: event.name, level: 1 })).toBeVisible()
}

/** Request `venue` from the catalogue's results and send it, as the coordinator does. */
async function requestAndSend(page: Page, venue: string) {
  await venueCard(page, venue).getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  await expect(page.getByRole('heading', { name: `Request ${venue}`, level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'Send request' }).click()
}

function notice(page: Page, text: string) {
  return page.getByRole('status').filter({ hasText: text })
}

test('12.5 AC1/AC2/AC3/AC9/AC4/AC5/AC8: a venue is requested for each requirement in turn', async ({
  page,
}) => {
  test.setTimeout(120_000)
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, FORUM)
  await page.getByRole('link', { name: FIND_A_VENUE }).click()

  // AC2: every requirement needs a venue, and Find a venue selected the first.
  await expect(requirementChoice(page, EXPO_HALL)).toHaveAttribute('aria-pressed', 'true')
  for (const name of [EXPO_HALL, WORKSHOP_ROOM, NETWORKING_LOUNGE]) {
    await expect(requirementChoice(page, name)).toContainText('Needs a venue')
  }

  // AC1: the request step names the requirement and carries its own number of people and times.
  await venueCard(page, 'Grand Hall').getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  const carries = page.getByRole('region', { name: 'What this request will carry' })
  await expect(carries).toContainText(EXPO_HALL)
  await expect(carries).toContainText('200')
  await expect(carries).toContainText('Tue, 11 Apr 2028, 09:00 – Wed, 12 Apr 2028, 17:00')
  await page.getByRole('button', { name: 'Send request' }).click()

  // AC3: back on the catalogue for the next requirement, and a notice names both.
  await expect(notice(page, 'Grand Hall was requested for Expo hall')).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`[?&]requirement=${WORKSHOP_ROOM_ID}(&|$)`))
  await expect(requirementChoice(page, WORKSHOP_ROOM)).toHaveAttribute('aria-pressed', 'true')
  // AC2 as decided: the covered requirement says so and moves after the others.
  await expect(requirementChoice(page, EXPO_HALL)).toContainText('Requested: Grand Hall')
  const listed = catalogueBanner(page, FORUM.name).getByRole('listitem')
  await expect(listed.nth(2)).toContainText(EXPO_HALL)

  // Selecting the covered requirement shows its venue first, then the others that fit it, with
  // no request offered for any of them.
  await requirementChoice(page, EXPO_HALL).click()
  const requested = page.getByRole('region', { name: `Requested for ${EXPO_HALL}` })
  await expect(requested).toContainText('Grand Hall')
  await expect(requested).toContainText('Pending')
  await expect(venueCard(page, 'Exhibition Foyer')).toBeVisible()
  await expect(page.getByRole('link', { name: REQUEST_THIS_VENUE })).toHaveCount(0)

  await requirementChoice(page, WORKSHOP_ROOM).click()
  await requestAndSend(page, 'Seminar Room 2.1')

  // AC9: Grand Hall is held for the Expo hall over the lounge's evening, so only the foyer fits.
  await expect(requirementChoice(page, NETWORKING_LOUNGE)).toHaveAttribute('aria-pressed', 'true')
  await expect(venueCard(page, 'Exhibition Foyer')).toBeVisible()
  await expect(venueCard(page, 'Grand Hall')).toHaveCount(0)
  await requestAndSend(page, 'Exhibition Foyer')

  // AC4: every requirement has a request, so the event's page opens, naming each one's venue.
  await expect(page.getByRole('heading', { name: FORUM.name, level: 1 })).toBeVisible()
  const bookings = bookingList(page)
  for (const [requirement, venue] of [
    [EXPO_HALL, 'Grand Hall'],
    [WORKSHOP_ROOM, 'Seminar Room 2.1'],
    [NETWORKING_LOUNGE, 'Exhibition Foyer'],
  ]) {
    await expect(bookings).toContainText(`For ${requirement}`)
    await expect(bookings).toContainText(venue)
  }

  // AC5: Find a venue is greyed and says so; it opens the catalogue with none selected.
  await expect(page.getByRole('link', { name: FIND_A_VENUE })).toHaveCount(0)
  await page.getByRole('link', { name: ALL_BOOKED }).click()
  await expect(catalogueBanner(page, FORUM.name)).toContainText('an additional venue')
  expect(new URL(page.url()).searchParams.has('requirement')).toBe(false)
  for (const name of [EXPO_HALL, WORKSHOP_ROOM, NETWORKING_LOUNGE]) {
    await expect(requirementChoice(page, name)).toHaveAttribute('aria-pressed', 'false')
  }

  // AC8: withdrawing the workshop room's request makes it need a venue again.
  await openEvent(page, FORUM)
  await page.getByRole('button', { name: `Withdraw Seminar Room 2.1 for ${WORKSHOP_ROOM}` }).click()
  const dialog = page.getByRole('dialog', { name: 'Withdraw this booking request?' })
  await dialog.getByRole('button', { name: 'Withdraw' }).click()
  await expect(dialog).not.toBeVisible()
  await page.getByRole('link', { name: FIND_A_VENUE }).click()
  await expect(requirementChoice(page, WORKSHOP_ROOM)).toHaveAttribute('aria-pressed', 'true')
  await expect(requirementChoice(page, WORKSHOP_ROOM)).toContainText('Needs a venue')
})

test('12.5 AC2/AC5: an event whose every requirement is booked offers an additional venue', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, WORKSHOP)

  await expect(bookingList(page)).toContainText('For Meeting room')
  await expect(bookingList(page)).toContainText('Boardroom 3.4')
  await expect(page.getByRole('link', { name: FIND_A_VENUE })).toHaveCount(0)
  await page.getByRole('link', { name: ALL_BOOKED }).click()

  const banner = catalogueBanner(page, WORKSHOP.name)
  await expect(banner.getByRole('listitem')).toContainText('Meeting room')
  await expect(banner.getByRole('listitem')).toContainText('Booked: Boardroom 3.4')
  await expect(banner).toContainText('an additional venue')
  expect(new URL(page.url()).searchParams.has('requirement')).toBe(false)
})

test('12.5 AC5: an additional venue is requested beside the booked requirement', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, WORKSHOP)
  await page.getByRole('link', { name: ALL_BOOKED }).click()

  await venueCard(page, 'Seminar Room 2.1').getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  const carries = page.getByRole('region', { name: 'What this request will carry' })
  await expect(carries).toContainText('Additional venue')
  await expect(carries).toContainText('Tue, 6 Jun 2028 · 09:00–12:00')
  await page.getByRole('button', { name: 'Send request' }).click()

  await expect(notice(page, 'Seminar Room 2.1 was requested as an additional venue')).toBeVisible()
  await expect(page.getByRole('heading', { name: WORKSHOP.name, level: 1 })).toBeVisible()
  await expect(bookingList(page)).toContainText('Additional venue')
  await expect(bookingList(page)).toContainText('Seminar Room 2.1')
})

test('12.5 AC7: an event marked "No venue requirements" keeps Find a venue as it is', async ({
  page,
}) => {
  // No seeded Planning event records "No venue requirements", so Summit's real record is answered
  // with it set, as 12.1 AC15's case for Nimbus does.
  await page.route(`**/events/${SUMMIT.id}`, async (route) => {
    if (route.request().resourceType() !== 'fetch') return route.fallback()
    const response = await route.fetch()
    const event = await response.json()
    return route.fulfill({
      response,
      json: { ...event, venue_none_required: true, venue_requirements: [] },
    })
  })
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, SUMMIT)

  await expect(page.getByRole('link', { name: FIND_A_VENUE })).toBeVisible()
  await expect(page.getByRole('link', { name: ALL_BOOKED })).toHaveCount(0)
})
