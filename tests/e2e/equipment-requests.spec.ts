/**
 * Story 15.1 - submit equipment requests for an event.
 *
 * 15.1 AC1 on the event page's Equipment requirements section (there is no separate equipment
 *          request page), the coordinator sees what the organiser asked for, adds more, and submits
 *          everything not yet sent to Technical Support, where it shows as Pending with who sent it.
 * 15.1 AC2 the coordinator edits an item's quantity and removes an item from the event page.
 * 15.1 AC3 the type picker shows how many of each type are available for the event's dates.
 * 15.1 AC4 a quantity of 0, or more than are available, is pointed out by the page itself before
 *          any request is sent. A purely client-side check has no backend call to assert against
 *          and no other runner, so it belongs here (AGENTS.md, tests/CLAUDE.md).
 * 15.1 AC6 a type already requested is not offered, and one with none available cannot be chosen.
 * 15.1 AC9 a Confirmed event, and the organiser's own view, show the equipment read-only.
 *
 * The holds, the availability arithmetic, the server's boundaries, the permissions, the date
 * re-check (AC8) and the races (AC10) are backend cases, in backend/tests/equipment/. This spec
 * covers what a coordinator actually clicks through.
 *
 * Seeded for this spec (backend/db/seed/020_sample_data.sql), both Planning, assigned to the
 * coordinator and dated May 2027, clear of every other spec's dates:
 * - EVENTS.equipmentWorkshop has the organiser's two portable projectors, not yet sent. Only the
 *   first test changes it.
 * - EVENTS.equipmentShowcase has one portable speaker set already sent, and every video camera out
 *   of service over its dates. Nothing here changes it, so its tests can run in parallel.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

const QUANTITY_PROBLEM = 'Enter a whole number from 1 to the number available.'

function equipmentSection(page: Page) {
  return page.getByRole('region', { name: 'Equipment requirements' })
}

function item(page: Page, typeName: string) {
  return equipmentSection(page).getByRole('listitem').filter({ hasText: typeName })
}

function addForm(page: Page) {
  return equipmentSection(page).getByRole('form', { name: 'Add equipment' })
}

test('15.1 AC1/AC2/AC3: the coordinator adds, edits and removes items, then submits them', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.equipmentWorkshop}`)

  // AC1: what the organiser asked for is already there, waiting to be sent.
  await expect(item(page, 'Portable projector')).toContainText('×2')
  await expect(item(page, 'Portable projector')).toContainText('Not yet sent')

  // AC1/AC3: add an item, choosing from types that show how many are available.
  const form = addForm(page)
  await expect(form.getByLabel('Equipment type')).toContainText('Wireless microphone (20 available)')
  await form.getByLabel('Equipment type').selectOption('WIRELESS_MIC')
  await form.getByLabel('Quantity').fill('4')
  await form.getByLabel('Technical notes').fill('Two lapel spares')
  await form.getByRole('button', { name: 'Add item' }).click()
  await expect(item(page, 'Wireless microphone')).toContainText('×4')
  await expect(item(page, 'Wireless microphone')).toContainText('Two lapel spares')
  await expect(item(page, 'Wireless microphone')).toContainText('Not yet sent')

  // AC2: change the organiser's quantity.
  await page.getByRole('button', { name: 'Edit Portable projector' }).click()
  const edit = equipmentSection(page).getByRole('form', { name: 'Edit Portable projector' })
  await edit.getByLabel('Quantity').fill('3')
  await edit.getByRole('button', { name: 'Save' }).click()
  await expect(item(page, 'Portable projector')).toContainText('×3')

  // AC2: remove an item, after confirming.
  await page.getByRole('button', { name: 'Remove Wireless microphone' }).click()
  const dialog = page.getByRole('dialog', { name: 'Remove this equipment item?' })
  await dialog.getByRole('button', { name: 'Remove' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(item(page, 'Wireless microphone')).toHaveCount(0)

  // AC1: send what is waiting; it is now with Technical Support, and nothing is left to send.
  await equipmentSection(page).getByRole('button', { name: 'Submit to Technical Support' }).click()
  await expect(item(page, 'Portable projector')).toContainText('Pending')
  await expect(item(page, 'Portable projector')).toContainText('Chloe Coordinator')
  await expect(
    equipmentSection(page).getByRole('button', { name: 'Submit to Technical Support' }),
  ).toHaveCount(0)
})

test('15.1 AC6: a type already requested is not offered, and one with none free cannot be chosen', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.equipmentShowcase}`)
  const types = addForm(page).getByLabel('Equipment type')

  // toBeDisabled() reads an <option> inside a <select> as enabled whatever its attribute, so the
  // attribute that stops the browser offering it is asserted directly.
  await expect(types.getByRole('option', { name: 'Video camera (0 available)' })).toHaveAttribute(
    'disabled',
  )
  await expect(types.getByRole('option', { name: /^Portable speaker set/ })).toHaveCount(0)
  await expect(types.getByRole('option', { name: /^Wireless microphone/ })).not.toHaveAttribute(
    'disabled',
  )
})

test('15.1 AC4: a quantity of 0, or more than are available, is pointed out before anything is sent', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.equipmentShowcase}`)
  const posted: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/equipment')) {
      posted.push(request.url())
    }
  })
  const form = addForm(page)
  await form.getByLabel('Equipment type').selectOption('LAPTOP')
  await expect(form.getByText("6 available for this event's dates")).toBeVisible()

  for (const quantity of ['0', '7']) {
    await form.getByLabel('Quantity').fill(quantity)
    await form.getByRole('button', { name: 'Add item' }).click()
    await expect(form.getByText(QUANTITY_PROBLEM)).toBeVisible()
  }

  expect(posted).toEqual([])
  await expect(item(page, 'Presentation laptop')).toHaveCount(0)
})

test('15.1 AC9: a confirmed event shows its equipment with nothing to change', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.confirmed}`)

  await expect(equipmentSection(page)).toBeVisible()
  await expect(addForm(page)).toHaveCount(0)
  await expect(
    equipmentSection(page).getByRole('button', { name: 'Submit to Technical Support' }),
  ).toHaveCount(0)
})

test('15.1 AC9: the organiser sees each item and its status, with nothing to change', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.equipmentShowcase}`)

  await expect(item(page, 'Portable speaker set')).toContainText('Pending')
  await expect(item(page, 'Portable speaker set').getByRole('button')).toHaveCount(0)
  await expect(addForm(page)).toHaveCount(0)
})
