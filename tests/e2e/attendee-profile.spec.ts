import { expect, test, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

/**
 * Story 18.4 - autofill attendee profile details. END-TO-END tests: what an attendee and an
 * organiser click through, at a phone's width (375x667) and a desktop's (1280x800).
 *
 * Level: e2e. The rules behind what these pages show - the phone and dietary limits, who may read
 * or change a profile, which list rows show details, two saves in a row - are proven in
 * backend/tests/registrations/test_attendee_profile_*.py and backend/tests/common/, not repeated
 * here. The exceptions are AC6/AC7's checks in the browser, which block a save before any request
 * is sent, so no backend test can see them, and AC9 as the page shows it: the server's rule is a
 * backend case, while leaving a withdrawn row's details empty, not "None", is the page's.
 *
 * AC1 An attendee has a My profile page that shows their name and email, which they cannot
 *     change, and the details they keep up to date: a contact phone number and their dietary
 *     requirements.
 * AC2 The first time an attendee registers for an event, they are asked for these details before
 *     the registration is confirmed. The details are saved to their profile, so later
 *     registrations do not ask again.
 * AC3 These details are remembered and filled in for later registrations. Changing them on
 *     Upcoming events, where the attendee registers, updates the profile (PO decision, 24 Oct
 *     2026: later registrations stay one click).
 * AC4 A change on My profile shows wherever the details are shown, including on events registered
 *     for earlier.
 * AC5 The organiser sees each registered attendee's phone number and dietary requirements on the
 *     registration list (18.3): a table on a desktop, one card per attendee on a phone.
 * AC6 Dietary requirements are free text of up to 500 characters; none recorded shows "None".
 * AC7 The phone number, when given, has 8 to 15 digits (2.1 AC13).
 * AC9 A withdrawn registration shows none of the attendee's details on the list.
 *
 * Each flow that changes an attendee's details has a seeded attendee of its own (Cara, Dion,
 * Esme: backend/db/seed/020_sample_data.sql, story 18.4's block), since specs run in parallel and a
 * first registration happens once. Aiden's profile and the food tasting walk's list are only read.
 */

const PROFILE_PATH = '/profile'
const UPCOMING_EVENTS_PATH = '/browse'
const PHONE = { width: 375, height: 667 }
const DESKTOP = { width: 1280, height: 800 }
/** The smallest height a control on a phone may have, to be pressed with a thumb. */
const THUMB_TARGET = 44
const DETAILS_DIALOG = 'Your details'
const DETAILS_REGION = 'Your details'
const PHONE_INVALID_MESSAGE = 'Enter a phone number with 8 to 15 digits.'
const DIETARY_MAX_LENGTH = 500

// What the seed holds for each attendee (story 18.4's block of 020_sample_data.sql).
const AIDEN = { name: 'Aiden Attendee', phone: '+65 9700 0007' } // no dietary requirements
const BELLA = {
  name: 'Bella Attendee',
  phone: '+65 9700 0011',
  dietary:
    'Vegetarian. No eggs, no mushrooms, and nothing cooked with fish sauce or oyster sauce, please' +
    ' - a severe shellfish allergy, so food prepared alongside shellfish is not safe either.',
}
const DION = { phone: '+65 9184 0202', dietary: 'No pork' }
const ESME = { name: 'Esme Attendee' }

const POTTERY_TASTER = 'Riverside Pottery Taster' // Cara's first registration
const WATERCOLOUR_CLASS = 'Evening Watercolour Class' // Cara's second, in one click
const BOOK_CLUB = 'Community Book Club' // Dion's, after changing his details

/** An event's card on Upcoming events, found by its name (as in attendee-registration.spec.ts). */
function eventCard(page: Page, name: string) {
  return page.getByRole('listitem').filter({ has: page.getByRole('heading', { level: 3, name }) })
}

function registerButton(page: Page, name: string) {
  return eventCard(page, name).getByRole('button', { name: `Register for ${name}` })
}

function registeredBadge(page: Page, name: string) {
  return eventCard(page, name).getByText('Registered', { exact: true })
}

function registrations(page: Page) {
  return page.getByRole('region', { name: 'Registered attendees', exact: true })
}

function reportPath(eventId: string): string {
  return `/registrations/report?event=${eventId}`
}

async function hasNoSidewaysScroll(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )
}

