/**
 * Story 4.2 - fe/be: the assigned coordinator asks the organiser for clarification.
 *
 * 4.2 AC1 writing a message and sending it shows it in the thread with its author and its time,
 *         and the event's status sentence shows the request is awaiting the organiser.
 * 4.2 AC3 the message is mandatory: a blank one is refused by the page itself, before any request
 *         is sent. A purely client-side check has no backend call to assert against and no other
 *         runner, so it belongs here (AGENTS.md, tests/CLAUDE.md).
 * 4.2 AC4 the coordinator can still send a follow-up question once the request already awaits a
 *         response to an earlier one - nothing moves the event back to Under Review (story 4.3's
 *         response leaves the status alone), so a second round starts from there.
 * 4.2 AC7 a double-click on Send sends once: the button is disabled while the request is in
 *         flight, so one message survives a reload, not two.
 *
 * Boundary, permission and conflict detail are backend cases, covered by
 * backend/tests/events/test_request_clarification.py - including the server-side half of AC7, two
 * overlapping requests. This spec covers the round trip a coordinator actually clicks through.
 *
 * All four criteria are one test over one event deliberately: creating and submitting a request
 * through the UI and then signing in as whichever coordinator story 5.1's round robin picked
 * costs two full sign-in cycles, and a case per criterion would pay that four times over.
 *
 * The event used here is a fresh one created and submitted through the UI, not an existing seed
 * row: story 5.1's round robin means a submission can land on either seeded coordinator, and this
 * action moves the event to CLARIFICATION_REQUESTED - reusing EVENTS.clarificationRequested (whose
 * fixed two-message thread e2e/decision-history.spec.ts asserts exactly) or one of
 * review-queue.spec.ts's shared UNDER_REVIEW events would leave it permanently changed for the
 * rest of this parallel run (see tests/CLAUDE.md on why specs must not mutate shared seed state).
 */
import { expect, test } from '@playwright/test'
import {
  ACCOUNTS,
  assignedCoordinator,
  clarificationsSection,
  createAndSubmitRequest,
  signIn,
  uniqueName,
} from './support'

const AWAITING_RESPONSE_SENTENCE =
  'A decision has not been made yet. The coordinator has asked for clarification - see the messages below.'

test('4.2 AC1/AC3/AC4/AC7: the coordinator asks, asks again, and a double-click sends once', async ({
  page,
}) => {
  // Two full sign-in cycles (organiser, then the auto-assigned coordinator) genuinely take
  // longer than the default per-test budget - see coordinator-reassignment.spec.ts for the same
  // reasoning with two.
  test.setTimeout(90_000)

  const name = uniqueName('Clarify')
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, name)

  await page.goto(`/events/${eventId}`)
  const coordinator = await assignedCoordinator(page)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator.account)
  await page.goto(`/events/${eventId}`)

  const askSection = page.getByRole('region', { name: 'Ask the organiser' })
  const send = askSection.getByRole('button', {
    name: 'Send clarification request',
  })

  // 4.2 AC3: a blank message is refused by the page, and nothing is sent.
  await send.click()
  await expect(askSection.getByRole('alert')).toHaveText('Enter a message to send.')
  await expect(clarificationsSection(page).getByRole('listitem')).toHaveCount(0)

  // 4.2 AC1: the message appears with its author and its time, and the status sentence follows.
  const question = 'Could you confirm the expected headcount?'
  await page.getByLabel('Message').fill(question)
  await send.click()

  const first = clarificationsSection(page).getByRole('listitem').first()
  await expect(first).toContainText(question)
  await expect(first).toContainText(coordinator.name)
  await expect(first).toContainText('Clarification requested')
  await expect(first).toContainText(/\d{1,2}:\d{2}/)
  await expect(page.getByText(AWAITING_RESPONSE_SENTENCE)).toBeVisible()

  // 4.2 AC4: several rounds are allowed. Nothing moves the event back to Under Review, so the
  // coordinator has to be able to ask again directly from CLARIFICATION_REQUESTED.
  await expect(send).toBeVisible()
  await page.getByLabel('Message').fill('And which room layout do you need?')
  await send.click()

  const followUp = clarificationsSection(page).getByRole('listitem').last()
  await expect(followUp).toContainText(coordinator.name)
  await expect(followUp).toContainText('And which room layout do you need?')

  // 4.2 AC7: a double-click sends once - Send is disabled while the request is in flight, so the
  // second click never reaches the handler. The reload is what proves it: only one row was written.
  const third = 'And will you need a projector?'
  await page.getByLabel('Message').fill(third)
  // Two presses at one point near the left edge, which the shorter "Sending…" label still
  // covers. dblclick() presses the centre, which the label change moves off.
  await send.scrollIntoViewIfNeeded()
  const box = await send.boundingBox()
  if (!box) throw new Error('Send is not on screen')
  const x = box.x + 5
  const y = box.y + box.height / 2
  await page.mouse.click(x, y)
  await page.mouse.click(x, y)
  await expect(clarificationsSection(page).getByRole('listitem')).toHaveCount(3)

  await page.reload()
  await expect(
    clarificationsSection(page).getByRole('listitem').filter({ hasText: third }),
  ).toHaveCount(1)
})
