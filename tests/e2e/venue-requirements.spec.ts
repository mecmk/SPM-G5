/**
 * Story 2.7 - fe/be: record several venue requirements, each with its own times.
 * AC1 the organiser adds more than one venue requirement, each with a name, how many people it
 *     must hold, a room layout, facilities (each optionally how many) and other requirements.
 * AC2 a new requirement's start and end default to the event's (Singapore time) and can be
 *     changed; while they still match the event they keep following it, before and after a save
 *     (CL-087).
 * AC3 requirements are added, edited and removed on a draft. (f2.7.4 took away "No venue
 *     requirements", which cleared them.)
 * AC4 every requirement, with its times, is shown to the reviewing coordinator on the event page,
 *     with both dates when it runs over more than one day.
 * AC5/AC9/AC10 a requirement outside the event, a repeated name, or an event moved past a
 *     requirement's own times is said under the field as it is typed (a client-side check, the
 *     AGENTS.md exception); the server's refusal of each is a backend case.
 * AC6 the first requirement's number of people defaults to the expected attendance, and follows
 *     it while it still matches.
 * AC8 an incomplete requirement is listed as still needed before submitting.
 * AC11 the requirement field to fix is marked and focused when a save is refused - in the browser,
 *     or by the server, which says which requirement and field in its refusal.
 * f2.7.4 - every request has at least one venue requirement:
 * AC14 a new request starts with one, and the form no longer offers "No venue requirements".
 * AC14/AC16 the only one cannot be removed: while it is the last, its Remove is disabled and a
 *     hint says why (a client-side check, the AGENTS.md exception; nothing is sent).
 * AC17 a draft saved with "No venue requirements" before the fix opens with one to fill in, and the
 *     coordinator's form for a request submitted without one says one is needed. Until a decision,
 *     the event page shows such a request's venue requirements as not recorded, not as "No venue
 *     is required" (an event approved with it keeps that line, AC19: 8.4 AC6's case in
 *     venue-requirement-search.spec.ts). No seeded event records that answer, so each case answers
 *     the event's own GET with it set, as 12.1 AC15's case for Nimbus does, and saves nothing.
 * AC18 the change request form (19.1) keeps the event's last requirement, and starts an event
 *     with none with one to fill in.
 * Rule detail, refusals (401/403/404/409/422), the migration (AC7), the server's refusal of a
 * repeated name (AC9) or a moved event (AC10), the race with a submission (AC12) and what a booking
 * request carries (AC13) are backend cases:
 * backend/tests/events/test_multiple_venue_requirements.py. So are f2.7.4's server rules: a save,
 * submission, correction or approval without a requirement, and the refused "none" answer
 * (AC14-AC17, AC20), in backend/tests/events/test_at_least_one_venue_requirement.py; a change
 * request that would leave none (AC18, AC20), in
 * backend/tests/change_requests/test_keep_a_venue_requirement.py. AC15's list of what is still
 * needed is event-request.spec.ts's.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  assignByLead,
  changeRequests,
  corsHeaders,
  EVENTS,
  inFuture,
  signIn,
  uniqueName,
} from './support'

const EDIT_PATH = /\/events\/[0-9a-f-]{36}\/edit$/
const COORDINATOR_EDIT_PATH = /\/events\/[0-9a-f-]{36}\/coordinator-edit$/
const MY_EVENTS_PATH = /\/events\/mine$/
// f2.7.4: what the forms say, word for word.
const NO_VENUE_REQUIREMENTS = 'No venue requirements'
const LAST_REQUIREMENT_HINT =
  'Every event needs at least one venue requirement, so the last one cannot be removed.'
const STILL_NEEDED_A_REQUIREMENT = 'Still needed: venue requirements (at least one).'
// The change request form's line for an empty list, which f2.7.4 takes away.
const NO_VENUE_NEEDED_LINE = 'No venue requirements - the event will need no venue.'
// The event page's line for "No venue requirements", and its line for nothing recorded.
const NO_VENUE_IS_REQUIRED = 'No venue is required for this event.'
const NOT_RECORDED = 'Not recorded'

function requirement(page: Page, position: number): Locator {
  return page.getByRole('group', { name: `Venue requirement ${position}` })
}

async function startNewRequest(page: Page, name: string, attendance = '60') {
  await page.goto('/events/new')
  await expect(page.getByRole('heading', { name: 'New event request' })).toBeVisible()
  await page.getByLabel('Event name').fill(name)
  await page.getByLabel('Purpose').fill('Staff training')
  await page.getByLabel('Description').fill('One-day hands-on workshop.')
  await page.getByLabel('Proposed start').fill(inFuture(30, 9))
  await page.getByLabel('Proposed end').fill(inFuture(30, 17))
  await page.getByLabel('Expected attendance').fill(attendance)
}

/** Name the venue requirement at `position`, first adding a card for it unless it is the first:
 * a new request starts with one (f2.7.4, AC14). */