/** The element sits wholly inside the viewport. */
async function expectInsideScreen(page: Page, element: Locator) {
  const box = (await element.boundingBox())!
  const { width, height } = page.viewportSize()!
  expect(box.x).toBeGreaterThanOrEqual(0)
  expect(box.y).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(width)
  expect(box.y + box.height).toBeLessThanOrEqual(height)
}

/** On a phone a field spans the form: here, most of the screen's width. */
async function expectFullWidth(page: Page, field: Locator) {
  const box = (await field.boundingBox())!
  expect(box.width).toBeGreaterThanOrEqual(page.viewportSize()!.width * 0.75)
}

async function expectThumbSized(control: Locator) {
  const box = (await control.boundingBox())!
  expect(box.height).toBeGreaterThanOrEqual(THUMB_TARGET)
}

/** The phone field brings up the phone keypad. */
async function expectPhoneKeypad(field: Locator) {
  await expect(field).toHaveAttribute('type', 'tel')
  await expect(field).toHaveAttribute('inputmode', 'tel')
}

test('18.4 AC1: My profile shows the name and email as fixed text and the details in a form, on a desktop and a phone', async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP)
  await signIn(page, ACCOUNTS.attendee)
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'My profile', exact: true })
    .click()

  await expect(page.getByRole('heading', { level: 1, name: 'My profile' })).toBeVisible()
  const main = page.getByRole('main')
  await expect(main.getByText(AIDEN.name, { exact: true })).toBeVisible()
  await expect(main.getByText(ACCOUNTS.attendee, { exact: true })).toBeVisible()
  // Shown, never offered to change (AC1): no field holds the name or the email.
  await expect(main.getByRole('textbox', { name: /name|email/i })).toHaveCount(0)
  const phone = main.getByLabel('Phone number')
  await expect(phone).toHaveValue(AIDEN.phone)
  await expectPhoneKeypad(phone)
  await expect(main.getByLabel('Dietary requirements')).toHaveValue('')
  expect(await hasNoSidewaysScroll(page)).toBe(true)

  await page.setViewportSize(PHONE)
  await expectFullWidth(page, phone)
  await expectFullWidth(page, main.getByLabel('Dietary requirements'))
  const save = main.getByRole('button', { name: 'Save details' })
  await save.scrollIntoViewIfNeeded()
  await expectThumbSized(save)
  await expectInsideScreen(page, save)
  expect(await hasNoSidewaysScroll(page)).toBe(true)
})

test('18.4 AC2/AC3: the first registration asks for the details, and the next registers in one click with them filled in', async ({
  page,
}) => {
  await page.setViewportSize(PHONE)
  await signIn(page, ACCOUNTS.attendee3)
  await page.goto(UPCOMING_EVENTS_PATH)

  await registerButton(page, POTTERY_TASTER).click()

  // AC2: the details are asked for first; nothing is registered yet.
  const dialog = page.getByRole('dialog', { name: DETAILS_DIALOG })
  await expect(dialog).toBeVisible()
  await expect(registeredBadge(page, POTTERY_TASTER)).toHaveCount(0)
  const phone = dialog.getByLabel('Phone number')
  await expectPhoneKeypad(phone)
  await expectFullWidth(page, phone)
  const confirm = dialog.getByRole('button', { name: 'Register', exact: true })
  await expectThumbSized(confirm)
  await expectThumbSized(dialog.getByRole('button', { name: 'Cancel', exact: true }))
  await expectInsideScreen(page, dialog)
  expect(await hasNoSidewaysScroll(page)).toBe(true)

  await phone.fill('+65 9184 0101')
  await dialog.getByLabel('Dietary requirements').fill('Vegetarian')
  await page.setViewportSize(DESKTOP)
  await confirm.click()

  await expect(dialog).toHaveCount(0)
  await expect(registeredBadge(page, POTTERY_TASTER)).toBeVisible()

  // AC3: remembered, and shown where the attendee registers; the next registration does not ask.
  const details = page.getByRole('region', { name: DETAILS_REGION })
  await expect(details).toContainText('+65 9184 0101')
  await expect(details).toContainText('Vegetarian')
  await registerButton(page, WATERCOLOUR_CLASS).click()
  await expect(registeredBadge(page, WATERCOLOUR_CLASS)).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(await hasNoSidewaysScroll(page)).toBe(true)

  // AC2: saved to the profile.
  await page.goto(PROFILE_PATH)
  await expect(page.getByLabel('Phone number')).toHaveValue('+65 9184 0101')
  await expect(page.getByLabel('Dietary requirements')).toHaveValue('Vegetarian')
})

