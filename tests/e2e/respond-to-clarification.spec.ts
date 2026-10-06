/**
 * Story 4.3 - fe/be: the organiser responds to a clarification request.
 *
 * 4.3 AC1 while clarification is outstanding, the organiser sees the coordinator's message and can
 *         add a response.
 * 4.3 AC2 the clarification and the responses stay visible and read-only - to the organiser and to
 *         the coordinator, who gets no response form of their own.
 * 4.3 AC4 the message is mandatory: a blank one is refused by the page itself, before any request
 *         is sent. A purely client-side check has no backend call to assert against and no other
 *         runner, so it belongs here (AGENTS.md, tests/CLAUDE.md).
 * 4.3 AC6 several responses are allowed, and each is kept in the thread in order.
 *
 * Boundary, permission and conflict detail, the coordinator's notification and the transaction
 * are backend cases, covered by backend/tests/events/test_respond_to_clarification.py.
 *
 * One test over one fresh event, for the same reason as request-clarification.spec.ts: the
 * request has to be created, submitted and asked about through the UI, by whichever coordinator
 * story 5.1's round robin picked, and every criterion here needs that same set-up. The seeded
 * EVENTS.clarificationRequested is not used: its fixed thread is asserted exactly by
 * decision-history.spec.ts, and responding would add to it for the rest of the parallel run.
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

test('4.3 AC1/AC2/AC4/AC6: the organiser answers a clarification request, twice', async ({
  page,
}) => {
  // Four sign-ins (organiser, coordinator, organiser, coordinator) - past the default budget.
  test.setTimeout(90_000)

  const name = uniqueName('Respond')
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, name)
  await page.goto(`/events/${eventId}`)
  const coordinator = await assignedCoordinator(page)

  // The coordinator asks a question.
  const question = 'Could you confirm the expected headcount?'
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator.account)
  await page.goto(`/events/${eventId}`)
  await page.getByLabel('Message').fill(question)
  await page.getByRole('button', { name: 'Send clarification request' }).click()
  await expect(clarificationsSection(page).getByRole('listitem')).toHaveCount(1)

  // 4.3 AC1: the organiser sees the question and a form to answer it.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${eventId}`)
  await expect(clarificationsSection(page).getByRole('listitem').first()).toContainText(question)

  const respondSection = page.getByRole('region', { name: 'Respond to the coordinator' })
  const send = respondSection.getByRole('button', { name: 'Send response' })

  // 4.3 AC4: a blank response is refused by the page, and nothing is sent.
  await send.click()
  await expect(respondSection.getByRole('alert')).toHaveText('Enter a message to send.')
  await expect(clarificationsSection(page).getByRole('listitem')).toHaveCount(1)

  // 4.3 AC1/AC6: two responses, each appended after the question, in order.
  const first = 'About 120 people.'
  const second = 'Correction: closer to 130.'
  await respondSection.getByLabel('Message').fill(first)
  await send.click()
  await expect(clarificationsSection(page).getByRole('listitem')).toHaveCount(2)
  await respondSection.getByLabel('Message').fill(second)
  await send.click()

  const thread = clarificationsSection(page).getByRole('listitem')
  await expect(thread).toHaveCount(3)
  await expect(thread.nth(1)).toContainText(first)
  await expect(thread.nth(1)).toContainText('Response')
  await expect(thread.nth(1)).toContainText('Olivia Organiser')
  await expect(thread.nth(2)).toContainText(second)

  // 4.3 AC2: the thread itself is read-only - nothing in it to edit or remove an entry with.
  await expect(clarificationsSection(page).getByRole('button')).toHaveCount(0)
  await expect(clarificationsSection(page).getByRole('textbox')).toHaveCount(0)

  // 4.3 AC2: the coordinator sees the responses, in order, and has no response form.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator.account)
  await page.goto(`/events/${eventId}`)
  const seen = clarificationsSection(page).getByRole('listitem')
  await expect(seen).toHaveCount(3)
  await expect(seen.nth(0)).toContainText(question)
  await expect(seen.nth(1)).toContainText(first)
  await expect(seen.nth(2)).toContainText(second)
  await expect(page.getByRole('region', { name: 'Respond to the coordinator' })).toHaveCount(0)
})
