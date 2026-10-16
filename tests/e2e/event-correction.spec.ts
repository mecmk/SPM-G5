/**
 * Story 7.2 - fe: the assigned Event Coordinator corrects an organiser's request until it is
 * confirmed, from the event details page, in the same form the organiser filled in (2.1).
 * AC4 the coordinator edits the organiser-provided details and saves them without the organiser's
 *     approval; the status stays where it was, including while a clarification is open. The cover
 *     picture is replaced with the organiser's own controls, a venue requirement is added with
 *     story 2.7's editor, and details cannot be saved while a field marked * is empty (checked
 *     before anything is sent).
 * AC5/AC6 were replaced by fix f7.2.4, which moves the lock from approval to confirmation:
 * AC10 an approved (Planning) event's details are still corrected, and the details page shows them,
 *     as an event awaiting its safety check still offers them. An approval that lands while the
 *     editor is open makes the save fail as stale, and a reload shows the details still editable.
 * AC12 once Confirmed, the organiser's details and cover picture are greyed out with a hint that
 *     further changes go through a change request; internal notes still save.
 * AC15 once approved, the form shows the equipment read-only, pointing to the Equipment
 *     requirements section, and a save leaves the equipment out of what it sends.
 * AC7 the form counts availability without the event's own holds, and marks equipment no longer
 *     available for new dates on its line, refusing the save.
 * AC8 nobody but the assigned coordinator is offered the edit.
 * AC9 a save made from a copy that changed meanwhile is refused, with a reload offered.
 * Which fields the API accepts, the 2.1 rules, every 403/409/422 refusal, which edits still fit a
 * booking or an equipment hold (f7.2.4 AC13-AC18), and the equipment holds themselves are covered
 * by backend/tests/events/test_correct_event_under_review.py. The organiser-vs-coordinator case of
 * AC9 needs story 4.3 (organisers editing a submitted request).
 *
 * Each test that saves raises its own request through the organiser's form, so parallel specs
 * never edit the same event. A submitted request waits until the Lead assigns it (5.4), so the
 * test has the Lead assign it before signing in as that coordinator.
 */
import { expect, test, type Browser, type Locator, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  EVENTS,
  assignByLead,
  createAndSubmitRequest,
  inFuture,
  signIn,
  uniqueName,
} from './support'

const DETAILS_PATH = /\/events\/[0-9a-f-]{36}$/
const EDIT_PATH = /\/events\/([0-9a-f-]{36})\/edit$/
const MY_EVENTS_PATH = /\/events\/mine$/
const LOCKED_HINT =
  'Event details can no longer be edited directly once the event is confirmed. Further changes must go through the change request process.'
const EQUIPMENT_HINT =
  'Once the event is approved, its equipment can no longer be changed here. While the event is in Planning, change it in the Equipment requirements section of the event page.'
// An organiser submits, then the auto-assigned coordinator signs in and edits: two full sign-in
// cycles take longer than the default per-test budget - the same reasoning as
// request-clarification.spec.ts and coordinator-reassignment.spec.ts.
const TWO_USER_TIMEOUT = 90_000
/** The smallest valid PNG: one transparent pixel. */
const PNG_BYTES = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64',
)

interface SubmittedRequest {
  id: string
  /** The seeded coordinator the Lead assigned it to (story 5.4, always Chloe). */
  coordinator: string
}

function equipmentItem(page: Page, position: number): Locator {
  return page.getByRole('group', { name: `Equipment item ${position}` })
}

/** Has the Lead assign the request (story 5.4), and returns the coordinator's account. */
async function coordinatorOf(page: Page, eventId: string): Promise<string> {
  await page.goto(`/events/${eventId}`)
  return (await assignByLead(page)).account
}

/** The organiser's submitted request, and the coordinator it went to. */
async function submittedRequest(page: Page, name: string): Promise<SubmittedRequest> {
  const id = await createAndSubmitRequest(page, name)
  return { id, coordinator: await coordinatorOf(page, id) }
}