async function addRequirement(page: Page, position: number, name: string, people?: string) {
  if (position > 1) await page.getByRole('button', { name: 'Add a venue requirement' }).click()
  const added = requirement(page, position)
  await added.getByLabel('Requirement name').fill(name)
  if (people !== undefined) await added.getByLabel('Number of people').fill(people)
  return added
}

async function saveDraft(page: Page) {
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)
}

/** Save a draft that already has its own address. The URL does not change, so wait for the server
 * to answer the edit instead, or a reload straight after could race it. */
async function saveEdits(page: Page) {
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.request().method() === 'PATCH' &&
        /\/events\/[0-9a-f-]{36}$/.test(new URL(response.url()).pathname),
    ),
    page.getByRole('button', { name: 'Save draft' }).click(),
  ])
}

/**
 * f2.7.4 (AC17): the event as one saved with "No venue requirements" before the fix. No seeded
 * event records that answer, so its real record is answered with it set and no requirement, as
 * 12.1 AC15's case for Nimbus does. Only the record's GET is answered: the page's own navigation
 * and any save go through untouched.
 */
async function answerAsMarkedNone(page: Page, eventId: string) {
  await page.route(`**/events/${eventId}`, async (route) => {
    const request = route.request()
    if (request.resourceType() !== 'fetch' || request.method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const event = await response.json()
    return route.fulfill({
      response,
      json: { ...event, venue_none_required: true, venue_requirements: [] },
    })
  })
}

/** Every POST or PATCH the page sends to an /events address from now on, so a test can show that
 * nothing was saved or sent. */
function eventWrites(page: Page): string[] {
  const sent: string[] = []
  page.on('request', (request) => {
    const isWrite = request.method() === 'POST' || request.method() === 'PATCH'
    if (isWrite && new URL(request.url()).pathname.startsWith('/events')) {
      sent.push(`${request.method()} ${request.url()}`)
    }
  })
  return sent
}

/** Story 19.1's change requests on the event page, opened for one field as
 * change-requests.spec.ts opens them. */
async function openChangeForm(page: Page, field: string) {
  await changeRequests(page).getByRole('button', { name: 'Request a change' }).click()
  await changeRequests(page).getByLabel('What to change').selectOption({ label: field })
}

test('2.7 AC1: the organiser adds two venue requirements, each with its own details', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, uniqueName('Two rooms'))

  const plenary = await addRequirement(page, 1, 'Plenary hall', '60')
  await plenary.getByLabel('Room layout').selectOption({ label: 'Theatre' })
  await plenary.getByRole('checkbox', { name: 'Projector & screen', exact: true }).check()
  await plenary.getByLabel('Other requirements').fill('Near the lifts')
  const breakout = await addRequirement(page, 2, 'Breakout', '20')
  await breakout.getByLabel('Room layout').selectOption({ label: 'Classroom' })
  await breakout.getByRole('checkbox', { name: 'Breakout rooms', exact: true }).check()
  await breakout.getByLabel('Breakout rooms quantity').fill('3')
  await saveDraft(page)

  await page.reload()
  await expect(requirement(page, 1).getByLabel('Requirement name')).toHaveValue('Plenary hall')
  await expect(requirement(page, 1).getByLabel('Number of people')).toHaveValue('60')
  await expect(requirement(page, 1).getByLabel('Room layout')).toHaveValue('THEATRE')
  await expect(
    requirement(page, 1).getByRole('checkbox', { name: 'Projector & screen', exact: true }),
  ).toBeChecked()
  await expect(requirement(page, 1).getByLabel('Other requirements')).toHaveValue('Near the lifts')
  await expect(requirement(page, 2).getByLabel('Requirement name')).toHaveValue('Breakout')
  await expect(requirement(page, 2).getByLabel('Number of people')).toHaveValue('20')
  await expect(requirement(page, 2).getByLabel('Room layout')).toHaveValue('CLASSROOM')
  await expect(requirement(page, 2).getByLabel('Breakout rooms quantity')).toHaveValue('3')
})

