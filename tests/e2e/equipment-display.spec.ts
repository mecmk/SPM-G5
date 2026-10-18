/**
 * Story 17.1 - fe/be: display equipment reserved for my event.
 * AC1 the event page's Equipment requirements section lists each item with its type, quantity,
 *     period and status: here the coordinator reads the roadshow's pending, accepted (reserved)
 *     and declined items, each with the event's period, and the declined one with Technical
 *     Support's reason. That the period is the event's own, and follows it when the dates change,
 *     is a backend case; so is a draft's item, which has no period until the event has dates.
 * AC2 the owning organiser sees the same list, read-only: no way to add, edit, remove or send.
 * AC3 an event with no equipment says so.
 * AC4 an item released with its cancelled event shows as Released and says it holds nothing.
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
import { expect, test, type Page } from '@playwright/test'
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
const PHONE = { width: 390, height: 844 }

function equipmentSection(page: Page) {
  return page.getByRole('region', { name: 'Equipment requirements' })
}

function item(page: Page, typeName: string) {
  return equipmentSection(page).getByRole('listitem').filter({ hasText: typeName })
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

  const accepted = item(page, 'Wireless microphone')
  await expect(accepted).toContainText('×4')
  await expect(accepted).toContainText(ROADSHOW_PERIOD)
  await expect(accepted.getByText(ACCEPTED, { exact: true })).toBeVisible()
  await expect(accepted).toContainText(/Decided .* by Theo Tech/)

  const declined = item(page, 'Portable projector')
  await expect(declined).toContainText('×3')
  await expect(declined).toContainText(ROADSHOW_PERIOD)
  await expect(declined.getByText('Declined', { exact: true })).toBeVisible()
  await expect(declined).toContainText(DECLINE_REASON)
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

  for (const typeName of ['Portable speaker set', 'Wireless microphone']) {
    const released = item(page, typeName)
    await expect(released).toContainText('×2')
    await expect(released).toContainText(MIXER_PERIOD)
    await expect(released.getByText(RELEASED, { exact: true })).toBeVisible()
    await expect(released).toContainText(HOLDS_NOTHING)
  }
  // The speakers had been accepted before the event was cancelled: who decided still shows.
  await expect(item(page, 'Portable speaker set')).toContainText(/Decided .* by Theo Tech/)
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
  await expect(laptops).toContainText(/Decided .* by Theo Tech/)
})

test('17.1 responsive: the list fits a phone', async ({ page }) => {
  await page.setViewportSize(PHONE)
  await openEvent(page, ACCOUNTS.coordinator, EVENTS.equipmentRoadshow, ROADSHOW)

  for (const typeName of ['Lapel microphone', 'Wireless microphone', 'Portable projector']) {
    const row = item(page, typeName)
    await expect(row.getByText(ROADSHOW_PERIOD)).toBeVisible()
    const box = (await row.boundingBox())!
    expect(box.x + box.width).toBeLessThanOrEqual(PHONE.width)
  }
  await expect(item(page, 'Wireless microphone').getByText(ACCEPTED, { exact: true })).toBeVisible()
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )
  expect(fits).toBe(true)
})
