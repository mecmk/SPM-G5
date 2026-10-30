import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, expectNoSidewaysScroll, inFuture, signIn } from './support'

/**
 * Story 16.2 - mark equipment out of service. END-TO-END tests: what Technical Support and a
 * coordinator click through.
 *
 * Level: e2e. The rules behind what the pages show - how many units may go out over a period,
 * which holds a shortage leaves short, who is told, who may call each endpoint, the races - are
 * proven in backend/tests/equipment/test_equipment_out_of_service_*.py, not repeated here. The
 * exceptions are the form's own checks, which stop a save before anything is sent.
 *
 * AC1 Technical Support records units of a type as out of service: how many, why, an optional
 *     note, from when and, optionally, until when.
 * AC2 The Equipment catalogue lists each type with its stock and the units out of service now;
 *     a type's page has the Out of service form and its current records, each with Edit and End.
 *     End removes a record not yet started.
 * AC3 The quantity is a whole number of at least 1, the end is after the start and the start is
 *     not in the past - checked before anything is sent; more units than are free over the
 *     period are refused by the server, and the form says so.
 * AC4 A record that leaves a hold short marks the item on its event's equipment for the
 *     coordinator.
 * AC5 Before saving, the page lists the holds the record would leave short and asks to confirm.
 * AC6 Only Technical Support has the catalogue; anyone else is told it is not permitted.
 *
 * Specs share one database and run in parallel, so each flow that records units uses a window
 * of its own, years ahead, on a type no other flow here records against: the conference phones
 * in 2031, and the mobile LED screens over the evening of Events.LIGHT_SHOWCASE in February 2030,
 * which nothing else holds. Neither moves a figure another spec reads.
 */

const CATALOGUE_PATH = '/equipment/catalogue'
const PHONE = { width: 390, height: 844 }
const THUMB_TARGET = 44

const CONF_PHONE = 'Conference phone' // stock 6
const PROJECTOR = 'Portable projector' // stock 8
const LED_SCREEN = 'Mobile LED screen' // stock 3, all held by the light showcase
const LIGHT_SHOWCASE = 'Riverside Light Showcase'

const QUANTITY_MESSAGE = 'Enter a whole number of at least 1.'
const END_NOT_AFTER_START_MESSAGE = 'The end must be after the start.'
const START_IN_THE_PAST_MESSAGE = 'The start cannot be in the past.'

function catalogue(page: Page) {
  return page.getByRole('table', { name: 'Equipment types' })
}

function form(page: Page) {
  return page.getByRole('form', { name: /out of service/i })
}

function records(page: Page) {
  return page.getByRole('region', { name: 'Current records' })
}

function record(page: Page, text: string) {
  return records(page).getByRole('listitem').filter({ hasText: text })
}

async function openType(page: Page, name: string) {
  await page.goto(CATALOGUE_PATH)
  await catalogue(page).getByRole('link', { name, exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
}

/** Every request that would change a record, from now on. */
function trackWrites(page: Page): string[] {
  const sent: string[] = []
  page.on('request', (request) => {
    const isWrite = ['POST', 'PATCH', 'DELETE'].includes(request.method())
    const isCheck = new URL(request.url()).pathname.endsWith('/out-of-service/check')
    if ((isWrite || isCheck) && request.url().includes('/out-of-service')) sent.push(request.url())
  })
  return sent
}

async function fillRecord(
  page: Page,
  { units, reason, note, from, until }: {
    units: string
    reason: string
    note?: string
    from: string
    until?: string
  },
) {
  const fields = form(page)
  await fields.getByLabel('Units').fill(units)
  await fields.getByLabel('Reason').selectOption({ label: reason })
  if (note !== undefined) await fields.getByLabel('Note').fill(note)
  await fields.getByLabel('From').fill(from)
  await fields.getByLabel('Until').fill(until ?? '')
}

// --- AC2 / AC6: the catalogue ------------------------------------------------------------------
test("16.2 AC2: Technical Support opens the catalogue from the navigation, and each type's page shows its stock and its records", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'Equipment catalogue' })
    .click()

  await expect(page.getByRole('heading', { level: 1, name: 'Equipment catalogue' })).toBeVisible()
  const projectors = catalogue(page).getByRole('row', { name: new RegExp(PROJECTOR) })
  await expect(projectors.getByRole('cell').nth(1)).toHaveText('8')
  await expect(projectors.getByRole('cell').nth(2)).toHaveText('0')

  await projectors.getByRole('link', { name: PROJECTOR }).click()

  await expect(page.getByRole('heading', { level: 1, name: PROJECTOR })).toBeVisible()
  await expect(page.getByRole('main')).toContainText('8 in stock')
  await expect(page.getByRole('main')).toContainText('0 out of service now')
  await expect(form(page)).toBeVisible()
  await expect(records(page)).toContainText('No units are out of service.')
  await page.getByRole('link', { name: '← Equipment catalogue' }).click()
  await expect(catalogue(page)).toBeVisible()
})

