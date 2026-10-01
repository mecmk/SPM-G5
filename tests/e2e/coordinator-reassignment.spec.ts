/**
 * Story 5.2 - fe/be: reassign a coordinator-holding event to a different coordinator.
 *
 * AC3 the event page has a Reassign action with a list of eligible coordinators and a
 *     confirmation step; the assignment change takes effect immediately (the page shows the new
 *     coordinator without a reload).
 *
 * Boundary, permission and conflict detail (AC4, AC6, AC7) are backend cases, covered by
 * backend/tests/coordination/test_reassign_coordinator.py. This spec covers the flow a
 * coordinator actually clicks through.
 *
 * The event used here is a fresh one created and submitted through the UI, not an existing seed
 * row: story 5.1's round robin means a submission can land on either seeded coordinator, and
 * reassigning a *shared* seed event (used by several other specs for its bookings, equipment and
 * accessibility data) would leave it permanently changed for the rest of this parallel run (see
 * tests/CLAUDE.md on why specs must not mutate shared seed state). Whichever coordinator the
 * round robin lands on is discovered from the page itself, the same way a person would look.
 */
import { expect, test } from '@playwright/test'
import {
  ACCOUNTS,
  assignedCoordinator,
  createAndSubmitRequest,
  signIn,
  uniqueName,
} from './support'

test('5.2 AC3: a coordinator reassigns an event to another coordinator', async ({ page }) => {
  // Two full sign-in cycles (organiser, then the auto-assigned coordinator) genuinely take
  // longer than the default per-test budget - see bookings.spec.ts's AC3/AC4 test for the
  // same reasoning.
  test.setTimeout(60_000)

  const name = uniqueName('Reassign')
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, name)

  await page.goto(`/events/${eventId}`)
  const { account, other } = await assignedCoordinator(page)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, account)
  await page.goto(`/events/${eventId}`)

  await page.getByRole('button', { name: 'Reassign' }).click()
  await page.getByLabel('New coordinator').selectOption({ label: other.name })
  await page.getByRole('button', { name: 'Confirm reassignment' }).click()

  await expect(page.getByText(other.name)).toBeVisible()
})
