import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, expectNoSidewaysScroll, inFuture, mainOverflow, signIn } from './support'

/**
 * Story 16.2 - mark equipment out of service: what Technical Support and a coordinator click
 * through.
 *
 * The rules behind what the pages show - how many units may go out over a period, which holds a
 * shortage leaves short, who is told, who may call each endpoint, the races - are proven in
 * backend/tests/equipment/test_equipment_out_of_service_*.py, not repeated here. The exceptions
 * are the form's own checks, which stop a save before anything is sent.
 *
 * AC1 Technical Support records units of a type as out of service: how many, why, an optional
 *     note, from when and, optionally, until when.
 * AC2 The Equipment catalogue lists each type with its stock and the units out of service now;
 *     a type's page has the Out of service form and its current records, each with Edit and End.
 *     End ends a record in force now, and removes one not yet started.
 * AC3 The quantity is a whole number of at least 1, there is a start, each date is finished and
 *     readable, the end is after the start and the start is not in the past - checked before
 *     anything is sent; a record in force keeps its start; more units than are free over the
 *     period are refused by the server, and the form says so.
 * AC4 A record that leaves a hold short marks the item on its event's equipment for the
 *     coordinator.
 * AC5 Before saving, the page lists the holds the record would leave short and asks to confirm;
 *     Cancel saves nothing.
 * AC6 Only Technical Support has the catalogue; anyone else is told it is not permitted.
 *
 * Specs share one database and run in parallel, so each flow that records units uses a window
 * of its own on a type no other flow here records against: the conference phones in 2031, and
 * from now until tomorrow for the one record in force (the seeded conference phone holds are in
 * 2027), and the mobile LED screens over the evening of EVENTS.lightShowcase in February 2030,
 * which nothing else holds. None moves a figure another spec reads.
 */

const CATALOGUE_PATH = '/equipment/catalogue'
const PHONE = { width: 390, height: 844 }
const THUMB_TARGET = 44

const CONF_PHONE = 'Conference phone' // stock 6
const PROJECTOR = 'Portable projector' // stock 8
const VIDEO_CAMERA = 'Video camera' // stock 4, only this spec records against it
const LED_SCREEN = 'Mobile LED screen' // stock 3, all held by the light showcase
const LIGHT_SHOWCASE = 'Riverside Light Showcase'

const QUANTITY_MESSAGE = 'Enter a whole number of at least 1.'
const START_REQUIRED_MESSAGE = 'Enter when the units go out of service.'
const END_NOT_AFTER_START_MESSAGE = 'The end must be after the start.'
const START_IN_THE_PAST_MESSAGE = 'The start cannot be in the past.'
const DATE_INCOMPLETE_MESSAGE = 'Finish entering the date and time'
const DATE_INVALID_MESSAGE = 'Enter a valid date and time, with a four-digit year.'

/** Singapore's clock, which every date field reads (frontend/src/shared/format.ts). */
const SINGAPORE_OFFSET_MS = 8 * 60 * 60 * 1000
/** Seconds left in a minute that are enough to fill the form and save before it rolls over. */
const LATEST_SECOND_TO_START = 40

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

/** The current minute, as the From field takes it: a record that starts now. It waits for a
 *  fresh minute when this one is nearly over, so the start cannot slip into the past between
 *  filling the form and saving it. */
async function thisMinute(): Promise<string> {
  await expect
    .poll(() => new Date().getSeconds(), { timeout: 30_000 })
    .toBeLessThan(LATEST_SECOND_TO_START)
  return new Date(Date.now() + SINGAPORE_OFFSET_MS).toISOString().slice(0, 16)
}

/** Every save of a record from now on - and, with `isCheckCounted`, the check before saving
 *  too, which writes nothing but is only sent for a form that passed its own checks. */
function trackSends(page: Page, { isCheckCounted }: { isCheckCounted: boolean }): string[] {
  const sent: string[] = []
  page.on('request', (request) => {
    const isWrite = ['POST', 'PATCH', 'DELETE'].includes(request.method())
    const isCheck = new URL(request.url()).pathname.endsWith('/out-of-service/check')
    if ((isWrite || (isCheckCounted && isCheck)) && request.url().includes('/out-of-service')) {
      sent.push(request.url())
    }
  })
  return sent
}

