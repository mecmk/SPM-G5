/**
 * Story 7.4 - fe: an Event Organiser sees what was changed on their event and by whom.
 * AC1 each saved change shows the field, its old and new values, who made it with their role, and
 *     when.
 * AC3 an event with no changes shows "No changes yet"; a long value is shortened, with a way to
 *     expand it.
 * What is recorded for each save, the order, change request references, who may read the history
 * and the internal-notes filter (AC1, AC2, AC4-AC7) are covered by
 * backend/tests/events/test_event_change_history.py.
 *
 * The test raises its own request through the organiser's form, so parallel specs never edit the
 * same event, and has the Lead assign it to Chloe before she corrects it.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, assignByLead, createAndSubmitRequest, signIn, uniqueName } from './support'

const LONG_DESCRIPTION =
  'Corrected: a two-part hands-on workshop, the morning on reading charts and the afternoon on ' +
  'building them, with a short break for lunch in between and a recap at the end of the day.'

function changeHistory(page: Page) {
  return page.getByRole('region', { name: 'Change history' })
}

test('7.4 AC1/AC3: the organiser sees no changes yet, then the coordinator’s correction with who made it', async ({
  page,
}) => {
  test.setTimeout(90_000)
  const name = uniqueName('History')
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, name)
  await page.goto(`/events/${eventId}`)
  const chloe = await assignByLead(page)

  await expect(changeHistory(page).getByText('No changes yet')).toBeVisible()

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, chloe.account)
  await page.goto(`/events/${eventId}`)
  await page.getByRole('link', { name: 'Edit event' }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
  await page.getByLabel('Description').fill(LONG_DESCRIPTION)
  await page.getByLabel('Expected attendance').fill('75')
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes('/review-details') &&
        response.request().method() === 'PATCH' &&
        response.ok(),
    ),
    page.getByRole('button', { name: 'Save changes' }).click(),
  ])

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${eventId}`)
  const history = changeHistory(page)
  await expect(history.getByText(`${chloe.name} (Event Coordinator)`)).toBeVisible()
  const attendance = history.getByRole('listitem').filter({ hasText: 'Expected attendance' })
  await expect(attendance).toContainText('60')
  await expect(attendance).toContainText('75')

  const description = history.getByRole('listitem').filter({ hasText: 'Description' })
  await expect(description.getByText(LONG_DESCRIPTION)).toHaveCount(0)
  await description.getByRole('button', { name: 'Show more' }).click()
  await expect(description.getByText(LONG_DESCRIPTION)).toBeVisible()
  await expect(description.getByRole('button', { name: 'Show less' })).toBeVisible()
})