test("2.7 AC2: a new requirement starts with the event's times, which can be changed", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, uniqueName('Own times'))

  const breakout = await addRequirement(page, 1, 'Breakout', '20')
  await expect(breakout.getByLabel('Needed from')).toHaveValue(inFuture(30, 9))
  await expect(breakout.getByLabel('Needed until')).toHaveValue(inFuture(30, 17))

  await breakout.getByLabel('Needed from').fill(inFuture(30, 13))
  await saveDraft(page)
  await page.reload()

  await expect(requirement(page, 1).getByLabel('Needed from')).toHaveValue(inFuture(30, 13))
  await expect(requirement(page, 1).getByLabel('Needed until')).toHaveValue(inFuture(30, 17))
})

test('2.7 AC3: requirements are added, edited and removed on a draft', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, uniqueName('Edit rooms'))
  await addRequirement(page, 1, 'Plenary hall', '60')
  await addRequirement(page, 2, 'Breakout', '20')
  await saveDraft(page)

  // Remove the first; the second becomes requirement 1. Rename it and save.
  await page.reload()
  await requirement(page, 1).getByRole('button', { name: 'Remove' }).click()
  await expect(requirement(page, 1).getByLabel('Requirement name')).toHaveValue('Breakout')
  await expect(requirement(page, 2)).toHaveCount(0)
  await requirement(page, 1).getByLabel('Requirement name').fill('Breakout rooms')
  await saveEdits(page)
  await page.reload()
  await expect(requirement(page, 1).getByLabel('Requirement name')).toHaveValue('Breakout rooms')
  await expect(requirement(page, 2)).toHaveCount(0)
})

test('2.7 AC4: the event page lists each venue requirement with its times', async ({ page }) => {
  const name = uniqueName('Shown rooms')
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, name)
  await addRequirement(page, 1, 'Plenary hall', '60')
  const breakout = await addRequirement(page, 2, 'Breakout', '20')
  await breakout.getByLabel('Needed from').fill(inFuture(30, 13))
  await page.getByLabel('Contact name').fill('Priya Nair')
  await page.getByLabel('Contact email').fill('priya.nair@example.com')
  await page.getByLabel('Contact phone number').fill('+65 9123 4567')
  await page.getByRole('checkbox', { name: 'No accessibility needs' }).check()
  await saveDraft(page)
  const eventPath = page.url().replace(/\/edit$/, '')
  await page.getByRole('button', { name: 'Submit request' }).click()
  await expect(page).toHaveURL(MY_EVENTS_PATH)

  await page.goto(eventPath)
  const coordinator = await assignByLead(page)
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator.account)
  await page.goto(eventPath)

  const venue = page.getByRole('region', { name: 'Venue requirements' })
  const plenary = venue.getByRole('listitem').filter({ hasText: 'Plenary hall' })
  const breakoutShown = venue.getByRole('listitem').filter({ hasText: 'Breakout' })
  await expect(plenary).toContainText('60 people')
  await expect(plenary).toContainText('09:00–17:00')
  await expect(breakoutShown).toContainText('20 people')
  await expect(breakoutShown).toContainText('13:00–17:00')
})

test("2.7 AC6: the first requirement's number of people starts at the expected attendance", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, uniqueName('Default people'), '75')

  // The card a new request starts with (f2.7.4) is the first requirement.
  await expect(requirement(page, 1).getByLabel('Number of people')).toHaveValue('75')

  // Only the first: a second room is rarely the whole audience, so it is left for the organiser.
  await page.getByRole('button', { name: 'Add a venue requirement' }).click()
  await expect(requirement(page, 2).getByLabel('Number of people')).toHaveValue('')
})