/** AC7 only: a submitted request holding `laptops` presentation laptops on a chosen day. */
async function submittedRequestWithLaptops(
  page: Page,
  name: string,
  { days, laptops }: { days: number; laptops: number },
): Promise<SubmittedRequest> {
  await page.goto('/events/new')
  await page.getByLabel('Event name').fill(name)
  await page.getByLabel('Purpose').fill('Staff training')
  await page.getByLabel('Description').fill('One-day hands-on workshop.')
  await page.getByLabel('Proposed start').fill(inFuture(days, 9))
  await page.getByLabel('Proposed end').fill(inFuture(days, 17))
  await page.getByLabel('Expected attendance').fill('60')
  await page.getByLabel('Contact name').fill('Priya Nair')
  await page.getByLabel('Contact email').fill('priya.nair@example.com')
  await page.getByLabel('Contact phone number').fill('9123 4567')
  await page.getByRole('checkbox', { name: 'No venue requirements' }).check()
  await page.getByRole('checkbox', { name: 'No accessibility needs' }).check()
  await page.getByRole('button', { name: 'Add equipment' }).click()
  await equipmentItem(page, 1)
    .getByLabel('Equipment type')
    .selectOption({ label: 'Presentation laptop' })
  await equipmentItem(page, 1).getByLabel('Quantity').fill(String(laptops))
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)
  const id = page.url().match(EDIT_PATH)?.[1] ?? ''
  await page.getByRole('button', { name: 'Submit request' }).click()
  await expect(page).toHaveURL(MY_EVENTS_PATH)
  return { id, coordinator: await coordinatorOf(page, id) }
}

/** Someone else, signed in their own browser context. */
async function signedInAs(browser: Browser, page: Page, email: string): Promise<Page> {
  const context = await browser.newContext({
    baseURL: new URL(page.url()).origin,
  })
  const other = await context.newPage()
  await signIn(other, email)
  return other
}

async function openCorrection(page: Page, eventId: string, name: string) {
  await page.goto(`/events/${eventId}`)
  await page.getByRole('link', { name: 'Edit event' }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
}

/** The assigned coordinator approves the request (4.4) from its details page. */
async function approve(page: Page, eventId: string) {
  await page.goto(`/events/${eventId}`)
  await page.getByRole('button', { name: 'Approve' }).click()
  await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/approve') && response.ok()),
    page.getByRole('dialog').getByRole('button', { name: 'Approve' }).click(),
  ])
}

async function saveCorrection(page: Page) {
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes('/review-details') && response.request().method() === 'PATCH',
    ),
    page.getByRole('button', { name: 'Save changes' }).click(),
  ])
}

test('7.2 AC4: the assigned coordinator corrects a request under review and the details page shows it', async ({
  page,
  browser,
}) => {
  test.setTimeout(TWO_USER_TIMEOUT)
  const name = uniqueName('Correct')
  await signIn(page, ACCOUNTS.organiser)
  const request = await submittedRequest(page, name)
  const coordinator = await signedInAs(browser, page, request.coordinator)

  await openCorrection(coordinator, request.id, name)
  await coordinator.getByLabel('Description').fill('Corrected: a two-part hands-on workshop.')
  await coordinator.getByLabel('Expected attendance').fill('75')
  await coordinator
    .getByLabel('Choose cover picture')
    .setInputFiles({ name: 'cover.png', mimeType: 'image/png', buffer: PNG_BYTES })
  await expect(coordinator.getByRole('img', { name: 'Cover picture preview' })).toBeVisible()
  const pictureSaved = coordinator.waitForResponse(
    (response) =>
      response.url().includes('/review-details/cover-image') &&
      response.request().method() === 'PUT' &&
      response.ok(),
  )
  await saveCorrection(coordinator)
  await pictureSaved
  await expect(coordinator.getByRole('alert')).toHaveCount(0)
  await expect(coordinator.getByRole('img', { name: 'Cover picture preview' })).toHaveAttribute(
    'src',
    /\/uploads\/events\//,
  )

  await coordinator.getByRole('link', { name: /^← / }).click()
  await expect(coordinator).toHaveURL(DETAILS_PATH)
  await expect(coordinator.getByText('Corrected: a two-part hands-on workshop.')).toBeVisible()
  await expect(coordinator.getByText('75', { exact: true })).toBeVisible()
  await expect(coordinator.getByText('Under review', { exact: true })).toBeVisible()
})

