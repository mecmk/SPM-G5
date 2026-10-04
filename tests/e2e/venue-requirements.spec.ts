/**
 * Story 2.7 - fe/be: record several venue requirements, each with its own times.
 * AC1 the organiser adds more than one venue requirement, each with a name, how many people it
 *     must hold, a room layout, facilities (each optionally how many) and other requirements.
 * AC2 a new requirement's start and end default to the event's (Singapore time) and can be
 *     changed.
 * AC3 requirements are added, edited and removed on a draft; "No venue requirements" clears them.
 * AC4 every requirement, with its times, is shown to the reviewing coordinator on the event page.
 * AC6 the first requirement's number of people defaults to the expected attendance.
 * AC8 an incomplete requirement is listed as still needed before submitting.
 * AC11 the requirement field to fix is marked and focused when a save is refused - in the browser,
 *     or by the server, which says which requirement and field in its refusal.
 * Rule detail, refusals (401/403/404/409/422), the migration (AC7), unique names (AC9), moving the
 * event (AC10) and the race with a submission (AC12) are backend cases:
 * backend/tests/events/test_multiple_venue_requirements.py.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  assignedCoordinator,
  corsHeaders,
  inFuture,
  signIn,
  uniqueName,
} from './support'

const EDIT_PATH = /\/events\/[0-9a-f-]{36}\/edit$/
const MY_EVENTS_PATH = /\/events\/mine$/

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

async function addRequirement(page: Page, position: number, name: string, people?: string) {
  await page.getByRole('button', { name: 'Add a venue requirement' }).click()
  const added = requirement(page, position)
  await added.getByLabel('Requirement name').fill(name)
  if (people !== undefined) await added.getByLabel('Number of people').fill(people)
  return added
}

async function saveDraft(page: Page) {
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)
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

test('2.7 AC3: requirements are added, edited and removed on a draft, and "No venue requirements" clears them', async ({
  page,
}) => {
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
  await saveDraft(page)
  await page.reload()
  await expect(requirement(page, 1).getByLabel('Requirement name')).toHaveValue('Breakout rooms')
  await expect(requirement(page, 2)).toHaveCount(0)

  // "No venue requirements" clears every requirement, and stays that way once saved.
  await page.getByRole('checkbox', { name: 'No venue requirements' }).check()
  await expect(requirement(page, 1)).toHaveCount(0)
  await saveDraft(page)
  await page.reload()
  await expect(page.getByRole('checkbox', { name: 'No venue requirements' })).toBeChecked()
  await expect(requirement(page, 1)).toHaveCount(0)
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
  const coordinator = await assignedCoordinator(page)
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

  await page.getByRole('button', { name: 'Add a venue requirement' }).click()
  await expect(requirement(page, 1).getByLabel('Number of people')).toHaveValue('75')

  // Only the first: a second room is rarely the whole audience, so it is left for the organiser.
  await page.getByRole('button', { name: 'Add a venue requirement' }).click()
  await expect(requirement(page, 2).getByLabel('Number of people')).toHaveValue('')
})

test('2.7 AC8: an incomplete requirement is pointed out before submitting', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page, uniqueName('Incomplete room'))
  const needed = page.getByText(/To submit, still needed:/)

  await page.getByRole('button', { name: 'Add a venue requirement' }).click()
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
