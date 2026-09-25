/**
 * Story 2.1 - fe/be: capture event details, requirements and equipment on a request.
 * AC1 the organiser records the name, purpose, description, proposed date and time, attendance.
 * AC2 the end must be after the start and a past date is rejected (checked in the browser,
 *     and the date pickers do not offer the past); an event starts at most 2 years ahead and
 *     runs at most 14 days, and a half-typed date is refused rather than read as empty. Each
 *     date problem is said under the dates as soon as it is typed, not only on save.
 * AC3 attendance, equipment and facility quantities take positive whole numbers (checked in the
 *     browser, said next to the field as it is typed, and the field to fix is marked and focused
 *     on a save).
 * AC4 venue requirements (room layout, facilities with a quantity, other requirements) are
 *     recorded; "No venue requirements" differs from left empty and clears the other choices.
 * AC5 accessibility needs are selected or described; "none required" differs from left empty.
 * AC6 several equipment items are added, each with a type and quantity; a type can be on the
 *     request only once, so the form stops offering one that is taken. The form says how many of
 *     an item are available for the chosen dates and stops a request for more.
 * AC11 a submission refused because the stock went in the meantime stays a draft, and the form
 *     shows the new count. (That equipment is held on submit is a backend rule.)
 * AC7 any detail, requirement or equipment item can be edited or removed before submission.
 * AC9-AC11 the organiser submits their own request, from the new-request page or from a saved
 *     draft; it then shows as submitted and read-only.
 * AC10 submitting with anything missing keeps the details as a draft (the backend names what is
 *     missing);
 *     the form
 *     also lists what is still needed as it is filled in, so it is no surprise at submit.
 * Rule detail, refusals (401/403/404/409/422) and what the coordinator sees (AC8, AC12) are
 * backend cases: backend/tests/events/test_event_request_*.py.
 */
import { expect, test, type Browser, type Locator, type Page } from '@playwright/test'
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

/** Open the form directly: one page load, so a test does not spend its time on the home page. */
async function startNewRequest(page: Page) {
  await page.goto('/events/new')
  await expect(page.getByRole('heading', { name: 'New event request' })).toBeVisible()
}

/** Reach the form the way a person does, through the menu. One test uses this. */
async function startNewRequestFromMenu(page: Page) {
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
  await startNewRequestFromMenu(page)

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

  await expect(page.getByText('Under review', { exact: true })).toBeVisible()
  await expect(page.getByText(/Submitted on /)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Submit request' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Save draft' })).toHaveCount(0)
  await expect(page.getByLabel('Event name')).toBeDisabled()

  await page.reload()
  await expect(page.getByText('Under review', { exact: true })).toBeVisible()
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
  await expect(page.getByText('Under review', { exact: true })).toBeVisible()
  await expect(page.getByText(/Submitted on /)).toBeVisible()
  await expect(page.getByLabel('Event name')).toHaveValue(name)
  await expect(page.getByLabel('Event name')).toBeDisabled()
})

test('2.1 AC10: submitting with anything missing keeps the details as a draft and shows the reason', async ({
  page,
}) => {
  const name = uniqueName('Missing')
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await fillEssentials(page, name)
  await page.getByLabel('Purpose').fill('')
  await page.getByLabel('Description').fill('')

  await page.getByRole('button', { name: 'Submit request' }).click()

  // The details were recorded as a draft and the refusal is shown. What is named as missing is a
  // backend rule (test_event_request_submission.py).
  await expect(page).toHaveURL(EDIT_PATH)
  await expect(page.getByLabel('Event name')).toHaveValue(name)
  await expect(page.getByText('Draft', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toBeVisible()
})

test('2.1 AC9: only an organiser can raise a request', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'New event request' })).toHaveCount(0)

  await page.goto('/events/new')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
})