test('2.7 AC8: an incomplete requirement is pointed out before submitting', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, uniqueName('Incomplete room'))
  const needed = page.getByText(/To submit, still needed:/)

  // The card a new request starts with (f2.7.4), its number of people cleared.
  await requirement(page, 1).getByLabel('Number of people').fill('')
  await expect(needed).toContainText('venue requirement 1: name')
  await expect(needed).toContainText('venue requirement 1: number of people')

  await requirement(page, 1).getByLabel('Requirement name').fill('Plenary hall')
  await requirement(page, 1).getByLabel('Number of people').fill('60')
  await expect(needed).not.toContainText('venue requirement 1')

  // A draft may hold an incomplete requirement: saving it is not refused.
  await addRequirement(page, 2, 'Breakout')
  await saveDraft(page)
  await expect(needed).toContainText('venue requirement 2: number of people')
})

test('2.7 AC11: the requirement field to fix is marked and focused', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, uniqueName('Mark room'))

  await addRequirement(page, 1, 'Plenary hall', '60')
  const breakout = await addRequirement(page, 2, 'Breakout', '61')
  await page.getByRole('button', { name: 'Save draft' }).click()
  const people = breakout.getByLabel('Number of people')
  await expect(people).toBeFocused()
  await expect(people).toHaveAttribute('aria-invalid', 'true')
  await expect(requirement(page, 1).getByLabel('Number of people')).not.toHaveAttribute(
    'aria-invalid',
    'true',
  )
  await people.fill('20')

  await breakout.getByLabel('Needed until').fill(inFuture(30, 18))
  await page.getByRole('button', { name: 'Save draft' }).click()
  const until = breakout.getByLabel('Needed until')
  await expect(until).toBeFocused()
  await expect(until).toHaveAttribute('aria-invalid', 'true')
  await until.fill(inFuture(30, 17))

  await breakout.getByLabel('Requirement name').fill(' plenary HALL ')
  await page.getByRole('button', { name: 'Save draft' }).click()
  const duplicateName = breakout.getByLabel('Requirement name')
  await expect(duplicateName).toBeFocused()
  await expect(duplicateName).toHaveAttribute('aria-invalid', 'true')
})

test('2.7 AC11: a save the server refuses marks the requirement field it names', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, uniqueName('Server refusal'))
  await addRequirement(page, 1, 'Plenary hall', '60')
  await addRequirement(page, 2, 'Breakout', '20')
  await saveDraft(page)

  // A refusal only the server can give - say the form was stale - is stubbed: the browser's own
  // checks would otherwise stop this save first. The server names requirement 2's end time.
  const refusal = 'Breakout cannot end after the event ends.'
  await page.route(
    (url) => /\/events\/[0-9a-f-]{36}$/.test(url.pathname),
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch' || request.method() !== 'PATCH') {
        return route.fallback()
      }
      return route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: [
            {
              loc: ['body', 'venue_requirements', 1, 'ends_at'],
              msg: refusal,
              type: 'value_error',
            },
          ],
        }),
        headers: corsHeaders(request),
      })
    },
  )
  await page.getByRole('button', { name: 'Save draft' }).click()

  const until = requirement(page, 2).getByLabel('Needed until')
  await expect(until).toBeFocused()
  await expect(until).toHaveAttribute('aria-invalid', 'true')
  await expect(requirement(page, 1).getByLabel('Needed until')).not.toHaveAttribute(
    'aria-invalid',
    'true',
  )
  await expect(page.getByRole('alert')).toHaveText(refusal)
})

