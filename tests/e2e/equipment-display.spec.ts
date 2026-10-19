/**
 * Story 17.1 - fe/be: display equipment reserved for my event.
 * AC1 the event page's Equipment requirements section lists each item with its type, quantity,
 *     period and status: here the coordinator reads the roadshow's pending, accepted (reserved)
 *     and declined items, each with its period, and the declined one with Technical Support's
 *     reason. A decided item names the decision - Accepted or Declined - and who made it and when,
 *     and no item that is still open says it holds nothing. That an item's period is what its hold
 *     covers - kept when a correction moves the event inside it - or its event's while it holds
 *     nothing, and that a draft's item has none until the event has dates, are backend cases.
 * AC2 the owning organiser sees the same list, read-only: no way to add, edit, remove or send.
 * AC3 an event with no equipment says so.
 * AC4 an item released with its cancelled event shows as Released. The two still open when it
 *     was cancelled say they hold nothing. The third was declined and then removed by an approved
 *     change (19.2): it still shows who declined it and why, and says nothing about a hold, which
 *     its decline had released.
 * AC5 Technical Support, opening the event from its queue, sees the list read-only. That every
 *     internal role is sent it, an attendee is refused (403) and another organiser is told the
 *     event is not found (404) are backend cases.
 * AC6 a decision made while the coordinator has the page open shows once it is loaded again.
 * The list also fits a phone.
 * Here is what each viewer sees on the page. What the API sends - each item's fields and period,
 * to whom, and the refusals - is backend/tests/equipment/test_display_equipment_integration.py's.
 *
 * The roadshow (EVENTS.equipmentRoadshow) and the Summer Rooftop Mixer (EVENTS.cancelled) are
 * only read here, and nothing can change a Confirmed event's equipment (EVENTS.confirmed, 15.1
 * AC9). The waterfront demo (EVENTS.waterfrontDemo) is this spec's own: its one pending item is
 * accepted in AC6, and no other case reads it.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

const QUEUE_PATH = '/equipment/requests'
const ROADSHOW = 'Regional Partner Roadshow'
const ROADSHOW_PERIOD = 'For Wed, 16 Jun 2027 · 09:00–17:00'
const MIXER = 'Summer Rooftop Mixer'
const MIXER_PERIOD = 'For Mon, 5 Oct 2026 · 18:00–21:00'
const DEMO = 'Waterfront Product Demo'
const ACCEPTED = 'Accepted (reserved)'
const RELEASED = 'Released'
const HOLDS_NOTHING = 'Nothing is held for this item any more.'
const DECLINE_REASON = 'Every portable projector is out on loan that week.'
const MIXER_DECLINE_REASON = 'All the portable projectors are booked that evening.'
const ACCEPTED_BY_THEO = /Accepted .* by Theo Tech/
const DECLINED_BY_THEO = /Declined .* by Theo Tech/
const PHONE = { width: 390, height: 844 }

function equipmentSection(page: Page) {
  return page.getByRole('region', { name: 'Equipment requirements' })
}

function item(page: Page, typeName: string) {
  return equipmentSection(page).getByRole('listitem').filter({ hasText: typeName })
}

/** Laid out on a single line: every box of its text at the same height. (An inline element has a
 *  box per text node and per line, so the boxes are counted by where they sit, not one by one.) */
async function expectOnOneLine(text: Locator) {
  await expect(text).toBeVisible()
  const lineTops = await text.evaluate(
    (element) => new Set(Array.from(element.getClientRects(), (box) => Math.round(box.top))).size,
  )
  expect(lineTops).toBe(1)
}

async function openEvent(page: Page, account: string, eventId: string, name: string) {
  await signIn(page, account)
  await page.goto(`/events/${eventId}`)
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
}

/** The roadshow's three items, as anyone who can open the event reads them (AC1, AC2, AC5). */
async function expectRoadshowItems(page: Page) {
  const pending = item(page, 'Lapel microphone')
  await expect(pending).toContainText('×10')
  await expect(pending).toContainText(ROADSHOW_PERIOD)
  await expect(pending.getByText('Pending', { exact: true })).toBeVisible()
  await expect(pending).not.toContainText(HOLDS_NOTHING)

  const accepted = item(page, 'Wireless microphone')
  await expect(accepted).toContainText('×4')
  await expect(accepted).toContainText(ROADSHOW_PERIOD)
  await expect(accepted.getByText(ACCEPTED, { exact: true })).toBeVisible()
  await expect(accepted).toContainText(ACCEPTED_BY_THEO)
  await expect(accepted).not.toContainText(HOLDS_NOTHING)

  const declined = item(page, 'Portable projector')
  await expect(declined).toContainText('×3')
  await expect(declined).toContainText(ROADSHOW_PERIOD)
  await expect(declined.getByText('Declined', { exact: true })).toBeVisible()
  await expect(declined).toContainText(DECLINED_BY_THEO)
  await expect(declined).toContainText(DECLINE_REASON)
  await expect(declined).not.toContainText(HOLDS_NOTHING)
}

/** Nothing on the section changes the equipment (AC2, AC5). */
async function expectReadOnly(page: Page) {
  const section = equipmentSection(page)
  await expect(section.getByRole('form', { name: 'Add equipment' })).toHaveCount(0)
  await expect(section.getByRole('button', { name: /^Edit / })).toHaveCount(0)
  await expect(section.getByRole('button', { name: /^Remove / })).toHaveCount(0)
  await expect(section.getByRole('button', { name: 'Submit to Technical Support' })).toHaveCount(0)
}

