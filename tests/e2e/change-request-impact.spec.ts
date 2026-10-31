/**
 * Story 19.3 - fe: assess a change request's impact before deciding it.
 *
 * AC1 Each pending change request shows the venue bookings, equipment and registrations it would
 *     affect, and why. Attendance above what the booked venues hold is flagged as a warning only.
 *     If nothing is affected, that is stated.
 * AC2 For each affected arrangement, the assessment says what approval (19.2) will do to it and
 *     who acts on it. No new flag or notification is added.
 * AC7 If the assessment changes after the request is opened, approving shows the new result
 *     before anything is applied.
 * AC8 (fix f19.3.1, CL-171) A booking the approval keeps is flagged when the change leaves its venue
 *     below half full, as a warning only.
 * Definition of Done: the assessment reads at 1280 x 720 and at 390 x 844, the dialog's buttons
 *     stay on screen, and the page never scrolls sideways.
 *
 * Decisions agreed 19 Oct 2026 (CL-152 to CL-154), as these tests show them: the assessment is on
 * the request, in the coordinator's queue and in the approval dialog, one row each for venue
 * bookings, equipment and registrations that says at a glance how much is affected and opens onto
 * each arrangement. A booking the change no longer fits is cancelled, Venue Staff are told and
 * need do nothing, and a replacement is requested from the event page (19.2's own behaviour); each
 * booking also says where it stands now. For AC7, another session adds equipment the new dates
 * must hold; the new assessment is marked as updated, and nothing is applied until the coordinator
 * approves again.
 *
 * Which bookings, items and registrations are affected and why, the boundaries (AC4),
 * unavailability and shortfalls (AC5), who may see the assessment (AC6), that assessing writes
 * nothing (AC3), and that its predictions are what the approval then does (AC2) are backend
 * cases: backend/tests/change_requests/test_assess_change_request_impact.py.
 *
 * A capacity shortfall is a warning only: approving cancels no booking for it, and its advice names
 * only what the coordinator can do - switch a pending request to a larger venue, request an
 * additional venue, or reject the change.
 *
 * Each test builds its own event (`approvedEvent`). The ones that book venues date theirs well away
 * from the day other specs' fresh events fall on, so the venues it requests are free and the holds
 * they leave hide nothing another spec looks for.
 */
import { expect, test, type Page } from '@playwright/test'
import { approvedEvent, changeRequests, inFuture, signIn, venueCard } from './support'

const CHANGE_REASON = 'The keynote speaker can only come a week later.'
const GRAND_HALL = 'Grand Hall'
const EXHIBITION_FOYER = 'Exhibition Foyer'
const NO_IMPACT = 'No existing arrangements are affected.'
const QUEUE_PATH = '/change-requests/review'
const IMPACT_CHANGED =
  'The impact of this change has changed since you opened it. Review the updated impact, then approve again.'
const SHORTFALL_ADVICE =
  'The bookings stay as they are: approving cancels none of them. If everyone needs room at those times, switch a pending request to a larger venue, request an additional venue from the event page (one smaller than the whole attendance needs a justification), or reject the change and tell the organiser why.'
const ATTENDANCE_KEEPS_BOOKINGS =
  'Venue bookings are kept as they are. Check that the venues booked still hold everyone between them, and request an additional venue from the event page if they do not.'

/** A day for an event that books venues: over a year ahead, spread out so reruns rarely meet,
 *  and early enough that a week later is within the two years an event may be planned ahead. */
function farDay(): number {
  return 400 + Math.floor(Math.random() * 120)
}

/** As the organiser, on the event's page: ask to move it a week later. */
async function requestDateChange(page: Page, days: number) {
  await changeRequests(page).getByRole('button', { name: 'Request a change' }).click()
  await changeRequests(page).getByLabel('What to change').selectOption({ label: 'Date and time' })
  await changeRequests(page)
    .getByLabel('New start')
    .fill(inFuture(days + 7, 9))
  await changeRequests(page)
    .getByLabel('New end')
    .fill(inFuture(days + 7, 17))
  await changeRequests(page).getByLabel('Reason for the change').fill(CHANGE_REASON)
  await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()
  await expect(changeRequests(page).getByRole('listitem')).toContainText('Pending')
}

/** As the organiser, on the event's page: ask for a new expected attendance. */
async function requestAttendanceChange(page: Page, attendance: string) {
  await changeRequests(page).getByRole('button', { name: 'Request a change' }).click()
  await changeRequests(page)
    .getByLabel('What to change')
    .selectOption({ label: 'Expected attendance' })
  await changeRequests(page).getByLabel('New expected attendance').fill(attendance)
  await changeRequests(page).getByLabel('Reason for the change').fill(CHANGE_REASON)
  await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()
  await expect(changeRequests(page).getByRole('listitem')).toContainText('Pending')
}

/** As the coordinator, through story 12.5's own steps: Grand Hall for the event's Main venue. */
async function bookGrandHall(page: Page, eventId: string, name: string) {
  await page.goto(`/events/${eventId}`)
  await page.getByRole('link', { name: 'Find a venue' }).click()
  await expect(page.getByRole('region', { name: `Finding a venue for ${name}` })).toBeVisible()
  await venueCard(page, GRAND_HALL).getByRole('link', { name: 'Request this venue' }).click()
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
}

