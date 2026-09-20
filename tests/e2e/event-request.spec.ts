/**
 * Story 2.1 - fe/be: capture event details, requirements and equipment on a request.
 * AC1 the organiser records the name, purpose, description, proposed date and time, attendance.
 * AC2 the end must be after the start and a past date is rejected (checked in the browser).
 * AC3 attendance, equipment and facility quantities take positive whole numbers (checked in the
 *     browser).
 * AC4 venue requirements (room layout, facilities with a quantity, other requirements) are
 *     recorded; "No venue requirements" differs from left empty and clears the other choices.
 * AC5 accessibility needs are selected or described; "none required" differs from left empty.
 * AC6 several equipment items are added, each with a type and quantity.
 * AC7 any detail, requirement or equipment item can be edited or removed before submission.
 * AC9-AC11 the organiser submits their own request, from the new-request page or from a saved
 *     draft; it then shows as submitted and read-only.
 * AC10 submitting with anything missing keeps the details as a draft and names what is missing.
 * Rule detail, refusals (401/403/404/409/422) and what the coordinator sees (AC8, AC12) are
 * backend cases: backend/tests/events/test_event_request_*.py.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, signIn } from './support'

const EDIT_PATH = /\/events\/[0-9a-f-]{36}\/edit$/
const PAST_START = '2020-01-01T09:00'

/** A `datetime-local` value (Singapore time) `days` from today, safely in the future. */
function inFuture(days: number, hour = 9): string {
  const day = new Date(Date.now() + days * 24 * 60 * 60 * 1000)
  const date = day.toISOString().slice(0, 10)
  return `${date}T${String(hour).padStart(2, '0')}:00`
}

function uniqueName(label: string): string {
  return `E2E ${label} ${Date.now()}-${Math.floor(Math.random() * 1e6)}`
}

function equipmentItem(page: Page, position: number): Locator {
  return page.getByRole('group', { name: `Equipment item ${position}` })
}

async function startNewRequest(page: Page) {
  await page.goto('/')
  await page.getByRole('link', { name: 'New event request' }).first().click()
  await expect(page.getByRole('heading', { name: 'New event request' })).toBeVisible()
}

async function fillEssentials(page: Page, name: string) {
  await page.getByLabel('Event name').fill(name)
  await page.getByLabel('Purpose').fill('Staff training')
  await page.getByLabel('Description').fill('One-day hands-on workshop.')
  await page.getByLabel('Proposed start').fill(inFuture(30, 9))
  await page.getByLabel('Proposed end').fill(inFuture(30, 17))
  await page.getByLabel('Expected attendance').fill('60')
}

async function addEquipment(page: Page, position: number, type: string, quantity: string) {
  await page.getByRole('button', { name: 'Add equipment' }).click()
  const item = equipmentItem(page, position)
  await item.getByLabel('Equipment type').selectOption({ label: type })
  await item.getByLabel('Quantity').fill(quantity)
}

/** Save an existing draft, waiting for the server to answer the edit. */
async function saveEdits(page: Page) {
  await Promise.all([
    page.waitForResponse(
      (response) => response.request().method() === 'PATCH' && response.url().includes('/events/'),
    ),
    page.getByRole('button', { name: 'Save draft' }).click(),
  ])
}

/** Answer the two sections a request cannot be submitted without: "none" is an answer. */
async function answerVenueAndAccessibility(page: Page) {
  await page.getByRole('checkbox', { name: 'No venue requirements' }).check()
  await page.getByRole('checkbox', { name: 'No accessibility needs' }).check()
}

/** Create a saved draft that is ready to submit and land on its edit page. */
async function createSubmittableDraft(page: Page, name: string) {
  await startNewRequest(page)
  await fillEssentials(page, name)
  await answerVenueAndAccessibility(page)
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)
}

test('2.1 AC1: an organiser records the event details and they are still there after a reload', async ({
  page,
}) => {
  const name = uniqueName('Details')
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)

  await fillEssentials(page, name)
  await page.getByRole('button', { name: 'Save draft' }).click()

  await expect(page).toHaveURL(EDIT_PATH)
  await page.reload()
  await expect(page.getByLabel('Event name')).toHaveValue(name)
  await expect(page.getByLabel('Purpose')).toHaveValue('Staff training')
  await expect(page.getByLabel('Description')).toHaveValue('One-day hands-on workshop.')
  await expect(page.getByLabel('Proposed start')).toHaveValue(inFuture(30, 9))
  await expect(page.getByLabel('Proposed end')).toHaveValue(inFuture(30, 17))
  await expect(page.getByLabel('Expected attendance')).toHaveValue('60')
  await expect(page.getByText('Draft', { exact: true })).toBeVisible()
})