test('7.2 AC4: the coordinator still corrects a request after asking the organiser a question', async ({
  page,
  browser,
}) => {
  test.setTimeout(TWO_USER_TIMEOUT)
  const name = uniqueName('Clarifying')
  await signIn(page, ACCOUNTS.organiser)
  const request = await submittedRequest(page, name)
  const coordinator = await signedInAs(browser, page, request.coordinator)
  await coordinator.goto(`/events/${request.id}`)
  await coordinator.getByLabel('Message').fill('Is it 60 or 80 people?')
  await coordinator.getByRole('button', { name: 'Send clarification request' }).click()
  const status = coordinator.getByRole('main').getByText('Clarification requested', { exact: true })
  await expect(status).toBeVisible()

  await openCorrection(coordinator, request.id, name)
  await coordinator.getByLabel('Expected attendance').fill('80')
  await saveCorrection(coordinator)
  await expect(coordinator.getByRole('alert')).toHaveCount(0)

  await coordinator.getByRole('link', { name: /^← / }).click()
  await expect(coordinator).toHaveURL(DETAILS_PATH)
  await expect(coordinator.getByText('80', { exact: true })).toBeVisible()
  await expect(status).toBeVisible()
})

test('7.2 AC4: the coordinator adds a venue requirement and the details page shows it', async ({
  page,
  browser,
}) => {
  test.setTimeout(TWO_USER_TIMEOUT)
  const name = uniqueName('Venue')
  await signIn(page, ACCOUNTS.organiser)
  const request = await submittedRequest(page, name)
  const coordinator = await signedInAs(browser, page, request.coordinator)

  await openCorrection(coordinator, request.id, name)
  await coordinator.getByRole('button', { name: 'Add a venue requirement' }).click()
  const added = coordinator.getByRole('group', { name: 'Venue requirement 1' })
  await added.getByLabel('Requirement name').fill('Main hall')
  await added.getByLabel('Number of people').fill('50')
  await saveCorrection(coordinator)
  await expect(coordinator.getByRole('alert')).toHaveCount(0)

  await coordinator.getByRole('link', { name: /^← / }).click()
  await expect(coordinator).toHaveURL(DETAILS_PATH)
  await expect(coordinator.getByText('Main hall')).toBeVisible()
})

test('7.2 AC7: the form leaves out the event’s own holds and marks equipment no longer free for new dates', async ({
  page,
  browser,
}) => {
  test.setTimeout(TWO_USER_TIMEOUT)
  const name = uniqueName('Equipment')
  // A day no other spec holds laptops on, and a different one each run, so a retry cannot collide.
  const busyDay = 600 + Math.floor(Math.random() * 100)
  await signIn(page, ACCOUNTS.organiser)
  const request = await submittedRequestWithLaptops(page, name, {
    days: busyDay - 40,
    laptops: 2,
  })
  // Another request takes 5 of the 6 laptops on the day the coordinator will move this one to.
  await submittedRequestWithLaptops(page, uniqueName('Busy day'), {
    days: busyDay,
    laptops: 5,
  })
  const coordinator = await signedInAs(browser, page, request.coordinator)

  await openCorrection(coordinator, request.id, name)
  const laptops = equipmentItem(coordinator, 1)
  // Its own 2 held laptops are not counted against it.
  await expect(laptops.getByText('6 available for these dates')).toBeVisible()

  await coordinator.getByLabel('Proposed start').fill(inFuture(busyDay, 9))
  await coordinator.getByLabel('Proposed end').fill(inFuture(busyDay, 17))

  await expect(laptops.getByText('1 available for these dates')).toBeVisible()
  await expect(
    laptops.getByText('Request no more than is available for these dates.'),
  ).toBeVisible()
  await expect(laptops.getByLabel('Quantity')).toHaveAttribute('aria-invalid', 'true')
  let correctionCalls = 0
  coordinator.on('request', (sent) => {
    if (sent.url().includes('/review-details')) correctionCalls += 1
  })
  await coordinator.getByRole('button', { name: 'Save changes' }).click()
  await expect(coordinator.getByRole('alert')).toContainText('no more than is available')
  expect(correctionCalls).toBe(0)
})