test('2.1 AC6: an equipment type already on the request cannot be picked again', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await addEquipment(page, 1, 'Portable speaker set', '1')

  await page.getByRole('button', { name: 'Add equipment' }).click()

  // Playwright's toBeDisabled() does not see a disabled <option>, so the attribute is checked.
  const second = equipmentItem(page, 2)
  await expect(second.getByRole('option', { name: /Portable speaker set/ })).toHaveAttribute(
    'disabled',
    '',
  )
  await expect(second.getByRole('option', { name: /Portable speaker set/ })).toHaveText(
    /already added/,
  )
  await expect(second.getByRole('option', { name: /Wireless microphone/ })).not.toHaveAttribute(
    'disabled',
    '',
  )
  // The first row still offers, and keeps, its own choice.
  await expect(equipmentItem(page, 1).getByLabel('Equipment type')).toHaveValue('SPEAKER_SET')
  await expect(
    equipmentItem(page, 1).getByRole('option', { name: /Portable speaker set/ }),
  ).not.toHaveAttribute('disabled', '')
})

test('2.1 AC6: once every equipment type is on the request there is nothing left to add', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('All equipment'))
  const addButton = page.getByRole('button', { name: 'Add equipment' })

  let rows = 0
  while (await addButton.isEnabled()) {
    rows += 1
    expect(rows).toBeLessThan(25)
    await addButton.click()
    const select = equipmentItem(page, rows).getByLabel('Equipment type')
    const firstFree = await select.locator('option:not([disabled])').nth(1).getAttribute('value')
    await select.selectOption(firstFree!)
  }

  expect(rows).toBeGreaterThan(1)
  await expect(addButton).toBeDisabled()
  await expect(page.getByText('Every equipment type is already on this request.')).toBeVisible()
  // With every type in use exactly once, the request still saves.
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)
})

test('2.1 AC6: an equipment item left without a type is refused and pointed at', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('No type'))
  await addEquipment(page, 1, 'Presentation laptop', '2')
  await page.getByRole('button', { name: 'Add equipment' }).click()

  await page.getByRole('button', { name: 'Save draft' }).click()

  await expect(page.getByRole('alert')).toContainText('Choose a type')
  const blank = equipmentItem(page, 2).getByLabel('Equipment type')
  await expect(blank).toBeFocused()
  await expect(blank).toHaveAttribute('aria-invalid', 'true')
  await expect(equipmentItem(page, 1).getByLabel('Equipment type')).not.toHaveAttribute(
    'aria-invalid',
    'true',
  )
})

test('2.1 AC3: the field that needs fixing is marked and focused', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('Focus'))

  const attendance = page.getByLabel('Expected attendance')
  await attendance.fill('0')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(attendance).toBeFocused()
  await expect(attendance).toHaveAttribute('aria-invalid', 'true')
  await attendance.fill('60')
  await expect(attendance).not.toHaveAttribute('aria-invalid', 'true')

  await page.getByRole('checkbox', { name: 'Breakout rooms', exact: true }).check()
  const rooms = page.getByLabel('Breakout rooms quantity')
  await rooms.fill('0')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(rooms).toBeFocused()
  await expect(rooms).toHaveAttribute('aria-invalid', 'true')
  await rooms.fill('3')

  await addEquipment(page, 1, 'Presentation laptop', '1')
  await addEquipment(page, 2, 'Wireless microphone', '0')
  await page.getByRole('button', { name: 'Save draft' }).click()
  const badQuantity = equipmentItem(page, 2).getByLabel('Quantity')
  await expect(badQuantity).toBeFocused()
  await expect(badQuantity).toHaveAttribute('aria-invalid', 'true')
  await expect(equipmentItem(page, 1).getByLabel('Quantity')).not.toHaveAttribute(
    'aria-invalid',
    'true',
  )
})

test('2.1 AC2: the date pickers do not offer dates in the past', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  const start = page.getByLabel('Proposed start')
  const end = page.getByLabel('Proposed end')

  // Both pickers start at "now" (Singapore time).
  const FIVE_MINUTES = 5 * 60 * 1000
  const startMin = await start.getAttribute('min')
  expect(startMin).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
  expect(Math.abs(new Date(`${startMin}:00+08:00`).getTime() - Date.now())).toBeLessThan(
    FIVE_MINUTES,
  )

  // Once a start is chosen, the end cannot be offered before it.
  await start.fill(inFuture(30, 9))
  await expect(end).toHaveAttribute('min', inFuture(30, 9))
})

