/**
 * Story 5.1 - fe: the coordinator assigned to an event.
 *
 * AC4 the assigned coordinator's name is visible on the event: the event page's Assigned
 *     coordinator tile names them, with their email, to the organiser and to the coordinator.
 *
 * Who may be assigned, the record of who assigned it and when, what submission does about a
 * coordinator, and every refusal are backend cases: backend/tests/coordination/
 * test_coordinator_assignment.py and test_auto_assign_coordinator.py. Since story 5.4 (AC9) the
 * Event Coordinator Lead makes the assignment, so the request here is assigned from the Lead's
 * queue (assignByLead).
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, assignByLead, createAndSubmitRequest, signIn, uniqueName } from './support'

function coordinatorTile(page: Page) {
  return page.getByText('Assigned coordinator', { exact: true }).locator('..')
}

test('5.1 AC4: the event page names the assigned coordinator', async ({ page }) => {
  test.setTimeout(60_000)
  await signIn(page, ACCOUNTS.organiser)
  const name = uniqueName('Who runs it')
  const eventId = await createAndSubmitRequest(page, name)
  await page.goto(`/events/${eventId}`)

  const chloe = await assignByLead(page)

  // assignByLead leaves the organiser signed in on the request's page.
  await expect(coordinatorTile(page)).toContainText(chloe.name)
  await expect(coordinatorTile(page)).toContainText(chloe.account)
  await expect(coordinatorTile(page)).not.toContainText('Not yet assigned')

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, chloe.account)
  await page.goto(`/events/${eventId}`)
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
  await expect(coordinatorTile(page)).toContainText(chloe.name)
  await expect(coordinatorTile(page)).toContainText(chloe.account)
})