test('2.7 AC5/AC9/AC10: a venue requirement problem is said next to its field as soon as it is typed', async ({
  page,
}) => {
  const endsAfter = 'A venue requirement cannot end after the event ends.'
  const duplicate = 'Two venue requirements cannot have the same name.'
  const startsBefore = 'A venue requirement cannot start before the event starts.'
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, uniqueName('Live problems'))
  await addRequirement(page, 1, 'Plenary hall', '60')
  const breakout = await addRequirement(page, 2, 'Breakout', '20')

  // AC5: an end after the event's is said under that field, before any save.
  await breakout.getByLabel('Needed until').fill(inFuture(30, 18))
  await expect(breakout.getByText(endsAfter)).toBeVisible()
  await expect(breakout.getByLabel('Needed until')).toHaveAttribute('aria-invalid', 'true')
  await expect(requirement(page, 1).getByText(endsAfter)).toHaveCount(0)
  await breakout.getByLabel('Needed until').fill(inFuture(30, 17))
  await expect(breakout.getByText(endsAfter)).toHaveCount(0)

  // AC9: a name another requirement already has, trimmed and in any case.
  await breakout.getByLabel('Requirement name').fill(' plenary HALL ')
  await expect(breakout.getByText(duplicate)).toBeVisible()
  await expect(requirement(page, 1).getByText(duplicate)).toHaveCount(0)
  await breakout.getByLabel('Requirement name').fill('Breakout')
  await expect(breakout.getByText(duplicate)).toHaveCount(0)

  // AC10: times the organiser chose are theirs, so moving the event's start past them says so
  // under the requirement at once - before or after a save (CL-087: only times that still match
  // the event follow it).
  await requirement(page, 1).getByLabel('Needed from').fill(inFuture(30, 10))
  await saveDraft(page)
  await page.getByLabel('Proposed start').fill(inFuture(30, 11))
  await expect(requirement(page, 1).getByText(startsBefore)).toBeVisible()
  await expect(requirement(page, 1).getByLabel('Needed from')).toHaveAttribute(
    'aria-invalid',
    'true',
  )
  await requirement(page, 1).getByLabel('Needed from').fill(inFuture(30, 11))
  await expect(requirement(page, 1).getByText(startsBefore)).toHaveCount(0)
})

test("2.7 AC2/AC6: a new requirement's times and number follow the event's until they are changed", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto('/events/new')
  await expect(page.getByRole('heading', { name: 'New event request' })).toBeVisible()
  await page.getByLabel('Event name').fill(uniqueName('Follow defaults'))

  // The card a new request starts with (f2.7.4), and one added before the event's dates and
  // attendance are known: the defaults arrive with them.
  await page.getByRole('button', { name: 'Add a venue requirement' }).click()
  await page.getByLabel('Proposed start').fill(inFuture(30, 9))
  await page.getByLabel('Proposed end').fill(inFuture(30, 17))
  await page.getByLabel('Expected attendance').fill('60')
  const first = requirement(page, 1)
  await expect(first.getByLabel('Needed from')).toHaveValue(inFuture(30, 9))
  await expect(first.getByLabel('Needed until')).toHaveValue(inFuture(30, 17))
  await expect(first.getByLabel('Number of people')).toHaveValue('60')
  // AC6: only the first requirement takes the attendance.
  await expect(requirement(page, 2).getByLabel('Number of people')).toHaveValue('')

  // Still untouched, so they keep following.
  await page.getByLabel('Expected attendance').fill('75')
  await expect(first.getByLabel('Number of people')).toHaveValue('75')

  // Once the organiser changes a value, it is theirs and stays put.
  await first.getByLabel('Number of people').fill('50')
  await first.getByLabel('Needed from').fill(inFuture(30, 13))
  await page.getByLabel('Expected attendance').fill('80')
  await page.getByLabel('Proposed start').fill(inFuture(30, 8))
  await expect(first.getByLabel('Number of people')).toHaveValue('50')
  await expect(first.getByLabel('Needed from')).toHaveValue(inFuture(30, 13))
  // The second requirement's times were never touched, so they moved with the event.
  await expect(requirement(page, 2).getByLabel('Needed from')).toHaveValue(inFuture(30, 8))
})