async function fillRecord(
  page: Page,
  {
    units,
    reason,
    note,
    from,
    until,
  }: {
    units: string
    reason: string
    note?: string
    from: string
    until?: string
  },
) {
  const fields = form(page)
  // Anchored: a refused From's label holds its message, which says "units" too.
  await fields.getByLabel(/^Units/).fill(units)
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
  await expect(projectors.getByRole('cell').nth(3)).toHaveText('—')

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
    page
      .getByRole('navigation', { name: 'Main' })
      .getByRole('link', { name: 'Equipment catalogue' }),
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
    const grille = `Cracked speaker grille ${Date.now()}`
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, CONF_PHONE)

    await fillRecord(page, {
      units: '2',
      reason: 'Damaged',
      note: grille,
      from: '2031-03-03T09:00',
      until: '2031-03-10T17:00',
    })
    await form(page).getByRole('button', { name: 'Take out of service' }).click()

    const saved = record(page, grille)
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
    const foyer = `Left at the Tower B foyer ${Date.now()}`
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, CONF_PHONE)

    await fillRecord(page, {
      units: '1',
      reason: 'Lost',
      note: foyer,
      from: '2031-06-02T09:00',
    })
    await form(page).getByRole('button', { name: 'Take out of service' }).click()

    const saved = record(page, foyer)
    await expect(saved).toContainText('until ended')
    await saved.getByRole('button', { name: 'End' }).click()
    await page
      .getByRole('dialog', { name: 'Remove this record?' })
      .getByRole('button', { name: 'Remove', exact: true })
      .click()
    await expect(saved).toHaveCount(0)
  })

  test('16.2 AC2/AC3: a record in force keeps its start on Edit, and End ends it now and closes its edit', async ({
    page,
  }) => {
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, CONF_PHONE)
    // One unbroken run of serial numbers: the note still wraps inside its row.
    const serials = `Serials ${Date.now()}: ${'SN0123456789'.repeat(34)}`

    await fillRecord(page, {
      units: '2',
      reason: 'Under maintenance',
      note: serials,
      from: await thisMinute(),
      until: inFuture(1),
    })
    await form(page).getByRole('button', { name: 'Take out of service' }).click()

    const saved = record(page, serials)
    const badge = saved.getByText('In force', { exact: true })
    await expect(badge).toBeVisible()
    await expect(page.getByRole('main')).toContainText('2 out of service now')
    const note = (await saved.getByText(serials).boundingBox())!
    expect(note.x + note.width).toBeLessThanOrEqual((await badge.boundingBox())!.x)

    // AC3: a record in force keeps its start; its units can still change.
    await saved.getByRole('button', { name: 'Edit' }).click()
    await expect(form(page).getByLabel('From')).toBeDisabled()
    await form(page).getByLabel('Units').fill('3')
    await form(page).getByRole('button', { name: 'Save changes' }).click()
    await expect(saved).toContainText('3 out of service')
    await expect(page.getByRole('main')).toContainText('3 out of service now')

    // AC2: End ends it now, after asking, and an edit open on it closes with it.
    await saved.getByRole('button', { name: 'Edit' }).click()
    await expect(
      form(page).getByRole('heading', { name: 'Edit units out of service' }),
    ).toBeVisible()
    await saved.getByRole('button', { name: 'End' }).click()
    await page
      .getByRole('dialog', { name: 'End this record now?' })
      .getByRole('button', { name: 'End now' })
      .click()
    await expect(saved).toHaveCount(0)
    await expect(page.getByRole('main')).toContainText('0 out of service now')
    await expect(
      form(page).getByRole('heading', { name: 'Take units out of service' }),
    ).toBeVisible()
  })

  test('16.2 AC2: a period still to come shows on the catalogue with its units, its status and from when to when', async ({
    page,
  }) => {
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, VIDEO_CAMERA)
    const note = `Scheduled check ${Date.now()}`

    await fillRecord(page, {
      units: '2',
      reason: 'Under maintenance',
      note,
      from: inFuture(2),
      until: inFuture(3),
    })
    await form(page).getByRole('button', { name: 'Take out of service' }).click()
    await expect(record(page, note).getByText('Scheduled', { exact: true })).toBeVisible()

    await page.getByRole('link', { name: '← Equipment catalogue' }).click()
    const row = catalogue(page).getByRole('row', { name: new RegExp(VIDEO_CAMERA) })
    await expect(row.getByRole('cell').nth(2)).toHaveText('0')
    await expect(row.getByRole('cell').nth(3)).toContainText('2 out of service')
    await expect(row.getByRole('cell').nth(3)).toContainText('Scheduled')
    await expect(row.getByRole('cell').nth(3)).toContainText(' – ')

    await page.getByLabel('Period status').selectOption('IN_FORCE')
    await expect(row).toHaveCount(0)
    await page.getByLabel('Period status').selectOption('SCHEDULED')
    await expect(row).toBeVisible()

    await row.getByRole('cell').nth(4).click()
    await expect(page.getByRole('heading', { level: 1, name: VIDEO_CAMERA })).toBeVisible()
    await record(page, note).getByRole('button', { name: 'End' }).click()
    await page
      .getByRole('dialog', { name: 'Remove this record?' })
      .getByRole('button', { name: 'Remove', exact: true })
      .click()
    await expect(record(page, note)).toHaveCount(0)
  })

  test('16.2 AC3: an edit can take the whole stock out, as the record is not counted against itself', async ({
    page,
  }) => {
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, CONF_PHONE)
    const note = `Whole batch recalled ${Date.now()}`

    await fillRecord(page, {
      units: '5',
      reason: 'Other',
      note,
      // Before the open-ended record of the test above, which runs alongside.
      from: '2031-05-05T09:00',
      until: '2031-05-06T09:00',
    })
    await form(page).getByRole('button', { name: 'Take out of service' }).click()
    const saved = record(page, note)
    await expect(saved).toContainText('5 out of service')

    await saved.getByRole('button', { name: 'Edit' }).click()
    await form(page).getByLabel('Units').fill('6')
    await form(page).getByRole('button', { name: 'Save changes' }).click()
    await expect(saved).toContainText('6 out of service')

    await saved.getByRole('button', { name: 'End' }).click()
    await page
      .getByRole('dialog', { name: 'Remove this record?' })
      .getByRole('button', { name: 'Remove', exact: true })
      .click()
    await expect(saved).toHaveCount(0)
  })
})