test('7.2 AC9: a save made from a copy that changed meanwhile is refused and a reload shows the latest', async ({
  page,
  browser,
}) => {
  test.setTimeout(TWO_USER_TIMEOUT)
  const name = uniqueName('Stale')
  await signIn(page, ACCOUNTS.organiser)
  const request = await submittedRequest(page, name)
  const first = await signedInAs(browser, page, request.coordinator)
  const second = await first.context().newPage()
  await openCorrection(first, request.id, name)
  await openCorrection(second, request.id, name)

  await first.getByLabel('Description').fill('Saved first.')
  await saveCorrection(first)
  await expect(first.getByRole('alert')).toHaveCount(0)

  await second.getByLabel('Description').fill('Saved second, from an old copy.')
  await saveCorrection(second)

  await expect(second.getByRole('alert')).toContainText('changed since you opened it')
  await second.getByRole('button', { name: 'Reload event' }).click()
  await expect(second.getByLabel('Description')).toHaveValue('Saved first.')
  await expect(second.getByRole('alert')).toHaveCount(0)
})

test('7.2 AC10: an approval that lands while the editor is open refuses the save as stale, and the details stay editable', async ({
  page,
  browser,
}) => {
  test.setTimeout(TWO_USER_TIMEOUT)
  const name = uniqueName('Race')
  await signIn(page, ACCOUNTS.organiser)
  const request = await submittedRequest(page, name)
  const editor = await signedInAs(browser, page, request.coordinator)
  const details = await editor.context().newPage()
  await openCorrection(editor, request.id, name)

  await approve(details, request.id)

  await editor.getByLabel('Description').fill('Too late.')
  await saveCorrection(editor)

  await expect(editor.getByRole('alert')).toContainText('changed since you opened it')
  await editor.getByRole('button', { name: 'Reload event' }).click()
  await expect(editor.getByText(LOCKED_HINT)).toHaveCount(0)
  await expect(editor.getByLabel('Description')).toBeEnabled()
})

test('7.2 AC10: the coordinator corrects an approved event and the details page shows it', async ({
  page,
  browser,
}) => {
  test.setTimeout(TWO_USER_TIMEOUT)
  const name = uniqueName('Planning fix')
  await signIn(page, ACCOUNTS.organiser)
  const request = await submittedRequest(page, name)
  const coordinator = await signedInAs(browser, page, request.coordinator)
  await approve(coordinator, request.id)

  await openCorrection(coordinator, request.id, name)
  await coordinator.getByLabel('Description').fill('Corrected while planning.')
  await saveCorrection(coordinator)
  await expect(coordinator.getByRole('alert')).toHaveCount(0)

  await coordinator.getByRole('link', { name: /^← / }).click()
  await expect(coordinator).toHaveURL(DETAILS_PATH)
  await expect(coordinator.getByText('Corrected while planning.')).toBeVisible()
  await expect(coordinator.getByText('Planning', { exact: true }).first()).toBeVisible()
})

test('7.2 AC10: an event awaiting its safety check still offers its details for correction', async ({
  page,
}) => {
  // Read only: the concert's coordinator opens the form and nothing is saved.
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto(`/events/${EVENTS.harbourConcert}`)
  await page.getByRole('link', { name: 'Edit event' }).click()

  await expect(page.getByText(LOCKED_HINT)).toHaveCount(0)
  await expect(page.getByLabel('Event name')).toBeEnabled()
  await expect(page.getByLabel('Description')).toBeEnabled()
})