test("2.7 AC3: each requirement's Remove button and facility quantities say which requirement they belong to", async ({
  page,
}) => {
  // Review of PR #84: every card repeats the same controls, so a screen reader must hear which
  // requirement each one acts on, not just "Remove".
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, uniqueName('Labelled controls'))
  await addRequirement(page, 1, 'Plenary hall', '60')
  const breakout = await addRequirement(page, 2, 'Breakout', '20')
  await breakout.getByRole('checkbox', { name: 'Breakout rooms', exact: true }).check()

  await expect(
    page.getByLabel('Breakout rooms quantity, venue requirement 2', { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Remove venue requirement 1', exact: true }),
  ).toBeVisible()

  await page.getByRole('button', { name: 'Remove venue requirement 2', exact: true }).click()
  await expect(requirement(page, 2)).toHaveCount(0)
  await expect(requirement(page, 1).getByLabel('Requirement name')).toHaveValue('Plenary hall')
})

test('2.7 AC2/AC6: a saved requirement that still matches the event keeps following it', async ({
  page,
}) => {
  // Review of PR #84: growing the event after a save must not leave an untouched requirement at
  // the old size and dates, where 12.1 would book it.
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, uniqueName('Grow after save'))
  await addRequirement(page, 1, 'Main hall')
  const breakout = await addRequirement(page, 2, 'Breakout', '20')
  await breakout.getByLabel('Needed from').fill(inFuture(30, 13))
  await saveDraft(page)
  await page.reload()

  await page.getByLabel('Proposed end').fill(inFuture(31, 17))
  await page.getByLabel('Expected attendance').fill('200')

  const mainHall = requirement(page, 1)
  await expect(mainHall.getByLabel('Needed from')).toHaveValue(inFuture(30, 9))
  await expect(mainHall.getByLabel('Needed until')).toHaveValue(inFuture(31, 17))
  await expect(mainHall.getByLabel('Number of people')).toHaveValue('200')
  // Breakout's times were the organiser's own, so they stay put.
  await expect(requirement(page, 2).getByLabel('Needed from')).toHaveValue(inFuture(30, 13))
  await expect(requirement(page, 2).getByLabel('Needed until')).toHaveValue(inFuture(30, 17))

  await saveEdits(page)
  await page.reload()
  await expect(mainHall.getByLabel('Needed until')).toHaveValue(inFuture(31, 17))
  await expect(mainHall.getByLabel('Number of people')).toHaveValue('200')
})

test('2.7 AC4: a requirement spanning two days shows both dates', async ({ page }) => {
  // Review of PR #84: the seeded Regional Sales Summit's Main venue runs 15 Dec 09:00 to 16 Dec
  // 17:00, so its line must say both days, not just the first.
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.planning}`)

  const venue = page.getByRole('region', { name: 'Venue requirements' })
  const mainVenue = venue.getByRole('listitem').filter({ hasText: 'Main venue' })
  await expect(mainVenue).toContainText('15 Dec 2026')
  await expect(mainVenue).toContainText('16 Dec 2026')
  await expect(mainVenue).toContainText('09:00')
  await expect(mainVenue).toContainText('17:00')
})

test('2.7 AC14: a new request starts with one venue requirement and offers no "No venue requirements"', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, uniqueName('Starting room'))

  await expect(requirement(page, 1)).toBeVisible()
  await expect(requirement(page, 2)).toHaveCount(0)
  await expect(page.getByRole('checkbox', { name: NO_VENUE_REQUIREMENTS })).toHaveCount(0)

  await requirement(page, 1).getByLabel('Requirement name').fill('Main hall')
  await saveDraft(page)
  await page.reload()
  await expect(requirement(page, 1).getByLabel('Requirement name')).toHaveValue('Main hall')
  await expect(requirement(page, 2)).toHaveCount(0)
})

test('2.7 AC14/AC16: the only venue requirement cannot be removed', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  const sent = eventWrites(page)
  await startNewRequest(page, uniqueName('Last room'))
  const removeFirst = page.getByRole('button', { name: 'Remove venue requirement 1', exact: true })
  const removeSecond = page.getByRole('button', { name: 'Remove venue requirement 2', exact: true })
  const hint = page.getByText(LAST_REQUIREMENT_HINT)

  // The card a new request starts with is its only one.
  await expect(removeFirst).toBeDisabled()
  await expect(hint).toBeVisible()
  await addRequirement(page, 1, 'Plenary hall')

  // With a second, either can go.
  await addRequirement(page, 2, 'Breakout', '20')
  await expect(removeFirst).toBeEnabled()
  await expect(removeSecond).toBeEnabled()
  await expect(hint).toHaveCount(0)

  // Removing one leaves the other as the only one, which cannot be removed in turn.
  await removeFirst.click()
  await expect(requirement(page, 1).getByLabel('Requirement name')).toHaveValue('Breakout')
  await expect(requirement(page, 2)).toHaveCount(0)
  await expect(removeFirst).toBeDisabled()
  await expect(hint).toBeVisible()
  expect(sent).toEqual([])
})

test('2.7 AC17: a draft saved with "No venue requirements" before this fix opens with one to fill in', async ({
  page,
}) => {
  // Nothing is saved: Olivia's seeded draft, with no dates or attendance yet, is only looked at.
  await answerAsMarkedNone(page, EVENTS.draft)
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.draft}/edit`)
  await expect(page.getByLabel('Event name')).toHaveValue('Q1 Sales Kick-off (draft)')

  const added = requirement(page, 1)
  await expect(added).toBeVisible()
  await expect(requirement(page, 2)).toHaveCount(0)
  await expect(added.getByLabel('Requirement name')).toHaveValue('')
  await expect(added.getByLabel('Number of people')).toHaveValue('')
  await expect(page.getByRole('checkbox', { name: NO_VENUE_REQUIREMENTS })).toHaveCount(0)
  await expect(page.getByText(/To submit, still needed:/)).toContainText(
    'venue requirement 1: name',
  )

  // It is the card a new request starts with: its number of people follows the attendance.
  await page.getByLabel('Expected attendance').fill('75')
  await expect(added.getByLabel('Number of people')).toHaveValue('75')
})

