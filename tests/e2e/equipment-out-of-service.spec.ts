import { expect, test, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  corsHeaders,
  EVENTS,
  expectNoSidewaysScroll,
  inFuture,
  mainOverflow,
  signIn,
} from './support'

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
 *     End ends a record in force now, and removes one not yet started. (f16.2.5) When a scheduled
 *     record's start arrives, the catalogue and the type's page change by themselves, with no
 *     refresh: out of service now, and Scheduled becoming In force.
 * AC3 The quantity is a whole number of at least 1, there is a start, each date is finished and
 *     readable, the end is after the start and the start is not in the past - checked before
 *     anything is sent; (f16.2.5) turning the mouse wheel over the Units box leaves the number as
 *     typed, where it used to count down to 1; a record in force keeps its start; more units than are free over the
 *     period are refused by the server, and the form says so.
 * AC4 A record that leaves a hold short marks the item on its event's equipment for the
 *     coordinator.
 * AC5 Before saving, the page lists the holds the record would leave short and asks to confirm;
 *     Cancel saves nothing.
 * AC6 Only Technical Support has the catalogue; anyone else is told it is not permitted.
 * AC8 (f16.2.2) An accepted item left short reads Accepted, not Accepted (reserved). Its advice to
 *     withdraw or remove the item went with fix f16.2.4 (AC11).
 * AC9 (f16.2.2) Technical Support's holds schedule marks the same hold short. Which holds, and by
 *     how many, are backend cases.
 * AC10 (f16.2.4) A record that takes every unit an item holds closes it as Out of service: its
 *     coordinator sees it closed, with no Withdraw, Edit or Remove. The rules - whatever its stage,
 *     back to Planning, who is told, what stays closed - are backend cases.
 * AC11 (f16.2.4) An item short of only some of its units keeps its status, and its mark says how
 *     many can still be supplied, with no advice to withdraw or remove it. Seeded for the accepted
 *     screens; the other statuses from stubbed shortages, since no seeded record leaves a Pending
 *     or unsent hold short and one that did would move figures other specs read.
 * AC12 (f16.2.4) The list of holds before saving says which items saving will close, and
 *     Technical Support's queue lists a closed item once sent to them under Out of service.
 * AC13 (f16.2.4) Only the event's coordinator, an Event Coordinator Lead and Technical Support see
 *     the marks; anyone else sees each item's status alone. The server's refusal is a backend case.
 *
 * Specs share one database and run in parallel, so each flow that records units uses a window
 * of its own on a type no other flow here records against: the conference phones in 2031, and
 * from now until tomorrow for the one record in force (the seeded conference phone holds are in
 * 2027), and the mobile LED screens over the evening of EVENTS.lightShowcase in February 2030,
 * which nothing else holds. AC10's flow adds lapel microphones to the light showcase and takes
 * every lapel microphone out over its evening, when nothing else holds any. None moves a figure
 * another spec reads.
 */

const CATALOGUE_PATH = '/equipment/catalogue'
const PHONE = { width: 390, height: 844 }
const THUMB_TARGET = 44

const CONF_PHONE = 'Conference phone' // stock 6
const PROJECTOR = 'Portable projector' // stock 8
const VIDEO_CAMERA = 'Video camera' // stock 4, only this spec records against it
const SPEAKER_SET = 'Portable speaker set' // stock 5, only the f16.2.5 flow takes units out
const LED_SCREEN = 'Mobile LED screen' // stock 3, all held by the light showcase
const LAPEL_MIC = 'Lapel microphone' // stock 10, none held in February 2030
const LIGHT_SHOWCASE = 'Riverside Light Showcase'

const QUANTITY_MESSAGE = 'Enter a whole number of at least 1.'
const START_REQUIRED_MESSAGE = 'Enter when the units go out of service.'
const END_NOT_AFTER_START_MESSAGE = 'The end must be after the start.'
const START_IN_THE_PAST_MESSAGE = 'The start cannot be in the past.'
const DATE_INCOMPLETE_MESSAGE = 'Enter a complete, real date and time'
const DATE_INVALID_MESSAGE = 'Enter a valid date and time, with a four-digit year.'