/** As the coordinator: Grand Hall for the event's Main venue, then Exhibition Foyer as an
 *  additional venue. */
async function bookTwoVenues(page: Page, eventId: string, name: string) {
  await bookGrandHall(page, eventId, name)

  await page.getByRole('link', { name: 'All required venues booked' }).click()
  await venueCard(page, EXHIBITION_FOYER).getByRole('link', { name: 'Request this venue' }).click()
  await page.getByRole('button', { name: 'Send request' }).click()
  // The event's page reloads its bookings, equipment and change requests: give it time under load.
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible({
    timeout: 15_000,
  })
}

function approvalDialog(page: Page) {
  return page.getByRole('dialog', { name: 'Approve this change?' })
}

async function hasNoSidewaysScroll(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
}

test('19.3 AC1/AC2: each booked venue the change cancels is listed with why and what happens next', async ({
  page,
}) => {
  test.setTimeout(150_000)
  const days = farDay()
  const { eventId, name, coordinator } = await approvedEvent(page, 'Impact venues', days)
  await requestDateChange(page, days)
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator)
  await bookTwoVenues(page, eventId, name)

  // On the request, at the desktop size Playwright opens with (1280 x 720): the category's row
  // says it at a glance, and opens onto each booking.
  await changeRequests(page).getByRole('button', { name: 'Show impact' }).click()
  const venueRow = changeRequests(page).getByRole('button', {
    name: /^Venue bookings/,
  })
  await expect(venueRow).toContainText('2 affected')
  await expect(venueRow).toContainText('2 bookings will be cancelled on approval.')
  await expect(changeRequests(page).getByRole('button', { name: /^Registrations/ })).toHaveCount(0)
  await expect(changeRequests(page).getByText('No registrations are affected.')).toBeVisible()
  await venueRow.click()
  const bookings = changeRequests(page).getByRole('region', {
    name: 'Venue bookings affected',
  })
  // Each booking's card ends with what happens after approval; its venue checks are a list too.
  const bookingCards = bookings.getByRole('listitem').filter({ hasText: 'After approval' })
  await expect(bookingCards).toHaveCount(2)
  const hall = bookingCards.filter({ hasText: GRAND_HALL })
  await expect(hall).toContainText('Main venue')
  await expect(hall).toContainText('Pending request for')
  await expect(hall).toContainText('Will be cancelled')
  await expect(hall).toContainText('Its booked times no longer cover the times the change needs.')
  await expect(hall).toContainText(
    'Venue Staff are told, and need do nothing; request a replacement from the event page.',
  )
  const foyer = bookingCards.filter({ hasText: EXHIBITION_FOYER })
  await expect(foyer).toContainText('Additional venue')
  await expect(foyer).toContainText('Will be cancelled')
  expect(await hasNoSidewaysScroll(page)).toBe(true)

  // In the approval dialog, on a phone.
  await page.setViewportSize({ width: 390, height: 844 })
  await changeRequests(page).getByRole('button', { name: 'Approve', exact: true }).click()
  const dialog = approvalDialog(page)
  await dialog.getByRole('button', { name: /^Venue bookings/ }).click()
  await expect(
    dialog
      .getByRole('region', { name: 'Venue bookings affected' })
      .getByRole('listitem')
      .filter({ hasText: 'After approval' }),
  ).toHaveCount(2)
  await expect(dialog.getByRole('button', { name: 'Approve' })).toBeInViewport()
  await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeInViewport()
  expect(await hasNoSidewaysScroll(page)).toBe(true)
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  // The request's own card - the assessment shown under it has list items of its own.
  await expect(changeRequests(page).getByRole('listitem').first()).toContainText('Pending')
})

test('19.3 AC1: a change that touches nothing arranged says so, on the event and in the queue', async ({
  page,
}) => {
  test.setTimeout(90_000)
  const { eventId, name, coordinator } = await approvedEvent(page, 'Impact none')
  await requestAttendanceChange(page, '150')

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator)
  await page.goto(`/events/${eventId}`)
  await changeRequests(page).getByRole('button', { name: 'Show impact' }).click()

  await expect(changeRequests(page).getByText(NO_IMPACT)).toBeVisible()

  // The same, from the coordinator's queue.
  await page.goto(QUEUE_PATH)
  const entry = page
    .getByRole('list', { name: 'Pending change requests' })
    .getByRole('listitem')
    .filter({ hasText: name })
  await entry.getByRole('button', { name: 'Show impact' }).click()
  await expect(entry.getByText(NO_IMPACT)).toBeVisible()
})