test('2.1 AC2: an end before the start, or a past date, is refused before anything is sent', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  let createCalls = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/events')) createCalls += 1
  })
  await fillEssentials(page, uniqueName('Dates'))

  await page.getByLabel('Proposed end').fill(inFuture(30, 8))
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page.getByRole('alert')).toContainText('must be after the start')

  await page.getByLabel('Proposed start').fill(PAST_START)
  await page.getByLabel('Proposed end').fill('2020-01-01T17:00')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page.getByRole('alert')).toContainText('in the past')
  expect(createCalls).toBe(0)
})

test('2.1 AC3: attendance, facility and equipment quantities must be positive whole numbers', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  let createCalls = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/events')) createCalls += 1
  })
  await fillEssentials(page, uniqueName('Numbers'))

  for (const value of ['0', '-3', '1.5']) {
    await page.getByLabel('Expected attendance').fill(value)
    await page.getByRole('button', { name: 'Save draft' }).click()
    await expect(page.getByRole('alert')).toContainText('positive whole number')
  }

  await page.getByLabel('Expected attendance').fill('60')
  await page.getByRole('checkbox', { name: 'Breakout rooms', exact: true }).check()
  await page.getByLabel('Breakout rooms quantity').fill('0')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page.getByRole('alert')).toContainText('positive whole number')

  await page.getByLabel('Breakout rooms quantity').fill('3')
  await addEquipment(page, 1, 'Presentation laptop', '0')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page.getByRole('alert')).toContainText('positive whole number')
  expect(createCalls).toBe(0)
})

test('2.1 AC4: venue requirements are recorded with the request, facilities with a quantity', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('Venue'))

  await page.getByLabel('Room layout').selectOption({ label: 'Theatre' })
  await page.getByRole('checkbox', { name: 'Projector & screen', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Breakout rooms', exact: true }).check()
  await page.getByLabel('Breakout rooms quantity').fill('3')
  await page.getByLabel('Other venue requirements').fill('Close to the lifts')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)

  await page.reload()
  await expect(page.getByLabel('Room layout')).toHaveValue('THEATRE')
  await expect(
    page.getByRole('checkbox', { name: 'Projector & screen', exact: true }),
  ).toBeChecked()
  await expect(page.getByRole('checkbox', { name: 'Breakout rooms', exact: true })).toBeChecked()
  await expect(page.getByLabel('Breakout rooms quantity')).toHaveValue('3')
  await expect(page.getByLabel('Other venue requirements')).toHaveValue('Close to the lifts')
  await expect(page.getByLabel('Preferred location')).toHaveCount(0)
})

test('2.1 AC4: "No venue requirements" is kept apart from left empty and clears the other choices', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)

  // Left empty: the box is not ticked, and it stays that way.
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('Venue empty'))
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)
  await page.reload()
  await expect(page.getByRole('checkbox', { name: 'No venue requirements' })).not.toBeChecked()

  // Ticking it leaves the other venue fields blank; choosing anything again un-ticks it.
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('Venue none'))
  await page.getByLabel('Room layout').selectOption({ label: 'Theatre' })
  await page.getByRole('checkbox', { name: 'Wi-Fi', exact: true }).check()
  await page.getByLabel('Other venue requirements').fill('Near the lifts')
  await page.getByRole('checkbox', { name: 'No venue requirements' }).check()
  await expect(page.getByLabel('Room layout')).toHaveValue('')
  await expect(page.getByRole('checkbox', { name: 'Wi-Fi', exact: true })).not.toBeChecked()
  await expect(page.getByLabel('Other venue requirements')).toHaveValue('')

  await page.getByRole('checkbox', { name: 'Wi-Fi', exact: true }).check()
  await expect(page.getByRole('checkbox', { name: 'No venue requirements' })).not.toBeChecked()

  await page.getByRole('checkbox', { name: 'No venue requirements' }).check()
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)
  await page.reload()
  await expect(page.getByRole('checkbox', { name: 'No venue requirements' })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: 'Wi-Fi', exact: true })).not.toBeChecked()
})