test('2.1 AC2: an event cannot run for more than 14 days', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  let createCalls = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/events')) createCalls += 1
  })
  await fillEssentials(page, uniqueName('Long'))
  const end = page.getByLabel('Proposed end')

  // The end picker stops offering dates 14 days after the start.
  await expect(end).toHaveAttribute('max', inFuture(44, 9))

  await end.fill(inFuture(45, 9))
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page.getByRole('alert')).toContainText('14 days')
  await expect(end).toBeFocused()
  await expect(end).toHaveAttribute('aria-invalid', 'true')
  expect(createCalls).toBe(0)

  // Exactly 14 days is allowed.
  await end.fill(inFuture(44, 9))
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)
})

test('2.1 AC2: a year-0001 date and a half-typed date are refused, not read as empty', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('Odd dates'))
  const start = page.getByLabel('Proposed start')
  const end = page.getByLabel('Proposed end')

  await start.fill('0001-01-01T01:13')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page.getByRole('alert')).toContainText('in the past')
  await expect(start).toBeFocused()

  // Clear just the AM/PM part of a complete end date: the field is now half-typed.
  await start.fill(inFuture(30, 9))
  await end.fill(inFuture(30, 17))
  await end.focus()
  for (let segment = 0; segment < 5; segment += 1) await page.keyboard.press('Tab')
  await page.keyboard.press('Backspace')
  await expect(
    page.getByText('Finish entering the date and time, including AM or PM.'),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Save draft' }).click()

  await expect(page.getByRole('alert')).toContainText('Finish entering')
  await expect(end).toBeFocused()
  await expect(end).toHaveAttribute('aria-invalid', 'true')
})

test('2.1 AC2: a start more than 2 years ahead is refused before anything is sent', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  let createCalls = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/events')) createCalls += 1
  })
  await fillEssentials(page, uniqueName('Far ahead'))
  const start = page.getByLabel('Proposed start')

  // The start picker stops offering dates 2 calendar years from now (Singapore time), which is
  // 730 or 731 days depending on whether a 29 February falls in between.
  const twoYearsFromNow = new Date()
  twoYearsFromNow.setUTCFullYear(twoYearsFromNow.getUTCFullYear() + 2)
  const FIVE_MINUTES = 5 * 60 * 1000
  const startMax = await start.getAttribute('max')
  expect(startMax).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
  expect(
    Math.abs(new Date(`${startMax}:00+08:00`).getTime() - twoYearsFromNow.getTime()),
  ).toBeLessThan(FIVE_MINUTES)

  for (const year of ['2099', '9999']) {
    await start.fill(`${year}-06-15T09:00`)
    await page.getByLabel('Proposed end').fill(`${year}-06-15T17:00`)
    await page.getByRole('button', { name: 'Save draft' }).click()
    await expect(page.getByRole('alert')).toContainText('2 years')
    await expect(start).toBeFocused()
    await expect(start).toHaveAttribute('aria-invalid', 'true')
  }
  expect(createCalls).toBe(0)
})