test('18.4 AC3: changing the details on Upcoming events updates My profile', async ({ page }) => {
  await signIn(page, ACCOUNTS.attendee4)
  await page.goto(UPCOMING_EVENTS_PATH)
  const details = page.getByRole('region', { name: DETAILS_REGION })
  await expect(details).toContainText(DION.phone)
  await expect(details).toContainText(DION.dietary)

  await details.getByRole('button', { name: 'Change details' }).click()

  const dialog = page.getByRole('dialog', { name: DETAILS_DIALOG })
  // Filled in from the profile.
  await expect(dialog.getByLabel('Phone number')).toHaveValue(DION.phone)
  await expect(dialog.getByLabel('Dietary requirements')).toHaveValue(DION.dietary)
  await dialog.getByLabel('Dietary requirements').fill('No pork, no peanuts')
  await dialog.getByRole('button', { name: 'Save details', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(details).toContainText('No pork, no peanuts')

  await registerButton(page, BOOK_CLUB).click()
  await expect(registeredBadge(page, BOOK_CLUB)).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await page.goto(PROFILE_PATH)
  await expect(page.getByLabel('Dietary requirements')).toHaveValue('No pork, no peanuts')
})

test('18.4 AC4: a change on My profile shows on the registration list of an event registered for earlier', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee5)
  await page.goto(PROFILE_PATH)
  await page.getByLabel('Phone number').fill('+65 9184 0399')
  await page.getByLabel('Dietary requirements').fill('Gluten free')
  // The save must land before the reload, or reloading would cancel it.
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.request().method() === 'PATCH' &&
        new URL(response.url()).pathname === PROFILE_PATH,
    ),
    page.getByRole('button', { name: 'Save details' }).click(),
  ])
  // Reloading shows what was saved.
  await page.reload()
  await expect(page.getByLabel('Phone number')).toHaveValue('+65 9184 0399')
  await expect(page.getByLabel('Dietary requirements')).toHaveValue('Gluten free')

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(reportPath(EVENTS.charityQuiz))

  const esme = registrations(page).getByRole('row').filter({ hasText: ESME.name })
  await expect(esme).toContainText('+65 9184 0399')
  await expect(esme).toContainText('Gluten free')
})