test('2.1 AC5: selected accessibility needs, "none required" and left empty are kept apart', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)

  // Left empty: neither the box nor any need is ticked, and it stays that way.
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('A11y empty'))
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)
  await page.reload()
  await expect(page.getByRole('checkbox', { name: 'No accessibility needs' })).not.toBeChecked()
  await expect(page.getByRole('checkbox', { name: 'Wheelchair access' })).not.toBeChecked()

  // "None required" is a positive statement, remembered as such.
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('A11y none'))
  await page.getByRole('checkbox', { name: 'No accessibility needs' }).check()
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)
  await page.reload()
  await expect(page.getByRole('checkbox', { name: 'No accessibility needs' })).toBeChecked()

  // Needs can be selected and described.
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('A11y needs'))
  await page.getByRole('checkbox', { name: 'Wheelchair access' }).check()
  await page.getByRole('checkbox', { name: 'Hearing loop' }).check()
  await page.getByLabel('Accessibility notes').fill('Guide dog attending')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)
  await page.reload()
  await expect(page.getByRole('checkbox', { name: 'Wheelchair access' })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: 'Hearing loop' })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: 'No accessibility needs' })).not.toBeChecked()
  await expect(page.getByLabel('Accessibility notes')).toHaveValue('Guide dog attending')
})

test('2.1 AC6: several equipment items are added, each with a type and a quantity', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('Equipment'))

  await addEquipment(page, 1, 'Wireless microphone', '6')
  await addEquipment(page, 2, 'Presentation laptop', '2')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)

  await page.reload()
  await expect(equipmentItem(page, 1).getByLabel('Equipment type')).toHaveValue('WIRELESS_MIC')
  await expect(equipmentItem(page, 1).getByLabel('Quantity')).toHaveValue('6')
  await expect(equipmentItem(page, 2).getByLabel('Equipment type')).toHaveValue('LAPTOP')
  await expect(equipmentItem(page, 2).getByLabel('Quantity')).toHaveValue('2')
})

test('2.1 AC7: a detail can be edited and an equipment item edited or removed before submitting', async ({
  page,
}) => {
  const name = uniqueName('Edit')
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await fillEssentials(page, name)
  await addEquipment(page, 1, 'Wireless microphone', '6')
  await addEquipment(page, 2, 'Presentation laptop', '2')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)

  await page.getByLabel('Event name').fill(`${name} renamed`)
  await equipmentItem(page, 1).getByLabel('Quantity').fill('8')
  await equipmentItem(page, 2).getByRole('button', { name: 'Remove' }).click()
  await saveEdits(page)

  await page.reload()
  await expect(page.getByLabel('Event name')).toHaveValue(`${name} renamed`)
  await expect(equipmentItem(page, 1).getByLabel('Quantity')).toHaveValue('8')
  await expect(equipmentItem(page, 2)).toHaveCount(0)
})

test('2.1 AC9/AC11: an organiser submits their draft and it becomes a read-only submitted request', async ({
  page,
}) => {
  const name = uniqueName('Submit')
  await signIn(page, ACCOUNTS.organiser)
  await createSubmittableDraft(page, name)

  await page.getByRole('button', { name: 'Submit request' }).click()

  await expect(page.getByText('Submitted', { exact: true })).toBeVisible()
  await expect(page.getByText(/Submitted on /)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Submit request' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Save draft' })).toHaveCount(0)
  await expect(page.getByLabel('Event name')).toBeDisabled()

  await page.reload()
  await expect(page.getByText('Submitted', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Event name')).toHaveValue(name)
})

test('2.1 AC9/AC11: an organiser can submit straight from the new request page', async ({
  page,
}) => {
  const name = uniqueName('Direct')
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await fillEssentials(page, name)
  await answerVenueAndAccessibility(page)

  await page.getByRole('button', { name: 'Submit request' }).click()

  await expect(page).toHaveURL(EDIT_PATH)
  await expect(page.getByText('Submitted', { exact: true })).toBeVisible()
  await expect(page.getByText(/Submitted on /)).toBeVisible()
  await expect(page.getByLabel('Event name')).toHaveValue(name)
  await expect(page.getByLabel('Event name')).toBeDisabled()
})

test('2.1 AC10: submitting with anything missing keeps the details and names what is missing', async ({
  page,
}) => {
  const name = uniqueName('Missing')
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await fillEssentials(page, name)
  await page.getByLabel('Purpose').fill('')
  await page.getByLabel('Description').fill('')

  await page.getByRole('button', { name: 'Submit request' }).click()

  // The details were recorded as a draft, and the message says what to add.
  await expect(page).toHaveURL(EDIT_PATH)
  await expect(page.getByLabel('Event name')).toHaveValue(name)
  await expect(page.getByText('Draft', { exact: true })).toBeVisible()
  const alert = page.getByRole('alert')
  await expect(alert).toContainText('purpose')
  await expect(alert).toContainText('description')
  await expect(alert).toContainText('venue requirements')
  await expect(alert).toContainText('accessibility needs')
})

test('2.1 AC9: only an organiser can raise a request', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'New event request' })).toHaveCount(0)

  await page.goto('/events/new')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
})
