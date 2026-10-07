/**
 * Story 16.1 - fe/be: accept or decline equipment requests.
 * AC1 Technical Support accepts a pending request from the queue: it moves to the Accepted tab,
 *     and the coordinator sees it as Accepted on the event page. That the hold is kept as the
 *     reservation is a backend case.
 * AC2 Technical Support declines a pending request with a reason: it moves to the Declined tab
 *     with the reason, and the coordinator sees Declined and the reason on the event page. The
 *     hold's release and requesting the type again are backend cases.
 * AC4 a blank or spaces-only reason is blocked in the browser before any request is sent (the
 *     client-side exception in tests/CLAUDE.md). The server's own refusal is a backend case.
 * AC1/AC2 the same, from the request's own page (View details), as Venue Staff decide a booking
 *     from its page. The blank reason and the double-click are not repeated there: both pages use
 *     the same dialogs.
 * AC6 accepting a request the card already shows as short suggests declining it instead; the
 *     dialog is only opened and cancelled, so the 15.2 spec's seeded roadshow is left as it was.
 *     The refusal itself, with its figures, is a backend case.
 * AC9 a double-click on Accept sends one decision. Two staff deciding at once is a backend case.
 * AC3 (who and when, saved with the hold), AC5/AC6 (availability on accepting), AC7 (only Pending
 * can be decided) and AC8 (only Technical Support) are backend cases:
 * backend/tests/equipment/test_decide_equipment_requests.py.
 *
 * The Leadership Offsite (EVENTS.equipmentDecisions) is dedicated to this spec. Each test decides
 * its own item, a different equipment type, so the tests can run in parallel; the laptops are
 * never decided.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

const QUEUE_PATH = '/equipment/requests'
const OFFSITE = 'Leadership Offsite'
const REASON_REQUIRED = 'Enter a reason for declining this request.'
const DECISION_PATH = /\/equipment-requests\/[^/]+\/decision$/

function queueCard(page: Page, typeName: string) {
  return page.getByRole('listitem').filter({ hasText: OFFSITE }).filter({ hasText: typeName })
}

function eventItem(page: Page, typeName: string) {
  return page
    .getByRole('region', { name: 'Equipment requirements' })
    .getByRole('listitem')
    .filter({ hasText: typeName })
}

async function openOffsiteAsCoordinator(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.equipmentDecisions}`)
  await expect(page.getByRole('heading', { name: OFFSITE, level: 1 })).toBeVisible()
}

test('16.1 AC1: Technical Support accepts a request, and the coordinator sees it as Accepted', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)

  const card = queueCard(page, 'Portable speaker set')
  // When the coordinator sent it, as Venue Staff's booking cards say when they were requested.
  await expect(card.getByText('Requested at', { exact: true })).toBeVisible()
  await expect(card).toContainText('5 Oct 2026')
  await card.getByRole('button', { name: 'Accept' }).click()
  const dialog = page.getByRole('dialog', { name: 'Accept this request?' })
  await expect(dialog).toContainText(OFFSITE)
  await dialog.getByRole('button', { name: 'Accept' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(card).toHaveCount(0)

  await page.getByRole('tab', { name: /^Accepted/ }).click()
  await expect(card.getByText('Accepted', { exact: true })).toBeVisible()
  await expect(card.getByText('Decided at', { exact: true })).toBeVisible()
  await expect(card).toContainText('by Theo Tech')
  await expect(card.getByRole('button', { name: 'Accept' })).toHaveCount(0)
  await expect(card.getByRole('button', { name: 'Decline' })).toHaveCount(0)

  await openOffsiteAsCoordinator(page)
  const item = eventItem(page, 'Portable speaker set')
  await expect(item.getByText('Accepted', { exact: true })).toBeVisible()
  await expect(item).toContainText(/Decided .* by Theo Tech/)
})

test('16.1 AC2: Technical Support declines a request with a reason, and the coordinator sees it', async ({
  page,
}) => {
  const reason = 'The only LED screen that day is already promised to a client launch.'
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)

  const card = queueCard(page, 'Mobile LED screen')
  await card.getByRole('button', { name: 'Decline' }).click()
  const dialog = page.getByRole('dialog', { name: 'Decline this request?' })
  await expect(dialog).toContainText(OFFSITE)
  await dialog.getByLabel('Reason for declining').fill(reason)
  await dialog.getByRole('button', { name: 'Decline' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(card).toHaveCount(0)

  await page.getByRole('tab', { name: /^Declined/ }).click()
  await expect(card.getByText('Declined', { exact: true })).toBeVisible()
  await expect(card).toContainText(reason)

  await openOffsiteAsCoordinator(page)
  const item = eventItem(page, 'Mobile LED screen')
  await expect(item.getByText('Declined', { exact: true })).toBeVisible()
  await expect(item).toContainText(reason)
})

test('16.1 AC4: a blank or spaces-only reason is blocked before anything is sent', async ({
  page,
}) => {
  let decisionsSent = 0
  page.on('request', (request) => {
    if (DECISION_PATH.test(new URL(request.url()).pathname)) decisionsSent += 1
  })
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)

  const card = queueCard(page, 'Presentation laptop')
  await card.getByRole('button', { name: 'Decline' }).click()
  const dialog = page.getByRole('dialog', { name: 'Decline this request?' })

  await dialog.getByRole('button', { name: 'Decline' }).click()
  await expect(dialog.getByRole('alert')).toHaveText(REASON_REQUIRED)

  await dialog.getByLabel('Reason for declining').fill('   ')
  await dialog.getByRole('button', { name: 'Decline' }).click()
  await expect(dialog.getByRole('alert')).toHaveText(REASON_REQUIRED)
  await expect(dialog).toBeVisible()

  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(card.getByText('Pending', { exact: true })).toBeVisible()
  expect(decisionsSent).toBe(0)
})

test('16.1 AC9: a double-click on Accept decides once', async ({ page }) => {
  let decisionsSent = 0
  await page.route(DECISION_PATH, async (route) => {
    if (route.request().resourceType() !== 'fetch') return route.fallback()
    decisionsSent += 1
    // Hold the decision in flight, so the second click lands while it is still being saved.
    await new Promise((resolve) => setTimeout(resolve, 1000))
    return route.continue()
  })
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)

  const card = queueCard(page, 'Conference phone')
  await card.getByRole('button', { name: 'Accept' }).click()
  const dialog = page.getByRole('dialog', { name: 'Accept this request?' })
  const confirm = dialog.getByRole('button', { name: 'Accept' })
  await confirm.dblclick()

  await expect(dialog).not.toBeVisible()
  await expect(card).toHaveCount(0)
  expect(decisionsSent).toBe(1)

  await page.getByRole('tab', { name: /^Accepted/ }).click()
  await expect(card.getByText('Accepted', { exact: true })).toBeVisible()
})

test('16.1 AC1: Technical Support accepts a request from its own page', async ({ page }) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)

  await queueCard(page, 'Portable projector').getByRole('link', { name: 'View details' }).click()
  await expect(page).toHaveURL(new RegExp(`${QUEUE_PATH}/[^/]+$`))
  await expect(page.getByRole('heading', { name: OFFSITE, level: 1 })).toBeVisible()
  await expect(page.getByText('Both breakout rooms')).toBeVisible()

  await page.getByRole('button', { name: 'Accept' }).click()
  const dialog = page.getByRole('dialog', { name: 'Accept this request?' })
  await dialog.getByRole('button', { name: 'Accept' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(page.getByText('Accepted', { exact: true })).toBeVisible()
  await expect(page.getByText(/Decided .* by Theo Tech/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Accept' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Decline' })).toHaveCount(0)
})

test('16.1 AC2: Technical Support declines a request from its own page with a reason', async ({
  page,
}) => {
  const reason = 'The venue provides wireless microphones for the panel.'
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)

  await queueCard(page, 'Wireless microphone').getByRole('link', { name: 'View details' }).click()
  await expect(page.getByRole('heading', { name: OFFSITE, level: 1 })).toBeVisible()

  await page.getByRole('button', { name: 'Decline' }).click()
  const dialog = page.getByRole('dialog', { name: 'Decline this request?' })
  await dialog.getByLabel('Reason for declining').fill(reason)
  await dialog.getByRole('button', { name: 'Decline' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(page.getByText('Declined', { exact: true })).toBeVisible()
  await expect(page.getByText(reason)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Decline' })).toHaveCount(0)
})

test("16.1 AC1: the request's page opens its event, whose back link returns to the request", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)
  await queueCard(page, 'Presentation laptop').getByRole('link', { name: 'View details' }).click()
  await expect(page).toHaveURL(new RegExp(`${QUEUE_PATH}/[^/]+$`))
  const requestUrl = page.url()

  await page.getByRole('link', { name: 'View event details' }).click()
  await expect(page).toHaveURL(new RegExp(`/events/${EVENTS.equipmentDecisions}$`))
  await expect(page.getByRole('heading', { name: OFFSITE, level: 1 })).toBeVisible()

  await page.getByRole('link', { name: '← Equipment Request', exact: true }).click()
  await expect(page).toHaveURL(requestUrl)
  await expect(page.getByText('Facilitator slides')).toBeVisible()
})

test('16.1 AC6: accepting a request that is short suggests declining it instead', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)

  // The roadshow's lapel microphones: all ten held, then four out of service (15.2's seed).
  const card = page
    .getByRole('listitem')
    .filter({ hasText: 'Regional Partner Roadshow' })
    .filter({ hasText: 'Lapel microphone' })
  await card.getByRole('button', { name: 'Accept' }).click()
  const dialog = page.getByRole('dialog', { name: 'Accept this request?' })

  await expect(dialog).toContainText('Only 6 are available for this event')
  await expect(dialog).toContainText('short by 4')
  await expect(dialog).toContainText('consider declining it with a reason instead')

  // Nothing is decided: the roadshow is only read by the 15.2 queue spec.
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(card.getByText('Pending', { exact: true })).toBeVisible()
})