test('2.1 AC2: a date problem is said under the dates as soon as it is typed', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  const start = page.getByLabel('Proposed start')
  const end = page.getByLabel('Proposed end')

  // Both dates in the past: said straight away, with no save needed.
  await start.fill('2022-03-31T01:13')
  await end.fill('2022-12-12T14:22')
  await expect(page.getByText('The proposed date and time cannot be in the past.')).toBeVisible()
  await expect(start).toHaveAttribute('aria-invalid', 'true')

  // An end before the start is said first: 12 Dec 2022 to 31 Mar 2022.
  await start.fill('2022-12-12T14:22')
  await end.fill('2022-03-31T01:13')
  await expect(
    page.getByText('The proposed end date and time must be after the start date and time.'),
  ).toBeVisible()
  await expect(end).toHaveAttribute('aria-invalid', 'true')

  // Each other problem is named as it happens.
  await start.fill(inFuture(30, 9))
  await end.fill(inFuture(30, 8))
  await expect(
    page.getByText('The proposed end date and time must be after the start date and time.'),
  ).toBeVisible()
  await expect(end).toHaveAttribute('aria-invalid', 'true')

  await end.fill(inFuture(45, 9))
  await expect(page.getByText('An event cannot run for more than 14 days.')).toBeVisible()

  await start.fill('2099-06-15T09:00')
  await end.fill('2099-06-15T17:00')
  await expect(
    page.getByText('The proposed start cannot be more than 2 years from now.'),
  ).toBeVisible()
  await expect(start).toHaveAttribute('aria-invalid', 'true')

  // And it goes away once the dates are right.
  await start.fill(inFuture(30, 9))
  await end.fill(inFuture(30, 17))
  await expect(
    page.getByText(
      /cannot be in the past|must be after the start date|cannot run for more than|cannot be more than 2 years/,
    ),
  ).toHaveCount(0)
  await expect(start).not.toHaveAttribute('aria-invalid', 'true')
  await expect(end).not.toHaveAttribute('aria-invalid', 'true')
})

/** Set both dates to a day `days` from today. Each availability test uses its own far-off day. */
async function setDates(page: Page, days: number) {
  await page.getByLabel('Proposed start').fill(inFuture(days, 9))
  await page.getByLabel('Proposed end').fill(inFuture(days, 17))
}

/** A second signed-in organiser in their own browser context. */
async function secondOrganiser(browser: Browser, page: Page): Promise<Page> {
  const context = await browser.newContext({ baseURL: new URL(page.url()).origin })
  const other = await context.newPage()
  await signIn(other, ACCOUNTS.organiser2)
  return other
}

test('2.1 AC6: the form says how many of an item are available for the chosen dates', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await addEquipment(page, 1, 'Presentation laptop', '1')
  const item = equipmentItem(page, 1)

  await expect(
    item.getByText('Choose the start and end to see how many are available.'),
  ).toBeVisible()

  await setDates(page, 300)

  await expect(item.getByText('6 available for these dates')).toBeVisible()
})

test('2.1 AC6: asking for more than is available is stopped and pointed at', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  let createCalls = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/events')) createCalls += 1
  })
  await fillEssentials(page, uniqueName('Too many'))
  await setDates(page, 320)
  await addEquipment(page, 1, 'Presentation laptop', '7')
  const quantity = equipmentItem(page, 1).getByLabel('Quantity')

  // Said as soon as it is typed, then again if a save is tried.
  await expect(
    equipmentItem(page, 1).getByText('Request no more than is available for these dates.'),
  ).toBeVisible()
  await expect(quantity).toHaveAttribute('aria-invalid', 'true')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page.getByRole('alert')).toContainText('no more than is available')
  await expect(quantity).toBeFocused()
  expect(createCalls).toBe(0)

  // All 6 is fine.
  await quantity.fill('6')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)
})

test('2.1 AC11: a refused submission stays a draft and the form shows the new count', async ({
  page,
  browser,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('Late'))
  await setDates(page, 360)
  await answerVenueAndAccessibility(page)
  await addEquipment(page, 1, 'Presentation laptop', '6')
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)

  // Someone else submits first and takes 4 of the 6.
  const other = await secondOrganiser(browser, page)
  await startNewRequest(other)
  await fillEssentials(other, uniqueName('First'))
  await setDates(other, 360)
  await answerVenueAndAccessibility(other)
  await addEquipment(other, 1, 'Presentation laptop', '4')
  await other.getByRole('button', { name: 'Submit request' }).click()
  await expect(other.getByText(/Submitted on /)).toBeVisible()
  await other.context().close()

  await page.getByRole('button', { name: 'Submit request' }).click()

  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByText('Draft', { exact: true })).toBeVisible()
  await expect(equipmentItem(page, 1).getByText('2 available for these dates')).toBeVisible()
})

