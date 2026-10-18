/**
 * Story 19.2 - fe: review and decide event change requests.
 *
 * AC1 the assigned coordinator sees their events' pending change requests in one queue, each with
 *     the current and proposed value, the reason, who asked and when - and, under its other tabs,
 *     the requests already decided or withdrawn (team request, 16 Oct 2026).
 * AC2 approving a change applies it: the event shows the new value and the request reads Approved.
 * AC3 rejecting takes a reason, leaves the event as it was, and the organiser reads the reason.
 * AC4 a blank or spaces-only rejection reason is not sent (the client-side half; the server's
 *     refusal is a backend case).
 * AC5 approving a date change says, before it is applied, what it may release, and the event
 *     then has the new dates.
 * AC8 approving a change on an event awaiting its safety check warns, before it is applied, that
 *     the event goes back to Planning for a new safety check - and it does.
 *
 * Who may decide (AC6), duplicate, withdrawn and out-of-date decisions (AC7), which bookings and
 * holds are released (AC5), that Confirm then needs a new safety approval (AC8), the notifications
 * and the audit record are backend cases:
 * backend/tests/change_requests/test_decide_change_request.py.
 *
 * Each test raises its own request on a fresh event (`approvedEvent`), since a pending request
 * blocks its field (19.1 AC6) and other specs share the database. AC8 needs an event with every
 * arrangement secured, which a fresh one is not, so it has a seeded event of its own
 * (`EVENTS.designSprint`), moved on for good: that test is not retried.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, approvedEvent, changeRequests, EVENTS, inFuture, signIn } from './support'

const CHANGE_REASON = 'More people signed up than expected.'
const REJECTION_REASON = 'The workshop room cannot take more people.'
const QUEUE_PATH = '/change-requests/review'
const BACK_TO_PLANNING_WARNING =
  'The event goes back to Planning and needs a new safety check before it is confirmed again.'

/** A `datetime-local` value ("2026-11-18T09:00", Singapore time) as the event page shows its
 *  date: "Wed, 18 Nov 2026". */
function shownDate(inputValue: string): string {
  return new Date(`${inputValue}:00+08:00`).toLocaleDateString('en-SG', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Singapore',
  })
}

function queueEntry(page: Page, eventName: string, tab = 'Pending') {
  return page
    .getByRole('list', { name: `${tab} change requests` })
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
  await expect(entry).toContainText('Changes to expected attendance')
  await expect(entry.getByText('60 people', { exact: true })).toBeVisible()
  await expect(entry.getByText('150 people', { exact: true })).toBeVisible()
  await expect(entry).toContainText(CHANGE_REASON)
  await expect(entry).toContainText('Olivia Organiser')

  await entry.getByRole('link', { name: 'View event →' }).click()
  await page.getByRole('link', { name: '← Change requests' }).click()
  await expect(page).toHaveURL(QUEUE_PATH)
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
  await page.getByRole('tab', { name: /^Approved/ }).click()
  await expect(queueEntry(page, name, 'Approved')).toContainText('Approved by Chloe Coordinator')

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
  const { eventId, name } = await pendingAttendanceChange(page, 'Reject change')

  const pending = changeRequests(page).getByRole('listitem')
  await pending.getByRole('button', { name: 'Reject' }).click()
  const dialog = page.getByRole('dialog', { name: 'Reject this change?' })
  await dialog.getByLabel('Reason for rejecting').fill(REJECTION_REASON)
  await dialog.getByRole('button', { name: 'Reject' }).click()

  await expect(pending).toContainText('Rejected')
  await expect(pending).toContainText(REJECTION_REASON)
  await expect(pending.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await expect(page.getByText('60', { exact: true })).toBeVisible()

  await page.goto(QUEUE_PATH)
  await page.getByRole('tab', { name: /^Rejected/ }).click()
  await expect(queueEntry(page, name, 'Rejected')).toContainText(REJECTION_REASON)

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

test('19.2 AC5: approving a date change says what it may release, then applies it', async ({
  page,
}) => {
  test.setTimeout(90_000)
  const { eventId, coordinator } = await approvedEvent(page, 'Date change')
  const newStart = inFuture(31, 9)
  await changeRequests(page).getByRole('button', { name: 'Request a change' }).click()
  await changeRequests(page).getByLabel('What to change').selectOption({ label: 'Date and time' })
  await changeRequests(page).getByLabel('New start').fill(newStart)
  await changeRequests(page).getByLabel('New end').fill(inFuture(31, 17))
  await changeRequests(page).getByLabel('Reason for the change').fill(CHANGE_REASON)
  await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()
  await expect(changeRequests(page).getByRole('listitem')).toContainText('Pending')

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator)
  await page.goto(`/events/${eventId}`)
  await changeRequests(page).getByRole('button', { name: 'Approve' }).click()
  const dialog = page.getByRole('dialog', { name: 'Approve this change?' })
  await expect(dialog).toContainText(
    'Venue bookings that no longer cover the new dates are released',
  )
  await dialog.getByRole('button', { name: 'Approve' }).click()

  await expect(changeRequests(page).getByRole('listitem')).toContainText('Approved')
  await expect(page.getByText(/Organised by/).first()).toContainText(`${shownDate(newStart)} · `)
})

test.describe('on a seeded event', () => {
  test.describe.configure({ retries: 0 })

  test('19.2 AC8: approving a change on an event awaiting its safety check sends it back to Planning', async ({
    page,
  }) => {
    test.setTimeout(90_000)
    await signIn(page, ACCOUNTS.organiser)
    await page.goto(`/events/${EVENTS.designSprint}`)
    await changeRequests(page).getByRole('button', { name: 'Request a change' }).click()
    await changeRequests(page)
      .getByLabel('What to change')
      .selectOption({ label: 'Expected attendance' })
    await changeRequests(page).getByLabel('New expected attendance').fill('70')
    await changeRequests(page).getByLabel('Reason for the change').fill(CHANGE_REASON)
    await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()
    await expect(changeRequests(page).getByRole('listitem')).toContainText('Pending')

    await page.getByRole('button', { name: 'Sign out' }).click()
    await signIn(page, ACCOUNTS.coordinator)
    await page.goto(`/events/${EVENTS.designSprint}`)
    const status = (label: string) =>
      page.getByRole('main').getByText(label, { exact: true }).first()
    await page
      .getByRole('region', { name: 'Safety review', exact: true })
      .getByRole('button', { name: 'Request safety review' })
      .click()
    await expect(status('Awaiting safety check')).toBeVisible()

    await changeRequests(page).getByRole('button', { name: 'Approve' }).click()
    const dialog = page.getByRole('dialog', { name: 'Approve this change?' })
    await expect(dialog).toContainText(BACK_TO_PLANNING_WARNING)
    await dialog.getByRole('button', { name: 'Approve' }).click()

    await expect(changeRequests(page).getByRole('listitem')).toContainText('Approved')
    await expect(status('Planning')).toBeVisible()
  })
})