const HOLDS_PATH = '/equipment/holds'
const QUEUE_PATH = '/equipment/requests'
// AC11 (f16.2.4): the advice f16.2.2 gave a short item, which no short item gives any more.
const NO_ADVICE = /withdraw it|remove it/i

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

/** The minute after this one, as the From field takes it: a record that starts in a moment. */
function nextMinute(): string {
  return new Date(Date.now() + SINGAPORE_OFFSET_MS + 60_000).toISOString().slice(0, 16)
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

  test('16.2 AC3 (f16.2.5): scrolling the page over the Units box leaves the number as typed', async ({
    page,
  }) => {
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, SPEAKER_SET)
    const units = form(page).getByLabel(/^Units/)
    await units.click()
    await units.pressSequentially('4')
    const box = (await units.boundingBox())!
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    for (let turn = 0; turn < 6; turn++) await page.mouse.wheel(0, 100)

    await expect(units).toHaveValue('4')
  })

  test('16.2 AC2 (f16.2.5): a scheduled record takes effect on the catalogue and the type page as its start arrives, with no refresh', async ({
    page,
  }) => {
    test.setTimeout(150_000)
    const note = `Starts in a minute ${Date.now()}`
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, SPEAKER_SET)
    await fillRecord(page, {
      units: '1',
      reason: 'Under maintenance',
      note,
      from: nextMinute(),
      until: inFuture(1),
    })
    await form(page).getByRole('button', { name: 'Take out of service' }).click()
    await expect(record(page, note).getByText('Scheduled', { exact: true })).toBeVisible()
    await expect(page.getByRole('main')).toContainText('0 out of service now')

    // The catalogue, open in a second tab, is not touched again from here on.
    const catalogueTab = await page.context().newPage()
    await catalogueTab.goto(CATALOGUE_PATH)
    const row = catalogue(catalogueTab).getByRole('row', { name: new RegExp(SPEAKER_SET) })
    await expect(row.getByRole('cell').nth(2)).toHaveText('0')
    await expect(row.getByRole('cell').nth(3)).toContainText('Scheduled')

    const MINUTE_AND_A_BIT = 90_000
    await expect(row.getByRole('cell').nth(2)).toHaveText('1', { timeout: MINUTE_AND_A_BIT })
    await expect(row.getByRole('cell').nth(3)).toContainText('In force')
    await expect(page.getByRole('main')).toContainText('1 out of service now', {
      timeout: MINUTE_AND_A_BIT,
    })
    await expect(record(page, note).getByText('In force', { exact: true })).toBeVisible()

    await record(page, note).getByRole('button', { name: 'End' }).click()
    await page
      .getByRole('dialog', { name: 'End this record now?' })
      .getByRole('button', { name: 'End now' })
      .click()
    await expect(record(page, note)).toHaveCount(0)
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

  test('16.2 AC4/AC5/AC8/AC9/AC11: a record that leaves a hold short lists it first, and once confirmed the coordinator sees the item short on the event and Technical Support sees the hold short on the schedule', async ({
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
    // AC12 (f16.2.4): a hold left some of its units is short, not closed.
    await expect(hold).not.toContainText('closed')
    await expect(records(page)).toContainText('No units are out of service.')
    await dialog.getByRole('button', { name: 'Save anyway' }).click()
    await expect(dialog).toHaveCount(0)
    await expect(record(page, pixels)).toContainText('1 out of service')

    // AC4: the event's coordinator sees the item short.
    await page.getByRole('button', { name: 'Sign out' }).click()
    await signIn(page, ACCOUNTS.coordinator2)
    await page.goto(`/events/${EVENTS.lightShowcase}`)
    const item = page.getByRole('listitem').filter({ hasText: LED_SCREEN })
    // AC11 (f16.2.4): how many can still be supplied, and no advice to withdraw it.
    await expect(item).toContainText('Short: 1 of 3 out of service, so only 2 can be supplied')
    await expect(item).not.toContainText(NO_ADVICE)
    // AC8: the accepted item no longer reads as reserved.
    await expect(item.getByText('Accepted', { exact: true })).toBeVisible()
    await expect(item).not.toContainText('(reserved)')

    // AC9: Technical Support's holds schedule marks the same hold.
    await page.getByRole('button', { name: 'Sign out' }).click()
    await signIn(page, ACCOUNTS.techSupport)
    await page.goto(`${HOLDS_PATH}?type=LED_SCREEN`)
    const held = page
      .getByRole('main')
      .getByRole('region', { name: LED_SCREEN, exact: true })
      .getByRole('row')
      .filter({ hasText: LIGHT_SHOWCASE })
    await expect(held).toContainText('Short: 1 of 3 out of service, so only 2 can be supplied')
    await expect(held.getByText('Accepted', { exact: true })).toBeVisible()
    await expect(held).not.toContainText('(reserved)')
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

// --- AC11 / AC13 (f16.2.4): a partly short item, and who reads its mark ---------------------------
const SHOWCASE_PATH = `/events/${EVENTS.productShowcase}`

/** Two of the showcase's holding items - microphones accepted (3), laptops not yet sent (2) -
 *  stubbed short by one, so each is seen without a record taking units. Its pending speaker set
 *  holds one unit, which can only be short of every unit, and that closes it (AC10). */
async function stubShowcaseShortByOne(page: Page) {
  let shortItems: string[] = []
  await page.route(`**${SHOWCASE_PATH}`, async (route) => {
    if (route.request().resourceType() !== 'fetch') return route.fallback()
    const response = await route.fetch()
    const event = await response.json()
    shortItems = event.equipment
      .filter(
        (item: { status: string; quantity: number }) =>
          ['REQUESTED', 'PENDING', 'ACCEPTED'].includes(item.status) && item.quantity > 1,
      )
      .map((item: { id: string }) => item.id)
    return route.fulfill({ response, json: event })
  })
  await page.route(`**${SHOWCASE_PATH}/equipment-shortages`, (route) =>
    route.fulfill({
      json: shortItems.map((id) => ({ item_id: id, units_short: 1 })),
      headers: corsHeaders(route.request()),
    }),
  )
}

function showcaseItem(page: Page, name: string) {
  return page
    .getByRole('region', { name: 'Equipment requirements' })
    .getByRole('listitem')
    .filter({ hasText: name })
}

test('16.2 AC11: an item short of some of its units keeps its status, says how many can still be supplied, and is not told to withdraw or remove it', async ({
  page,
}) => {
  await stubShowcaseShortByOne(page)
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto(SHOWCASE_PATH)
  const item = (name: string) => showcaseItem(page, name)

  const mics = item('Wireless microphone')
  await expect(mics).toContainText('Short: 1 of 3 out of service, so only 2 can be supplied')
  await expect(mics.getByText('Accepted', { exact: true })).toBeVisible()
  await expect(mics).not.toContainText('(reserved)')
  await expect(mics).not.toContainText(NO_ADVICE)

  const laptops = item('Presentation laptop')
  await expect(laptops).toContainText('Short: 1 of 2 out of service, so only 1 can be supplied')
  await expect(laptops.getByText('Not yet sent', { exact: true })).toBeVisible()
  await expect(laptops).not.toContainText(NO_ADVICE)
})

for (const [who, account, isShown] of [
  ['an Event Coordinator Lead', ACCOUNTS.lead, true],
  ['Technical Support', ACCOUNTS.techSupport, true],
  ["a coordinator not the event's", ACCOUNTS.coordinator, false],
  ['Venue Staff', ACCOUNTS.venueStaff, false],
  ['a Safety Officer', ACCOUNTS.safetyOfficer, false],
] as const) {
  test(`16.2 AC13: ${who} ${isShown ? 'sees' : 'does not see'} what units out of service leave the event short of`, async ({
    page,
  }) => {
    await stubShowcaseShortByOne(page)
    await signIn(page, account)
    await page.goto(SHOWCASE_PATH)
    const mics = showcaseItem(page, 'Wireless microphone')
    await expect(mics).toBeVisible()

    if (isShown) {
      await expect(mics).toContainText('Short: 1 of 3 out of service')
    } else {
      // The item and its status, but no mark: the page does not ask, so the stub never answers.
      await expect(mics.getByText('Accepted (reserved)', { exact: true })).toBeVisible()
      await expect(mics).not.toContainText('Short:')
    }
  })
}

// --- AC10 / AC12 (f16.2.4): a record that takes every unit an item holds closes it ----------------
test.describe('closes an item it takes every unit of', () => {
  test.describe.configure({ retries: 0 })

  test("16.2 AC10/AC12: a record that takes every unit an item holds says it will close it, then the item reads Out of service on the event and in Technical Support's queue", async ({
    page,
  }) => {
    const notes = `Clip-on mics for the hosts ${Date.now()}`
    const equipment = () => page.getByRole('region', { name: 'Equipment requirements' })
    const lapels = () => equipment().getByRole('listitem').filter({ hasText: notes })

    // The showcase's coordinator asks for two lapel microphones and sends them.
    await signIn(page, ACCOUNTS.coordinator2)
    await page.goto(`/events/${EVENTS.lightShowcase}`)
    const add = equipment().getByRole('form', { name: 'Add equipment' })
    await add.getByLabel('Equipment type').selectOption('LAPEL_MIC')
    await add.getByLabel('Quantity').fill('2')
    await add.getByLabel('Technical notes').fill(notes)
    await add.getByRole('button', { name: 'Add item' }).click()
    await expect(lapels()).toContainText('Not yet sent')
    await equipment().getByRole('button', { name: 'Submit to Technical Support' }).click()
    await expect(lapels().getByText('Pending', { exact: true })).toBeVisible()

    // AC12: Technical Support takes every lapel microphone out over the evening, and is told the
    // item will be closed before anything is saved.
    await page.getByRole('button', { name: 'Sign out' }).click()
    await signIn(page, ACCOUNTS.techSupport)
    await openType(page, LAPEL_MIC)
    await fillRecord(page, {
      units: '10',
      reason: 'Lost',
      note: `Box of lapel mics missing ${Date.now()}`,
      from: '2030-02-20T12:00',
      until: '2030-02-21T12:00',
    })
    await form(page).getByRole('button', { name: 'Take out of service' }).click()
    const dialog = page.getByRole('dialog', { name: 'Some holds will be short' })
    const hold = dialog.getByRole('listitem').filter({ hasText: LIGHT_SHOWCASE })
    await expect(hold).toContainText('2 of 2 short')
    await expect(hold).toContainText('Its item will be closed as out of service.')
    await dialog.getByRole('button', { name: 'Save anyway' }).click()
    await expect(dialog).toHaveCount(0)

    // AC12: the closed request is under Out of service in Technical Support's queue.
    await page.goto(QUEUE_PATH)
    await page.getByRole('tab', { name: /^Out of service/ }).click()
    const card = page
      .getByRole('listitem')
      .filter({ hasText: LIGHT_SHOWCASE })
      .filter({ hasText: LAPEL_MIC })
    await expect(card.getByText('Out of service', { exact: true })).toBeVisible()
    await expect(card.getByRole('button', { name: 'Accept' })).toHaveCount(0)

    // AC10: the coordinator sees the item closed, with nothing left to do to it.
    await page.getByRole('button', { name: 'Sign out' }).click()
    await signIn(page, ACCOUNTS.coordinator2)
    await page.goto(`/events/${EVENTS.lightShowcase}`)
    await expect(lapels().getByText('Out of service', { exact: true })).toBeVisible()
    await expect(lapels()).toContainText(
      'Every unit held was taken out of service, so this item was closed and nothing is held for it.',
    )
    await expect(lapels()).not.toContainText('Short:')
    await expect(lapels().getByRole('button')).toHaveCount(0)
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
