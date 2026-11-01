/**
 * Story 17.2 - fe/be: withdraw booked equipment.
 * AC1 on the event page's Equipment requirements section, the assigned coordinator withdraws an
 *     item Technical Support accepted, after confirming. That its units are released at once is a
 *     backend case.
 * AC7 closing the confirmation first leaves the item as it was.
 * AC3 the withdrawn item stays on the page as Withdrawn, with who withdrew it and when, and its
 *     type is offered again under Add equipment.
 * AC10 the organiser sees the withdrawn item read-only, with no way to withdraw anything. That
 *     every other user is refused is a backend case.
 * AC2 a pending item offers Withdraw, not Remove, and is withdrawn the same way.
 * AC4 Technical Support find it under Withdrawn in their queue, read-only, with no Accept or
 *     Decline. Who is notified, and what the notice names, are backend cases.
 * AC5 Withdraw is not offered once the event is Awaiting Safety Check (the harbour concert). That a
 *     direct request is refused on every closed status is a backend case.
 * AC11 Technical Support accept an item while its Withdraw dialog is open: the dialog says it is
 *     now accepted, offers only Close, and the page shows it Accepted. The race itself and a
 *     double-click are backend cases.
 * AC6 (which statuses can be withdrawn), AC8/AC9 (the safety check) and the API's refusals are
 * backend cases: backend/tests/equipment/test_withdraw_equipment.py.
 *
 * The riverside summit (EVENTS.riversideSummit) is this spec's own: each test withdraws a
 * different item on it, the accepted speakers or the pending microphones, so the tests can run
 * in parallel. The AC11 test submits a request of its own.
 */
import { expect, test, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  EVENTS,
  assignByLead,
  createAndSubmitRequest,
  signIn,
  uniqueName,
} from './support'

const QUEUE_PATH = '/equipment/requests'
const SUMMIT = 'Riverside Partner Summit'
const SPEAKERS = 'Portable speaker set'
const MICROPHONES = 'Wireless microphone'
const LAPTOP = 'Presentation laptop'
const WITHDRAWN_BY_CHLOE = /Withdrawn .* by Chloe Coordinator/

function equipmentSection(page: Page) {
  return page.getByRole('region', { name: 'Equipment requirements' })
}

function item(page: Page, typeName: string) {
  return equipmentSection(page).getByRole('listitem').filter({ hasText: typeName })
}

async function openSummit(page: Page, account: string) {
  await signIn(page, account)
  await page.goto(`/events/${EVENTS.riversideSummit}`)
  await expect(page.getByRole('heading', { name: SUMMIT, level: 1 })).toBeVisible()
}

test('17.2 AC1/AC3/AC7/AC10: the coordinator withdraws an accepted item after confirming, and the organiser sees it read-only', async ({
  page,
}) => {
  await openSummit(page, ACCOUNTS.coordinator)
  const speakers = item(page, SPEAKERS)
  await expect(speakers).toContainText('Accepted (reserved)')

  // AC7: closing the confirmation changes nothing.
  await speakers.getByRole('button', { name: `Withdraw ${SPEAKERS}` }).click()
  const dialog = page.getByRole('dialog', { name: 'Withdraw this equipment?' })
  await expect(dialog).toContainText(`${SPEAKERS} ×2`)
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(speakers).toContainText('Accepted (reserved)')

  await speakers.getByRole('button', { name: `Withdraw ${SPEAKERS}` }).click()
  await dialog.getByRole('button', { name: 'Withdraw' }).click()
  await expect(dialog).not.toBeVisible()

  // AC3: kept on the page, saying who withdrew it and when, and its type can be asked for again.
  await expect(speakers).toContainText('Withdrawn')
  await expect(speakers).toContainText(WITHDRAWN_BY_CHLOE)
  await expect(speakers.getByRole('button', { name: `Withdraw ${SPEAKERS}` })).toHaveCount(0)
  await expect(
    page
      .getByRole('form', { name: 'Add equipment' })
      .getByRole('combobox', { name: 'Equipment type' })
      .getByRole('option', { name: new RegExp(`^${SPEAKERS}`) }),
  ).toHaveCount(1)

  // AC10: the organiser reads it, with nothing to withdraw.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await openSummit(page, ACCOUNTS.organiser2)
  await expect(item(page, SPEAKERS)).toContainText('Withdrawn')
  await expect(item(page, SPEAKERS)).toContainText(WITHDRAWN_BY_CHLOE)
  await expect(equipmentSection(page).getByRole('button', { name: /^Withdraw/ })).toHaveCount(0)
})