test('19.3 AC1/AC2: attendance beyond what the booked venues hold is a warning that says what can be done', async ({
  page,
}) => {
  test.setTimeout(120_000)
  const days = farDay()
  const { eventId, name, coordinator } = await approvedEvent(page, 'Impact shortfall', days)
  await requestAttendanceChange(page, '600')
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator)
  await bookGrandHall(page, eventId, name)

  // Grand Hall seats 400 of the 600 now asked for, and its booking is still a pending request.
  await changeRequests(page).getByRole('button', { name: 'Show impact' }).click()
  const venueRow = changeRequests(page).getByRole('button', { name: /^Venue bookings/ })
  await expect(venueRow).toContainText('too small for the 600 now expected')
  await expect(venueRow).not.toContainText('will be cancelled')
  await venueRow.click()
  await expect(
    changeRequests(page).getByText('Not enough room for the new attendance'),
  ).toBeVisible()
  await expect(changeRequests(page).getByText(SHORTFALL_ADVICE)).toBeVisible()

  // Fix f19.2.1: approving says the bookings are kept, in the same words as the advice above.
  await changeRequests(page).getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(approvalDialog(page).getByText(ATTENDANCE_KEEPS_BOOKINGS)).toBeVisible()
})

test('19.3 AC7: an impact that changed after the dialog opened is shown again before anything is applied', async ({
  page,
  browser,
}, testInfo) => {
  test.setTimeout(150_000)
  const { eventId, coordinator } = await approvedEvent(page, 'Impact changed')
  await requestDateChange(page, 30)
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator)
  await page.goto(`/events/${eventId}`)
  await changeRequests(page).getByRole('button', { name: 'Approve', exact: true }).click()
  const dialog = approvalDialog(page)
  await expect(dialog.getByText(NO_IMPACT)).toBeVisible()

  // Meanwhile, in another session, the coordinator records a projector for the event (15.1),
  // which the new dates would have to hold.
  const elsewhere = await browser.newContext({
    baseURL: testInfo.project.use.baseURL,
  })
  const other = await elsewhere.newPage()
  await signIn(other, coordinator)
  await other.goto(`/events/${eventId}`)
  const addForm = other
    .getByRole('region', { name: 'Equipment requirements' })
    .getByRole('form', { name: 'Add equipment' })
  await addForm.getByLabel('Equipment type').selectOption('PROJECTOR_PORTABLE')
  await addForm.getByLabel('Quantity').fill('1')
  await addForm.getByRole('button', { name: 'Add item' }).click()
  await expect(
    other.getByRole('region', { name: 'Equipment requirements' }).getByRole('listitem'),
  ).toContainText('Portable projector')
  await elsewhere.close()

  // Approving on the assessment seen first is refused, and the updated one is shown instead.
  await dialog.getByRole('button', { name: 'Approve' }).click()
  await expect(dialog.getByRole('alert')).toHaveText(IMPACT_CHANGED)
  await expect(dialog).toContainText('Updated impact of approving this change')
  const equipmentRow = dialog.getByRole('button', { name: /^Equipment/ })
  await expect(equipmentRow).toContainText('1 item held again for the new dates.')
  await equipmentRow.click()
  await expect(dialog.getByRole('region', { name: 'Equipment affected' })).toContainText(
    'Portable projector',
  )
  await expect(dialog.getByText(NO_IMPACT)).toHaveCount(0)

  // Approving again, on what is now shown, applies the change.
  await dialog.getByRole('button', { name: 'Approve' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(changeRequests(page).getByRole('listitem')).toContainText('Approved')
})

test('19.3 AC8: a venue the change leaves below half full is flagged, and kept', async ({
  page,
}) => {
  test.setTimeout(150_000)
  const days = farDay()
  const { eventId, name, coordinator } = await approvedEvent(page, 'Impact oversized', days)
  // The fresh event's Main venue needs room for 60: Olivia asks for 50.
  const section = changeRequests(page)
  await section.getByRole('button', { name: 'Request a change' }).click()
  await section.getByLabel('What to change').selectOption({ label: 'Venue requirements' })
  await section.getByLabel('Requirement 1 number of people').fill('50')
  await section.getByLabel('Reason for the change').fill(CHANGE_REASON)
  await section.getByRole('button', { name: 'Send change request' }).click()
  await expect(section.getByRole('listitem')).toContainText('Pending')
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator)
  await bookGrandHall(page, eventId, name)

  // Grand Hall, booked for Main venue, holds 400: 50 is below half of it.
  await section.getByRole('button', { name: 'Show impact' }).click()
  const venueRow = section.getByRole('button', { name: /^Venue bookings/ })
  await expect(venueRow).toContainText('below half full for the people now needed')
  await expect(venueRow).not.toContainText('will be cancelled')
  await venueRow.click()
  const hall = section
    .getByRole('region', { name: 'Venue bookings affected' })
    .getByRole('listitem')
    .filter({ hasText: 'After approval' })
  await expect(hall).toContainText(GRAND_HALL)
  await expect(hall).toContainText('Kept')
  await expect(hall).toContainText('Larger than needed')
  await expect(hall).toContainText(
    `Needs room for 50; ${GRAND_HALL} holds 400, more than twice that.`,
  )
  await expect(hall).toContainText('You decide whether to keep this venue or replace it.')
})