test("2.7 AC17: the coordinator's form for a request submitted without a venue requirement says one is needed", async ({
  page,
}) => {
  // Nothing is saved: Olivia's Data Literacy Workshop, under review with Chloe, is only looked at.
  await answerAsMarkedNone(page, EVENTS.submitted)
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.submitted}`)
  await page.getByRole('link', { name: 'Edit event' }).click()
  await expect(page).toHaveURL(COORDINATOR_EDIT_PATH)
  await expect(page.getByLabel('Purpose')).toBeEnabled()
  const save = page.getByRole('button', { name: 'Save changes' })

  // No card is made up for it: the request as submitted has none, which is what is missing.
  await expect(page.getByText(STILL_NEEDED_A_REQUIREMENT)).toBeVisible()
  await expect(page.getByRole('checkbox', { name: NO_VENUE_REQUIREMENTS })).toHaveCount(0)
  await expect(requirement(page, 1)).toHaveCount(0)
  await expect(save).toBeDisabled()

  // The coordinator adds one, the only one, so it cannot be removed.
  await page.getByRole('button', { name: 'Add a venue requirement' }).click()
  await expect(requirement(page, 1)).toBeVisible()
  await expect(requirement(page, 2)).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Remove venue requirement 1', exact: true }),
  ).toBeDisabled()
  await expect(page.getByText(LAST_REQUIREMENT_HINT)).toBeVisible()
  await expect(save).toBeEnabled()
})

test('2.7 AC17: the page of a request submitted with "No venue requirements" before this fix shows none recorded', async ({
  page,
}) => {
  // Nothing is saved: Olivia's Data Literacy Workshop, under review with Chloe, is only looked at.
  // Approving it is refused until it has a venue requirement, so its page must not say none is
  // needed.
  await answerAsMarkedNone(page, EVENTS.submitted)
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.submitted}`)

  const venue = page.getByRole('region', { name: 'Venue requirements' })
  await expect(venue.getByText(NOT_RECORDED, { exact: true })).toBeVisible()
  await expect(page.getByText(NO_VENUE_IS_REQUIRED)).toHaveCount(0)
})