// --- AC3: the form's own checks, and the server's -----------------------------------------------
test('16.2 AC3: a missing quantity or start, a quantity of 0 or one too large to hold, an end before the start and a start in the past are refused before anything is sent', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await openType(page, CONF_PHONE)
  const sent = trackSends(page, { isCheckCounted: true })
  const fields = form(page)
  const save = fields.getByRole('button', { name: 'Take out of service' })

  await save.click()
  await expect(fields.getByRole('alert').filter({ hasText: QUANTITY_MESSAGE })).toBeVisible()
  await expect(fields.getByRole('alert').filter({ hasText: START_REQUIRED_MESSAGE })).toBeVisible()
  await expect(fields.getByLabel(/^Units/)).toBeFocused()

  await fillRecord(page, {
    units: '0',
    reason: 'Other',
    from: inFuture(1500),
    until: inFuture(1499),
  })
  await save.click()

  await expect(fields.getByRole('alert').filter({ hasText: QUANTITY_MESSAGE })).toBeVisible()
  await expect(
    fields.getByRole('alert').filter({ hasText: END_NOT_AFTER_START_MESSAGE }),
  ).toBeVisible()
  await expect(fields.getByLabel('Units')).toBeFocused()
  await expect(fields.getByLabel('Units')).toHaveAttribute('aria-invalid', 'true')

  await fields.getByLabel('Units').fill('1')
  await fields.getByLabel('From').fill(inFuture(-1))
  await fields.getByLabel('Until').fill(inFuture(1))
  await save.click()
  await expect(
    fields.getByRole('alert').filter({ hasText: START_IN_THE_PAST_MESSAGE }),
  ).toBeVisible()
  await expect(fields.getByLabel('From')).toBeFocused()

  // A number too long to hold exactly would be sent as 1e+24, which the server cannot read.
  await fields.getByLabel('Units').fill(`1${'0'.repeat(24)}`)
  await fields.getByLabel('From').fill(inFuture(1500))
  await fields.getByLabel('Until').fill(inFuture(1501))
  await save.click()
  await expect(fields.getByRole('alert').filter({ hasText: QUANTITY_MESSAGE })).toBeVisible()
  await expect(fields.getByLabel('Units')).toBeFocused()
  expect(sent).toHaveLength(0)
})