test('2.1 AC3: a bad number is said next to the field as soon as it is typed', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  await fillEssentials(page, uniqueName('Live numbers'))

  // Attendance
  await page.getByLabel('Expected attendance').fill('0')
  await expect(page.getByText('Expected attendance must be a positive whole number.')).toBeVisible()
  await expect(page.getByLabel('Expected attendance')).toHaveAttribute('aria-invalid', 'true')
  await page.getByLabel('Expected attendance').fill('60')
  await expect(page.getByText('Expected attendance must be a positive whole number.')).toHaveCount(
    0,
  )

  // A facility quantity
  await page.getByRole('checkbox', { name: 'Breakout rooms', exact: true }).check()
  await page.getByLabel('Breakout rooms quantity').fill('-2')
  await expect(
    page.getByText('A facility quantity must be a positive whole number, or left empty.'),
  ).toBeVisible()
  await page.getByLabel('Breakout rooms quantity').fill('3')
  await expect(
    page.getByText('A facility quantity must be a positive whole number, or left empty.'),
  ).toHaveCount(0)

  // An equipment quantity, on the row it belongs to
  await addEquipment(page, 1, 'Presentation laptop', '1')
  await addEquipment(page, 2, 'Wireless microphone', '1.5')
  await expect(
    equipmentItem(page, 2).getByText('Equipment quantity must be a positive whole number.'),
  ).toBeVisible()
  await expect(
    equipmentItem(page, 1).getByText('Equipment quantity must be a positive whole number.'),
  ).toHaveCount(0)
  await equipmentItem(page, 2).getByLabel('Quantity').fill('2')
  await expect(page.getByText('Equipment quantity must be a positive whole number.')).toHaveCount(0)
})

test('2.1 AC1: an empty event name is said as soon as you move off the field', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  const name = page.getByLabel('Event name')

  await name.focus()
  await expect(page.getByText('Enter a name for the event.')).toHaveCount(0) // not yet: untouched
  await page.keyboard.press('Tab')

  await expect(page.getByText('Enter a name for the event.')).toBeVisible()
  await expect(name).toHaveAttribute('aria-invalid', 'true')
  await name.fill('Now it has a name')
  await expect(page.getByText('Enter a name for the event.')).toHaveCount(0)
})

test('2.1 AC10: what is still needed to submit is listed as you fill the form in', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  const needed = page.getByText(/To submit, still needed:/)

  await expect(needed).toContainText('purpose')
  await expect(needed).toContainText('description')
  await expect(needed).toContainText('proposed start date and time')
  await expect(needed).toContainText('proposed end date and time')
  await expect(needed).toContainText('expected attendance')
  await expect(needed).toContainText('venue requirements')
  await expect(needed).toContainText('accessibility needs')

  await page.getByLabel('Purpose').fill('Staff training')
  await expect(needed).not.toContainText('purpose')
  await expect(needed).toContainText('description')

  await fillEssentials(page, uniqueName('Checklist'))
  await expect(needed).not.toContainText('expected attendance')
  await expect(needed).toContainText('venue requirements')

  await page.getByRole('checkbox', { name: 'No venue requirements' }).check()
  await expect(needed).not.toContainText('venue requirements')
  await page.getByRole('checkbox', { name: 'No accessibility needs' }).check()

  await expect(needed).toHaveCount(0)
})

test('2.1 AC2: a date that does not exist, like 29 February in a non-leap year, is explained', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await startNewRequest(page)
  const start = page.getByLabel('Proposed start')

  // Type 02/29/2027 11:11 AM segment by segment: every part is filled in, but 2027 is not a leap
  // year, so the browser holds no date at all.
  await start.focus()
  for (const [segment, text] of [
    [0, '02'],
    [1, '29'],
    [2, '2027'],
    [3, '11'],
    [4, '11'],
    [5, 'A'],
  ] as const) {
    if (segment > 0) await page.keyboard.press('Tab')
    await page.keyboard.type(text)
  }

  await expect(page.getByText(/29 February is only valid in a leap year/)).toBeVisible()
  await expect(page.getByText(/no 31st in April, June, September or November/)).toBeVisible()
  await expect(start).toHaveAttribute('aria-invalid', 'true')
})