test("18.4 AC5: the organiser sees each attendee's phone and dietary requirements, as a table on a desktop and as cards on a phone", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP)
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(reportPath(EVENTS.foodTastingWalk))

  const list = registrations(page)
  await expect(list.getByRole('columnheader', { name: 'Phone', exact: true })).toBeVisible()
  await expect(
    list.getByRole('columnheader', { name: 'Dietary requirements', exact: true }),
  ).toBeVisible()
  const aiden = list.getByRole('row').filter({ hasText: AIDEN.name })
  await expect(aiden).toContainText(AIDEN.phone)
  // AC6: none recorded shows as "None".
  await expect(aiden.getByRole('cell', { name: 'None', exact: true })).toBeVisible()
  const bella = list.getByRole('row').filter({ hasText: BELLA.name })
  await expect(bella).toContainText(BELLA.phone)
  await expect(bella).toContainText(BELLA.dietary)
  expect(await hasNoSidewaysScroll(page)).toBe(true)

  // On a phone each attendee is a card: no column headings, nothing wider than the screen, and
  // long dietary requirements wrap onto more lines.
  await page.setViewportSize(PHONE)
  await expect(list.getByRole('columnheader', { name: 'Phone', exact: true })).toBeHidden()
  for (const text of [AIDEN.name, AIDEN.phone, BELLA.name, BELLA.phone]) {
    await expect(list.getByText(text, { exact: true })).toBeVisible()
  }
  await expect(list.getByText('None', { exact: true })).toBeVisible()
  const bellaDietary = list.getByText(BELLA.dietary, { exact: true })
  await bellaDietary.scrollIntoViewIfNeeded()
  await expectInsideScreen(page, bellaDietary)
  expect((await bellaDietary.boundingBox())!.height).toBeGreaterThan(40)
  expect(await hasNoSidewaysScroll(page)).toBe(true)
  // Nothing in the list scrolls sideways either, so no text is hidden past its edge.
  expect(
    await list.evaluate((section) =>
      [section, ...section.querySelectorAll('*')].every(
        (element) => element.scrollWidth <= element.clientWidth + 1,
      ),
    ),
  ).toBe(true)
})

test('18.4 AC6/AC7: My profile shows what is wrong with the phone number before sending, and takes no more than 500 characters of dietary requirements', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee)
  const saves: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'PATCH' && new URL(request.url()).pathname === PROFILE_PATH) {
      saves.push(request.url())
    }
  })
  await page.goto(PROFILE_PATH)

  const phone = page.getByLabel('Phone number')
  await phone.fill('9123 456a')
  await page.getByRole('button', { name: 'Save details' }).click()

  const problem = page.getByRole('alert').filter({ hasText: PHONE_INVALID_MESSAGE })
  await expect(problem).toBeVisible()
  await expect(phone).toHaveAttribute('aria-invalid', 'true')
  const problemId = await problem.getAttribute('id')
  expect(problemId).not.toBeNull()
  expect((await phone.getAttribute('aria-describedby'))?.split(' ')).toContain(problemId)
  await expect(phone).toBeFocused()

  const dietary = page.getByLabel('Dietary requirements')
  await dietary.fill('v'.repeat(DIETARY_MAX_LENGTH + 1))
  await expect(dietary).toHaveValue('v'.repeat(DIETARY_MAX_LENGTH))
  expect(saves).toHaveLength(0)
})

test("18.4 AC7: the browser's phone check refuses 7 and 16 digits and accepts 8 and 15, as the server does", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee)
  const saves: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'PATCH' && new URL(request.url()).pathname === PROFILE_PATH) {
      saves.push(request.url())
    }
  })
  await page.goto(PROFILE_PATH)
  const phone = page.getByLabel('Phone number')
  const problem = page.getByRole('alert').filter({ hasText: PHONE_INVALID_MESSAGE })

  // Once Save was pressed, the check follows every keystroke (story 2.1 AC13's rule, shared).
  await phone.fill('9123456')
  await page.getByRole('button', { name: 'Save details' }).click()
  await expect(problem).toBeVisible()
  await phone.fill('91234567')
  await expect(problem).toHaveCount(0)
  await phone.fill('1234567890123456')
  await expect(problem).toBeVisible()
  await phone.fill('123456789012345')
  await expect(problem).toHaveCount(0)
  expect(saves).toHaveLength(0)
})

test('18.4 AC9: a withdrawn registration is listed with no phone number or dietary requirements', async ({
  page,
}) => {
  // Aiden withdrew from the heritage trail (story 18.2's seed); his profile has a phone number.
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(reportPath(EVENTS.heritageTrail))

  const aiden = registrations(page).getByRole('row').filter({ hasText: AIDEN.name })
  await expect(aiden).toContainText('Withdrawn')
  await expect(aiden).not.toContainText(AIDEN.phone)
  await expect(aiden.getByText('None', { exact: true })).toHaveCount(0)
  await expect(aiden.getByText('Not recorded', { exact: true })).toHaveCount(0)
})