test('16.2 AC6: anyone but Technical Support is told the catalogue is not permitted, and has no link to it', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)

  await expect(
    page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Equipment catalogue' }),
  ).toHaveCount(0)
  await page.goto(CATALOGUE_PATH)
  await expect(page.getByRole('heading', { level: 1, name: 'Not permitted' })).toBeVisible()
})

// --- AC1 / AC2: recording, editing and ending ---------------------------------------------------
test.describe('records units out of service', () => {
  test.describe.configure({ retries: 0 })

  test('16.2 AC1/AC2: units recorded out of service are listed, can be edited, and a record not yet started is removed by End', async ({
    page,
  }) => {
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, CONF_PHONE)

    await fillRecord(page, {
      units: '2',
      reason: 'Damaged',
      note: 'Cracked speaker grille',
      from: '2031-03-03T09:00',
      until: '2031-03-10T17:00',
    })
    await form(page).getByRole('button', { name: 'Take out of service' }).click()

    const saved = record(page, 'Cracked speaker grille')
    await expect(saved).toContainText('2 out of service')
    await expect(saved).toContainText('Damaged')
    await expect(saved).toContainText('Mon, 3 Mar 2031, 09:00')
    await expect(saved).toContainText('Mon, 10 Mar 2031, 17:00')

    // AC2: Edit fills the form with the record; saving changes it in the list.
    await saved.getByRole('button', { name: 'Edit' }).click()
    await expect(form(page).getByLabel('Units')).toHaveValue('2')
    await form(page).getByLabel('Units').fill('3')
    await form(page).getByLabel('Reason').selectOption({ label: 'Under maintenance' })
    await form(page).getByRole('button', { name: 'Save changes' }).click()
    await expect(saved).toContainText('3 out of service')
    await expect(saved).toContainText('Under maintenance')

    // AC2: End on a record not yet started removes it, after asking.
    await saved.getByRole('button', { name: 'End' }).click()
    const dialog = page.getByRole('dialog', { name: 'Remove this record?' })
    await expect(dialog).toContainText('has not started')
    await dialog.getByRole('button', { name: 'Remove', exact: true }).click()
    await expect(saved).toHaveCount(0)
  })

  test('16.2 AC1: a record with no end says it is out until ended', async ({ page }) => {
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, CONF_PHONE)

    await fillRecord(page, {
      units: '1',
      reason: 'Lost',
      note: 'Left at the Tower B foyer',
      from: '2031-06-02T09:00',
    })
    await form(page).getByRole('button', { name: 'Take out of service' }).click()

    const saved = record(page, 'Left at the Tower B foyer')
    await expect(saved).toContainText('until ended')
    await saved.getByRole('button', { name: 'End' }).click()
    await page.getByRole('dialog', { name: 'Remove this record?' }).getByRole('button', { name: 'Remove', exact: true }).click()
    await expect(saved).toHaveCount(0)
  })
})