test('2.7 AC17: the page of a draft saved with "No venue requirements" before this fix shows none recorded', async ({
  page,
}) => {
  // Nothing is saved: Olivia's seeded draft is only looked at. It cannot be submitted until it has
  // a venue requirement.
  await answerAsMarkedNone(page, EVENTS.draft)
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.draft}`)

  const venue = page.getByRole('region', { name: 'Venue requirements' })
  await expect(venue.getByText(NOT_RECORDED, { exact: true })).toBeVisible()
  await expect(page.getByText(NO_VENUE_IS_REQUIRED)).toHaveCount(0)
})

test("2.7 AC18: the change request form keeps the event's last venue requirement", async ({
  page,
}) => {
  // Nothing is sent: Olivia's Regional Sales Summit, with its one Main venue, is only looked at.
  await signIn(page, ACCOUNTS.organiser)
  const sent = eventWrites(page)
  await page.goto(`/events/${EVENTS.planning}`)
  const section = changeRequests(page)
  const removeFirst = section.getByRole('button', { name: 'Remove requirement 1', exact: true })
  const removeSecond = section.getByRole('button', { name: 'Remove requirement 2', exact: true })
  const hint = section.getByText(LAST_REQUIREMENT_HINT)

  await openChangeForm(page, 'Venue requirements')
  await expect(section.getByLabel('Requirement 1 name')).toHaveValue('Main venue')
  await expect(removeFirst).toBeDisabled()
  await expect(hint).toBeVisible()

  await section.getByRole('button', { name: 'Add a venue requirement' }).click()
  await expect(removeFirst).toBeEnabled()
  await expect(removeSecond).toBeEnabled()
  await expect(hint).toHaveCount(0)

  await removeSecond.click()
  await expect(section.getByLabel('Requirement 2 name')).toHaveCount(0)
  await expect(section.getByLabel('Requirement 1 name')).toHaveValue('Main venue')
  await expect(removeFirst).toBeDisabled()
  await expect(hint).toBeVisible()
  expect(sent).toEqual([])
})

test('2.7 AC18: an event with no venue requirement starts the change form with one to fill in', async ({
  page,
}) => {
  // Nothing is sent: Olivia's Product Launch Showcase, approved with no venue requirement, is only
  // looked at.
  await signIn(page, ACCOUNTS.organiser)
  const sent = eventWrites(page)
  await page.goto(`/events/${EVENTS.equipmentShowcase}`)
  const section = changeRequests(page)

  await openChangeForm(page, 'Venue requirements')
  await expect(section.getByLabel('Requirement 1 name')).toHaveValue('')
  await expect(section.getByLabel('Requirement 1 number of people')).toHaveValue('')
  await expect(section.getByLabel('Requirement 2 name')).toHaveCount(0)
  await expect(
    section.getByRole('button', { name: 'Remove requirement 1', exact: true }),
  ).toBeDisabled()
  await expect(section.getByText(LAST_REQUIREMENT_HINT)).toBeVisible()
  await expect(section.getByText(NO_VENUE_NEEDED_LINE)).toHaveCount(0)
  expect(sent).toEqual([])
})

test("2.7 AC2/AC14: the starting venue requirement takes the event's times only once they are a valid start and end", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto('/events/new')
  await expect(page.getByRole('heading', { name: 'New event request' })).toBeVisible()
  const neededFrom = requirement(page, 1).getByLabel('Needed from')
  const neededUntil = requirement(page, 1).getByLabel('Needed until')

  // An end before the start is the event's own mistake, said once, under its dates: the card it
  // starts with does not copy it and get marked as well.
  await page.getByLabel('Proposed start').fill(inFuture(30, 17))
  await page.getByLabel('Proposed end').fill(inFuture(30, 9))
  await expect(
    page.getByText('The proposed end date and time must be after the start date and time.'),
  ).toBeVisible()
  await expect(neededFrom).toHaveValue('')
  await expect(neededUntil).toHaveValue('')
  await expect(neededUntil).not.toHaveAttribute('aria-invalid', 'true')
  await expect(page.getByText('A venue requirement must end after it starts.')).toHaveCount(0)

  // Once the dates are right, the card takes them.
  await page.getByLabel('Proposed end').fill(inFuture(30, 18))
  await expect(neededFrom).toHaveValue(inFuture(30, 17))
  await expect(neededUntil).toHaveValue(inFuture(30, 18))
})