test('7.2 AC15: once approved, the form shows the equipment read-only and points to its own section', async ({
  page,
}) => {
  // Read only: the roadshow's pending, accepted and declined items are shown, never changed.
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.equipmentRoadshow}`)
  await page.getByRole('link', { name: 'Edit event' }).click()

  await expect(page.getByText(EQUIPMENT_HINT)).toBeVisible()
  const firstItem = equipmentItem(page, 1)
  await expect(firstItem.getByLabel('Equipment type')).toBeDisabled()
  await expect(firstItem.getByLabel('Quantity')).toBeDisabled()
  await expect(firstItem.getByLabel('Technical notes')).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Remove', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add equipment' })).toHaveCount(0)
  await expect(page.getByLabel('Description')).toBeEnabled()
})

test('7.2 AC15: once approved, a correction leaves the equipment out of what it sends', async ({
  page,
  browser,
}) => {
  // Leaving the list out is what lets an event carrying a declined type requested again (15.1)
  // still be corrected: 2.1's one-line-per-type rule would refuse the list if it were sent.
  test.setTimeout(TWO_USER_TIMEOUT)
  const name = uniqueName('Approved kit')
  await signIn(page, ACCOUNTS.organiser)
  const request = await submittedRequestWithLaptops(page, name, {
    days: 500 + Math.floor(Math.random() * 50),
    laptops: 1,
  })
  const coordinator = await signedInAs(browser, page, request.coordinator)
  await approve(coordinator, request.id)
  await openCorrection(coordinator, request.id, name)
  await expect(equipmentItem(coordinator, 1).getByLabel('Quantity')).toBeDisabled()

  await coordinator.getByLabel('Description').fill('Corrected with the kit left alone.')
  const [sent] = await Promise.all([
    coordinator.waitForRequest(
      (sent) => sent.url().includes('/review-details') && sent.method() === 'PATCH',
    ),
    saveCorrection(coordinator),
  ])

  expect(sent.postDataJSON()).not.toHaveProperty('equipment')
  expect(sent.postDataJSON()).toHaveProperty('description')
  await expect(coordinator.getByRole('alert')).toHaveCount(0)
  await coordinator.getByRole('link', { name: /^← / }).click()
  await expect(coordinator.getByText('Corrected with the kit left alone.')).toBeVisible()
})

test('7.2 AC12: once confirmed, the details are greyed out, the hint says why, and notes still save', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.confirmed}`)
  await expect(page.getByText(LOCKED_HINT)).toBeVisible()

  await page.getByRole('link', { name: 'Edit event' }).click()
  await expect(page.getByText(LOCKED_HINT)).toBeVisible()
  await expect(page.getByLabel('Event name')).toBeDisabled()
  await expect(page.getByLabel('Description')).toBeDisabled()
  await expect(page.getByLabel('Choose cover picture')).toBeDisabled()
  const note = `E2E confirmed note ${Date.now()}`
  await page.getByLabel('Internal notes').fill(note)
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes('/routine-information') &&
        response.request().method() === 'PATCH' &&
        response.ok(),
    ),
    page.getByRole('button', { name: 'Save changes' }).click(),
  ])
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByLabel('Internal notes')).toHaveValue(note)
})

test('7.2 AC4: details cannot be saved while a field marked * is empty', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.submitted}`)
  await page.getByRole('link', { name: 'Edit event' }).click()
  await expect(page.getByLabel('Purpose')).toBeEnabled()
  let correctionCalls = 0
  page.on('request', (sent) => {
    if (sent.url().includes('/review-details')) correctionCalls += 1
  })

  await page.getByLabel('Purpose').fill('')

  await expect(page.getByText(/^Still needed: .*purpose/)).toBeVisible()
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('alert')).toContainText('Fill in every field marked *')
  expect(correctionCalls).toBe(0)
})

test('7.2 AC8: a coordinator not assigned to the request is not offered the edit', async ({
  page,
}) => {
  // The seeded request under review is assigned to coordinator 1.
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto(`/events/${EVENTS.submitted}`)

  await expect(
    page.getByRole('heading', { name: 'Data Literacy Workshop', level: 1 }),
  ).toBeVisible()
  await expect(page.getByRole('link', { name: 'Edit event' })).toHaveCount(0)
})

test('7.2 AC8: the organiser is not offered the coordinator’s edit on their own request', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.submitted}`)

  await expect(
    page.getByRole('heading', { name: 'Data Literacy Workshop', level: 1 }),
  ).toBeVisible()
  await expect(page.getByRole('link', { name: 'Edit event' })).toHaveCount(0)
})