test('17.2 AC2/AC4: a pending item is withdrawn, not removed, and Technical Support see it under Withdrawn, read-only', async ({
  page,
}) => {
  await openSummit(page, ACCOUNTS.coordinator)
  const microphones = item(page, MICROPHONES)
  await expect(microphones).toContainText('Pending')
  await expect(microphones.getByRole('button', { name: `Remove ${MICROPHONES}` })).toHaveCount(0)

  await microphones.getByRole('button', { name: `Withdraw ${MICROPHONES}` }).click()
  const dialog = page.getByRole('dialog', { name: 'Withdraw this equipment?' })
  await dialog.getByRole('button', { name: 'Withdraw' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(microphones).toContainText('Withdrawn')

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)
  await page.getByRole('tab', { name: /^Withdrawn/ }).click()
  const card = page
    .getByRole('listitem')
    .filter({ hasText: SUMMIT })
    .filter({ hasText: MICROPHONES })
  await expect(card).toContainText('Withdrawn')
  await expect(card).toContainText('Chloe Coordinator')
  await expect(card.getByRole('button', { name: 'Accept' })).toHaveCount(0)
  await expect(card.getByRole('button', { name: 'Decline' })).toHaveCount(0)
})

test('17.2 AC5: Withdraw is not offered once the event is Awaiting Safety Check', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto(`/events/${EVENTS.harbourConcert}`)
  await expect(equipmentSection(page).getByRole('listitem').first()).toContainText(
    'Accepted (reserved)',
  )
  await expect(equipmentSection(page).getByRole('button', { name: /^Withdraw/ })).toHaveCount(0)
})

test('17.2 AC11: Technical Support accept an item while its Withdraw dialog is open, and the coordinator is shown it is now accepted', async ({
  page,
  browser,
}, testInfo) => {
  test.setTimeout(120_000)
  const name = uniqueName('Withdraw race')
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, name, 520)
  await page.goto(`/events/${eventId}`)
  await assignByLead(page)
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${eventId}`)
  const addForm = equipmentSection(page).getByRole('form', {
    name: 'Add equipment',
  })
  await addForm.getByLabel('Equipment type').selectOption('LAPTOP')
  await addForm.getByLabel('Quantity').fill('1')
  await addForm.getByRole('button', { name: 'Add item' }).click()
  await equipmentSection(page).getByRole('button', { name: 'Submit to Technical Support' }).click()
  const laptop = item(page, LAPTOP)
  await expect(laptop).toContainText('Pending')

  await laptop.getByRole('button', { name: `Withdraw ${LAPTOP}` }).click()
  const dialog = page.getByRole('dialog', { name: 'Withdraw this equipment?' })

  // Meanwhile, in another session, Technical Support accept it.
  const elsewhere = await browser.newContext({
    baseURL: testInfo.project.use.baseURL,
  })
  const tech = await elsewhere.newPage()
  await signIn(tech, ACCOUNTS.techSupport)
  await tech.goto(QUEUE_PATH)
  await tech
    .getByRole('listitem')
    .filter({ hasText: name })
    .getByRole('button', { name: 'Accept' })
    .click()
  const accept = tech.getByRole('dialog', { name: 'Accept this request?' })
  await accept.getByRole('button', { name: 'Accept' }).click()
  await expect(accept).not.toBeVisible()
  await elsewhere.close()

  await dialog.getByRole('button', { name: 'Withdraw' }).click()
  await expect(dialog).toContainText('This equipment item is now accepted')
  await expect(dialog.getByRole('button', { name: 'Withdraw' })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(laptop).toContainText('Accepted (reserved)')
})