// --- AC3: the form's own checks, and the server's -----------------------------------------------
test('16.2 AC3: a missing quantity, an end before the start and a start in the past are refused before anything is sent', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await openType(page, CONF_PHONE)
  const sent = trackWrites(page)
  const fields = form(page)
  const save = fields.getByRole('button', { name: 'Take out of service' })

  await fillRecord(page, { units: '0', reason: 'Other', from: inFuture(1500), until: inFuture(1499) })
  await save.click()

  await expect(fields.getByRole('alert').filter({ hasText: QUANTITY_MESSAGE })).toBeVisible()
  await expect(fields.getByRole('alert').filter({ hasText: END_NOT_AFTER_START_MESSAGE })).toBeVisible()
  await expect(fields.getByLabel('Units')).toBeFocused()
  await expect(fields.getByLabel('Units')).toHaveAttribute('aria-invalid', 'true')

  await fields.getByLabel('Units').fill('1')
  await fields.getByLabel('From').fill(inFuture(-1))
  await fields.getByLabel('Until').fill(inFuture(1))
  await save.click()
  await expect(fields.getByRole('alert').filter({ hasText: START_IN_THE_PAST_MESSAGE })).toBeVisible()
  await expect(fields.getByLabel('From')).toBeFocused()
  expect(sent).toHaveLength(0)
})

test('16.2 AC3: more units than are free over the period are refused by the server, and the form says so', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await openType(page, PROJECTOR)

  await fillRecord(page, { units: '9', reason: 'Other', from: inFuture(1600), until: inFuture(1601) })
  await form(page).getByRole('button', { name: 'Take out of service' }).click()

  await expect(form(page).getByRole('alert')).toHaveText(
    'At most 8 can be taken out of service for that period.',
  )
  await expect(form(page).getByLabel('Units')).toHaveValue('9')
  await expect(records(page)).toContainText('No units are out of service.')
})

// --- AC4 / AC5: a record that leaves a hold short ------------------------------------------------
test.describe('takes a seeded hold short once', () => {
  test.describe.configure({ retries: 0 })

  test("16.2 AC4/AC5: a record that leaves a hold short lists it first, and once confirmed the coordinator sees the item short on the event", async ({
    page,
  }) => {
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, LED_SCREEN)

    await fillRecord(page, {
      units: '1',
      reason: 'Damaged',
      note: 'Dead pixels across the top row',
      from: '2030-02-20T12:00',
      until: '2030-02-21T12:00',
    })
    await form(page).getByRole('button', { name: 'Take out of service' }).click()

    // AC5: the hold it would leave short is listed before anything is saved.
    const dialog = page.getByRole('dialog', { name: 'Some holds will be short' })
    const hold = dialog.getByRole('listitem').filter({ hasText: LIGHT_SHOWCASE })
    await expect(hold).toContainText('1 of 3 short')
    await expect(hold).toContainText('Carl Coordinator')
    await expect(records(page)).toContainText('No units are out of service.')
    await dialog.getByRole('button', { name: 'Save anyway' }).click()
    await expect(dialog).toHaveCount(0)
    await expect(record(page, 'Dead pixels across the top row')).toContainText('1 out of service')

    // AC4: the event's coordinator sees the item short.
    await page.getByRole('button', { name: 'Sign out' }).click()
    await signIn(page, ACCOUNTS.coordinator2)
    await page.goto(`/events/${EVENTS.lightShowcase}`)
    const item = page.getByRole('listitem').filter({ hasText: LED_SCREEN })
    await expect(item).toContainText('Short: 1 of 3 out of service')
  })
})

// --- On a phone -----------------------------------------------------------------------------------
test("16.2 AC2: on a phone, a type's page fits without sideways scrolling, its fields take the width and its button is big enough for a thumb", async ({
  page,
}) => {
  await page.setViewportSize(PHONE)
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(CATALOGUE_PATH)
  await expectNoSidewaysScroll(page)
  await catalogue(page).getByRole('link', { name: CONF_PHONE, exact: true }).click()

  await expect(form(page)).toBeVisible()
  await expectNoSidewaysScroll(page)
  for (const label of ['Units', 'Reason', 'From', 'Until']) {
    const box = (await form(page).getByLabel(label).boundingBox())!
    expect(box.width).toBeGreaterThanOrEqual(PHONE.width * 0.75)
  }
  const save = form(page).getByRole('button', { name: 'Take out of service' })
  expect((await save.boundingBox())!.height).toBeGreaterThanOrEqual(THUMB_TARGET)
})