test('16.2 AC3: a year of five digits, or a date left half typed, on either date is refused before anything is sent', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await openType(page, CONF_PHONE)
  const sent = trackSends(page, { isCheckCounted: true })
  const fields = form(page)
  const save = fields.getByRole('button', { name: 'Take out of service' })

  await fillRecord(page, { units: '1', reason: 'Damaged', from: '20311-03-03T09:00' })
  await save.click()
  await expect(fields.getByRole('alert').filter({ hasText: DATE_INVALID_MESSAGE })).toBeVisible()
  await expect(fields.getByLabel('From')).toBeFocused()

  // A date started but not finished reads as blank, which for Until would mean "until ended".
  await fields.getByLabel('From').fill('2031-03-03T09:00')
  await fields.getByLabel('Until').focus()
  await page.keyboard.type('0310')
  await save.click()
  await expect(fields.getByRole('alert').filter({ hasText: DATE_INCOMPLETE_MESSAGE })).toBeVisible()
  await expect(fields.getByLabel('Until')).toBeFocused()

  await fields.getByLabel('Until').fill('20311-03-04T09:00')
  await save.click()
  await expect(fields.getByRole('alert').filter({ hasText: DATE_INVALID_MESSAGE })).toBeVisible()
  await expect(fields.getByLabel('Until')).toBeFocused()

  await fields.getByLabel('Until').fill('')
  await fields.getByLabel('From').fill('')
  await fields.getByLabel('From').focus()
  await page.keyboard.type('0310')
  await save.click()
  await expect(fields.getByRole('alert').filter({ hasText: DATE_INCOMPLETE_MESSAGE })).toBeVisible()
  await expect(fields.getByLabel('From')).toBeFocused()
  expect(sent).toHaveLength(0)
})

test('16.2 AC3: more units than are free over the period are refused by the server, and the form says so', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await openType(page, PROJECTOR)

  await fillRecord(page, {
    units: '9',
    reason: 'Other',
    from: inFuture(1600),
    until: inFuture(1601),
  })
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

  test('16.2 AC4/AC5: a record that leaves a hold short lists it first, and once confirmed the coordinator sees the item short on the event', async ({
    page,
  }) => {
    const pixels = `Dead pixels across the top row ${Date.now()}`
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, LED_SCREEN)

    await fillRecord(page, {
      units: '1',
      reason: 'Damaged',
      note: pixels,
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
    await expect(record(page, pixels)).toContainText('1 out of service')

    // AC4: the event's coordinator sees the item short.
    await page.getByRole('button', { name: 'Sign out' }).click()
    await signIn(page, ACCOUNTS.coordinator2)
    await page.goto(`/events/${EVENTS.lightShowcase}`)
    const item = page.getByRole('listitem').filter({ hasText: LED_SCREEN })
    await expect(item).toContainText('Short: 1 of 3 out of service')
  })

  test('16.2 AC5: Cancel on the list of holds left short saves nothing', async ({ page }) => {
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, LED_SCREEN)
    const saves = trackSends(page, { isCheckCounted: false })
    const note = `Cracked panel ${Date.now()}`

    await fillRecord(page, {
      units: '1',
      reason: 'Damaged',
      note,
      from: '2030-02-20T12:00',
      until: '2030-02-21T12:00',
    })
    await form(page).getByRole('button', { name: 'Take out of service' }).click()
    const dialog = page.getByRole('dialog', { name: 'Some holds will be short' })
    await expect(dialog.getByRole('listitem').filter({ hasText: LIGHT_SHOWCASE })).toBeVisible()
    await dialog.getByRole('button', { name: 'Cancel' }).click()

    await expect(dialog).toHaveCount(0)
    await expect(record(page, note)).toHaveCount(0)
    expect(saves).toHaveLength(0)
  })
})

// --- On a phone -----------------------------------------------------------------------------------
test("16.2 AC2: on a phone, the catalogue's columns and a type's page fit without sideways scrolling, its fields take the width and its button is big enough for a thumb", async ({
  page,
}) => {
  await page.setViewportSize(PHONE)
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(CATALOGUE_PATH)
  await expect(
    catalogue(page).getByRole('columnheader', { name: 'Out of service now' }),
  ).toBeVisible()
  // The table scrolls inside its own frame, so it is the table that has to fit, not the page.
  const tableFits = await catalogue(page).evaluate(
    (table) => table.scrollWidth <= table.parentElement!.clientWidth,
  )
  expect(tableFits).toBe(true)
  expect(await mainOverflow(page)).toBeLessThanOrEqual(0)
  await expectNoSidewaysScroll(page)
  await catalogue(page).getByRole('link', { name: CONF_PHONE, exact: true }).click()

  await expect(form(page)).toBeVisible()
  expect(await mainOverflow(page)).toBeLessThanOrEqual(0)
  await expectNoSidewaysScroll(page)
  for (const label of ['Units', 'Reason', 'From', 'Until']) {
    const box = (await form(page).getByLabel(label).boundingBox())!
    expect(box.width).toBeGreaterThanOrEqual(PHONE.width * 0.75)
  }
  const save = form(page).getByRole('button', { name: 'Take out of service' })
  expect((await save.boundingBox())!.height).toBeGreaterThanOrEqual(THUMB_TARGET)
})
