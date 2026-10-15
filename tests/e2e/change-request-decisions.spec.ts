/**
 * Story 19.2 - fe: review and decide event change requests (Phase 1).
 *
 * AC1 the assigned coordinator sees their events' pending change requests in one queue, each with
 *     the current and proposed value, the reason, who asked and when.
 * AC2 approving a change applies it: the event shows the new value and the request reads Approved.
 * AC3 rejecting takes a reason, leaves the event as it was, and the organiser reads the reason.
 * AC4 a blank or spaces-only rejection reason is not sent (the client-side half; the server's
 *     refusal is a backend case).
 *
 * Who may decide (AC6), duplicate, withdrawn and stale decisions (AC7), what may not be approved
 * until Phase 2 (AC5, AC8), the notifications and the audit record are backend cases:
 * backend/tests/change_requests/test_decide_change_request.py.
 *
 * Each test raises its own request on a fresh event (`approvedEvent`), since a pending request
 * blocks its field (19.1 AC6) and other specs share the database. Only an attendance change is
 * approvable in Phase 1, so that is the change every test asks for.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, approvedEvent, signIn } from './support'

const CHANGE_REASON = 'More people signed up than expected.'
const REJECTION_REASON = 'The workshop room cannot take more people.'
const QUEUE_PATH = '/change-requests/review'

function changeRequests(page: Page) {
  return page.getByRole('region', { name: 'Change requests' })
}

function queueEntry(page: Page, eventName: string) {
  return page
    .getByRole('list', { name: 'Pending change requests' })
    .getByRole('listitem')
    .filter({ hasText: eventName })
}

/** A fresh approved event on which the organiser has asked for 150 people instead of 60, with
 *  its coordinator signed in on the event's page. */
async function pendingAttendanceChange(page: Page, label: string) {
  const { eventId, name, coordinator } = await approvedEvent(page, label)
  await changeRequests(page).getByRole('button', { name: 'Request a change' }).click()
  await changeRequests(page)
    .getByLabel('What to change')
    .selectOption({ label: 'Expected attendance' })
  await changeRequests(page).getByLabel('New expected attendance').fill('150')
  await changeRequests(page).getByLabel('Reason for the change').fill(CHANGE_REASON)
  await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()
  await expect(changeRequests(page).getByRole('listitem')).toContainText('Pending')

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator)
  await page.goto(`/events/${eventId}`)
  return { eventId, name }
}

test('19.2 AC1: the coordinator sees a pending change in their queue with what was asked', async ({
  page,
}) => {
  test.setTimeout(90_000)
  const { name } = await pendingAttendanceChange(page, 'Queue change')

  await page.getByRole('link', { name: 'Change requests' }).first().click()
  await expect(page).toHaveURL(QUEUE_PATH)
  const entry = queueEntry(page, name)
  await expect(entry).toContainText('Expected attendance')
  await expect(entry).toContainText('Now: 60 people')
  await expect(entry).toContainText('Requested: 150 people')
  await expect(entry).toContainText(CHANGE_REASON)
  await expect(entry).toContainText('Olivia Organiser')
})

test('19.2 AC2: the coordinator approves an attendance change and the event takes it', async ({
  page,
}) => {
  test.setTimeout(90_000)
  const { eventId, name } = await pendingAttendanceChange(page, 'Approve change')
  await expect(page.getByText('60', { exact: true })).toBeVisible()

  await page.goto(QUEUE_PATH)
  await queueEntry(page, name).getByRole('button', { name: 'Approve' }).click()
  await page
    .getByRole('dialog', { name: 'Approve this change?' })
    .getByRole('button', { name: 'Approve' })
    .click()
  await expect(queueEntry(page, name)).toHaveCount(0)

  await page.goto(`/events/${eventId}`)
  await expect(page.getByText('150', { exact: true })).toBeVisible()
  const decided = changeRequests(page).getByRole('listitem')
  await expect(decided).toContainText('Approved')
  await expect(decided).toContainText('Chloe Coordinator')
})

test('19.2 AC3: the coordinator rejects a change with a reason the organiser then reads', async ({
  page,
}) => {
  test.setTimeout(90_000)
  const { eventId } = await pendingAttendanceChange(page, 'Reject change')

  const pending = changeRequests(page).getByRole('listitem')
  await pending.getByRole('button', { name: 'Reject' }).click()
  const dialog = page.getByRole('dialog', { name: 'Reject this change?' })
  await dialog.getByLabel('Reason for rejecting').fill(REJECTION_REASON)
  await dialog.getByRole('button', { name: 'Reject' }).click()

  await expect(pending).toContainText('Rejected')
  await expect(pending).toContainText(REJECTION_REASON)
  await expect(pending.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await expect(page.getByText('60', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${eventId}`)
  const seen = changeRequests(page).getByRole('listitem')
  await expect(seen).toContainText('Rejected')
  await expect(seen).toContainText(REJECTION_REASON)
  await expect(seen.getByRole('button', { name: 'Reject' })).toHaveCount(0)
})

test('19.2 AC4: a blank or spaces-only rejection reason is not sent', async ({ page }) => {
  test.setTimeout(90_000)
  await pendingAttendanceChange(page, 'Blank rejection')
  let rejectCalls = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/reject')) rejectCalls += 1
  })

  await changeRequests(page).getByRole('button', { name: 'Reject' }).click()
  const dialog = page.getByRole('dialog', { name: 'Reject this change?' })
  const reason = dialog.getByLabel('Reason for rejecting')
  for (const blank of ['', '   ']) {
    await reason.fill(blank)
    await dialog.getByRole('button', { name: 'Reject' }).click()
    await expect(dialog.getByRole('alert')).toHaveText('Enter a reason for rejecting this change.')
  }
  expect(rejectCalls).toBe(0)
  await expect(changeRequests(page).getByRole('listitem')).toContainText('Pending')
})