test('17.1 AC1: the coordinator sees each item with its quantity, period and status', async ({
  page,
}) => {
  await openEvent(page, ACCOUNTS.coordinator, EVENTS.equipmentRoadshow, ROADSHOW)

  await expectRoadshowItems(page)
})

test('17.1 AC2: the organiser sees the same items, read-only', async ({ page }) => {
  await openEvent(page, ACCOUNTS.organiser2, EVENTS.equipmentRoadshow, ROADSHOW)

  await expectRoadshowItems(page)
  await expectReadOnly(page)
})

test('17.1 AC3: an event with no equipment says none was requested', async ({ page }) => {
  await openEvent(page, ACCOUNTS.coordinator, EVENTS.confirmed, 'Partner Appreciation Dinner')

  await expect(equipmentSection(page).getByText('No equipment requested.')).toBeVisible()
  await expect(equipmentSection(page).getByRole('listitem')).toHaveCount(0)
})

test('17.1 AC4: items released with their cancelled event show as Released, holding nothing', async ({
  page,
}) => {
  await openEvent(page, ACCOUNTS.coordinator, EVENTS.cancelled, MIXER)

  for (const typeName of ['Portable speaker set', 'Wireless microphone', 'Portable projector']) {
    const released = item(page, typeName)
    await expect(released).toContainText(MIXER_PERIOD)
    const badge = released.getByText(RELEASED, { exact: true })
    await expect(badge).toBeVisible()
    // A released hold is neither a decision nor a problem: it reads in the neutral colour.
    await expect(badge).toHaveClass(/\bbadge-released\b/)
  }
  // The speakers had been accepted, the microphones were still pending: both were held until the
  // event was cancelled.
  const speakers = item(page, 'Portable speaker set')
  await expect(speakers).toContainText(ACCEPTED_BY_THEO)
  await expect(speakers).toContainText(HOLDS_NOTHING)
  const microphones = item(page, 'Wireless microphone')
  await expect(microphones).not.toContainText(/(Accepted|Declined) .* by/)
  await expect(microphones).toContainText(HOLDS_NOTHING)
  // The projector was declined, then removed by an approved change: who declined it and why still
  // show, and its hold went when it was declined, so it says nothing about one.
  const projector = item(page, 'Portable projector')
  await expect(projector).toContainText(DECLINED_BY_THEO)
  await expect(projector).toContainText(MIXER_DECLINE_REASON)
  await expect(projector).not.toContainText(HOLDS_NOTHING)
  await expectReadOnly(page)
})

test('17.1 AC5: Technical Support open the event from their queue and see the items read-only', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)
  await page
    .getByRole('listitem')
    .filter({ hasText: ROADSHOW })
    .first()
    .getByRole('link', { name: ROADSHOW })
    .click()
  await expect(page).toHaveURL(new RegExp(`/events/${EVENTS.equipmentRoadshow}$`))

  await expectRoadshowItems(page)
  await expectReadOnly(page)
})

test('17.1 AC6: a decision made while the page is open shows once it is loaded again', async ({
  page,
  browser,
}) => {
  // Two people sign in, and Technical Support's queue works out every request's figures.
  test.setTimeout(60_000)
  await openEvent(page, ACCOUNTS.coordinator, EVENTS.waterfrontDemo, DEMO)
  const laptops = item(page, 'Presentation laptop')
  await expect(laptops.getByText('Pending', { exact: true })).toBeVisible()

  const techContext = await browser.newContext({ baseURL: new URL(page.url()).origin })
  const tech = await techContext.newPage()
  await signIn(tech, ACCOUNTS.techSupport)
  await tech.goto(QUEUE_PATH)
  const card = tech.getByRole('listitem').filter({ hasText: DEMO })
  await card.getByRole('button', { name: 'Accept' }).click()
  const dialog = tech.getByRole('dialog', { name: 'Accept this request?' })
  await dialog.getByRole('button', { name: 'Accept' }).click()
  await expect(dialog).not.toBeVisible()
  await techContext.close()

  // The page shows the list as it was loaded, until it is loaded again.
  await expect(laptops.getByText('Pending', { exact: true })).toBeVisible()
  await page.reload()
  await expect(laptops.getByText(ACCEPTED, { exact: true })).toBeVisible()
  await expect(laptops).toContainText(ACCEPTED_BY_THEO)
})

test('17.1 responsive: the list fits a phone', async ({ page }) => {
  await page.setViewportSize(PHONE)
  await openEvent(page, ACCOUNTS.coordinator, EVENTS.equipmentRoadshow, ROADSHOW)

  // Each item's text takes the row's width, so its notes and its period each keep to one line
  // rather than being squeezed beside the quantity, the badge and the coordinator's buttons.
  for (const [typeName, notes] of [
    ['Lapel microphone', 'One per panel speaker'],
    ['Wireless microphone', 'For audience questions'],
    ['Portable projector', 'Ceiling-mounted screens preferred'],
  ]) {
    const row = item(page, typeName)
    await expectOnOneLine(row.getByText(notes, { exact: true }))
    await expectOnOneLine(row.getByText(ROADSHOW_PERIOD, { exact: true }))
    const box = (await row.boundingBox())!
    expect(box.x + box.width).toBeLessThanOrEqual(PHONE.width)
  }
  await expect(item(page, 'Wireless microphone').getByText(ACCEPTED, { exact: true })).toBeVisible()
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )
  expect(fits).toBe(true)
})
