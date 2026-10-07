/**
 * Story 19.1 - fe: raise an event change request, and withdraw it.
 *
 * AC1 on an event in Planning the organiser picks a field, enters the new value and a reason,
 *     and submits; the request shows as Pending to the organiser and to the assigned coordinator.
 * AC2 the point of contact is updated directly from the same page.
 * AC4 the form will not submit without a reason (the client-side half; the server's refusal and
 *     every value rule are backend cases).
 * AC5 change requests are offered only on a Planning event: not before approval, not once
 *     Confirmed.
 * AC9 the organiser withdraws a pending request after confirming, and it reads as Withdrawn.
 *
 * Validation rules, refusals (401/403/404/409/422), the one-pending-per-field rule, the conflict
 * cases (AC8, AC10) and the notifications are backend cases:
 * backend/tests/change_requests/test_raise_change_request.py.
 *
 * Each test that raises a request does so on a fresh event it creates, submits and has approved
 * through the UI, rather than on a shared seed event: a Pending request blocks its field (AC6),
 * so a retried test, or a parallel one, would otherwise collide with a request left behind.
 */
import { expect, test, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  assignedCoordinator,
  createAndSubmitRequest,
  EVENTS,
  inFuture,
  signIn,
  uniqueName,
} from './support'

// Confirmed, Omar's (organiser 2) - only read here, never changed.
const CONFIRMED_DINNER = '33333333-0000-0000-0000-000000000013'
const REASON = 'The keynote speaker can only attend a day later.'

function changeRequests(page: Page) {
  return page.getByRole('region', { name: 'Change requests' })
}

/** A fresh event of the organiser's, approved by whichever coordinator it was assigned to, with
 *  the organiser signed back in on its page. Returns its id and that coordinator's account. */
async function approvedEvent(page: Page, label: string) {
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, uniqueName(label))
  await page.goto(`/events/${eventId}`)
  const { account } = await assignedCoordinator(page)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, account)
  await page.goto(`/events/${eventId}`)
  await page.getByRole('button', { name: 'Approve' }).click()
  await page
    .getByRole('dialog', { name: 'Approve this request?' })
    .getByRole('button', { name: 'Approve' })
    .click()
  await expect(page.getByText('Planning', { exact: true }).first()).toBeVisible()

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${eventId}`)
  return { eventId, coordinator: account }
}

async function openChangeForm(page: Page, field: string) {
  await changeRequests(page).getByRole('button', { name: 'Request a change' }).click()
  await changeRequests(page).getByLabel('What to change').selectOption({ label: field })
}

test('19.1 AC1: an organiser requests a new date and the coordinator sees it pending', async ({
  page,
}) => {
  // Three sign-ins (organiser, coordinator, organiser) and a fourth to look as the coordinator.
  test.setTimeout(90_000)
  const { eventId, coordinator } = await approvedEvent(page, 'Change date')

  await openChangeForm(page, 'Date and time')
  await changeRequests(page).getByLabel('New start').fill(inFuture(31, 9))
  await changeRequests(page).getByLabel('New end').fill(inFuture(31, 17))
  await changeRequests(page).getByLabel('Reason for the change').fill(REASON)
  await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()

  const raised = changeRequests(page).getByRole('listitem').filter({ hasText: 'Date and time' })
  await expect(raised).toContainText('Pending')
  await expect(raised).toContainText(REASON)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator)
  await page.goto(`/events/${eventId}`)
  const seen = changeRequests(page).getByRole('listitem').filter({ hasText: 'Date and time' })
  await expect(seen).toContainText('Pending')
  await expect(changeRequests(page).getByRole('button', { name: 'Request a change' })).toHaveCount(
    0,
  )
})

test('19.1 AC2: an organiser updates the point of contact on a planning event', async ({
  page,
}) => {
  test.setTimeout(60_000)
  await approvedEvent(page, 'Contact')
  const email = `events.${Date.now()}@acme.example`

  await page.getByRole('button', { name: 'Update point of contact' }).click()
  await page.getByLabel('Contact email').fill(email)
  await page.getByLabel('Contact phone number').fill('+65 6999 0000')
  await page.getByRole('button', { name: 'Save contact details' }).click()

  await expect(page.getByText(email)).toBeVisible()
  await expect(page.getByText('+65 6999 0000')).toBeVisible()
  await page.reload()
  await expect(page.getByText(email)).toBeVisible()
})

test('19.1 AC4: the change form will not submit without a reason', async ({ page }) => {
  test.setTimeout(60_000)
  await approvedEvent(page, 'No reason')
  let raiseCalls = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/change-requests')) raiseCalls += 1
  })

  await openChangeForm(page, 'Expected attendance')
  await changeRequests(page).getByLabel('New expected attendance').fill('150')
  await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()

  const reason = changeRequests(page).getByLabel('Reason for the change')
  await expect(reason).toBeFocused()
  await expect(reason).toHaveAttribute('aria-invalid', 'true')
  await expect(changeRequests(page).getByText('Enter a reason for the change.')).toBeVisible()
  expect(raiseCalls).toBe(0)
})

test('19.1 AC5: change requests are offered only on a planning event', async ({ page }) => {
  // Planning: offered. Olivia's Regional Sales Summit is only looked at here, never changed.
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.planning}`)
  await expect(page.getByRole('button', { name: 'Request a change' })).toBeVisible()

  // Under review: Olivia's submitted request goes through clarification instead.
  await page.goto(`/events/${EVENTS.submitted}`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Request a change' })).toHaveCount(0)

  // Confirmed: Omar's dinner takes no more change requests.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${CONFIRMED_DINNER}`)
  await expect(page.getByRole('heading', { name: 'Partner Appreciation Dinner' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Request a change' })).toHaveCount(0)
})

test('19.1 AC9: an organiser withdraws a pending change request', async ({ page }) => {
  test.setTimeout(60_000)
  await approvedEvent(page, 'Withdraw change')

  await openChangeForm(page, 'Expected attendance')
  await changeRequests(page).getByLabel('New expected attendance').fill('150')
  await changeRequests(page).getByLabel('Reason for the change').fill(REASON)
  await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()
  const raised = changeRequests(page)
    .getByRole('listitem')
    .filter({ hasText: 'Expected attendance' })
  await expect(raised).toContainText('Pending')

  await raised.getByRole('button', { name: 'Withdraw' }).click()
  await page
    .getByRole('dialog', { name: 'Withdraw this change request?' })
    .getByRole('button', { name: 'Withdraw' })
    .click()

  await expect(raised).toContainText('Withdrawn')
  await expect(raised.getByRole('button', { name: 'Withdraw' })).toHaveCount(0)
})

test('19.1 AC4: a point of contact problem clears as soon as it is fixed', async ({ page }) => {
  // Nothing is saved: Olivia's Regional Sales Summit is only looked at here, never changed.
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.planning}`)
  await page.getByRole('button', { name: 'Update point of contact' }).click()
  const email = page.getByLabel('Contact email')
  const phone = page.getByLabel('Contact phone number')

  await email.fill('not-an-email')
  await page.getByRole('button', { name: 'Save contact details' }).click()
  await expect(email).toHaveAttribute('aria-invalid', 'true')
  await expect(page.getByText('Enter an email address like name@example.com.')).toBeVisible()
  await expect(phone).not.toHaveAttribute('aria-invalid', 'true')

  // Fixed without pressing Save again: the message goes as soon as the address is valid.
  await email.fill('events@acme.example')
  await expect(page.getByText('Enter an email address like name@example.com.')).toHaveCount(0)
  await expect(email).not.toHaveAttribute('aria-invalid', 'true')
})

test('19.1 AC4: the reason message clears once a reason is typed', async ({ page }) => {
  // Nothing is sent: Olivia's Regional Sales Summit is only looked at here, never changed.
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.planning}`)
  await openChangeForm(page, 'Expected attendance')
  await changeRequests(page).getByLabel('New expected attendance').fill('250')
  await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()
  const reason = changeRequests(page).getByLabel('Reason for the change')
  await expect(changeRequests(page).getByText('Enter a reason for the change.')).toBeVisible()

  await reason.fill(REASON)
  await expect(changeRequests(page).getByText('Enter a reason for the change.')).toHaveCount(0)
  await expect(reason).not.toHaveAttribute('aria-invalid', 'true')
})

test('19.1 AC4: a repeated equipment type or a requirement under 1 person is not sent', async ({
  page,
}) => {
  // Nothing is sent: Olivia's Regional Sales Summit is only looked at here, never changed.
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.planning}`)
  let raiseCalls = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/change-requests')) raiseCalls += 1
  })
  const section = changeRequests(page)

  await openChangeForm(page, 'Equipment')
  const existingItems = await section.getByLabel(/^Item \d+ type$/).count()
  await section.getByRole('button', { name: 'Add equipment' }).click()
  await section.getByRole('button', { name: 'Add equipment' }).click()
  for (const position of [existingItems + 1, existingItems + 2]) {
    await section
      .getByLabel(`Item ${position} type`)
      .selectOption({ label: 'Wireless microphone' })
    await section.getByLabel(`Item ${position} quantity`).fill('1')
  }
  await section.getByLabel('Reason for the change').fill(REASON)
  await section.getByRole('button', { name: 'Send change request' }).click()
  await expect(
    section.getByText('Each equipment type can appear only once on a request.'),
  ).toBeVisible()

  await section.getByLabel('What to change').selectOption({ label: 'Venue requirements' })
  const existingRequirements = await section
    .getByLabel(/^Requirement \d+ number of people$/)
    .count()
  await section.getByRole('button', { name: 'Add a venue requirement' }).click()
  const added = existingRequirements + 1
  await section.getByLabel(`Requirement ${added} name`).fill('Breakout')
  await section.getByLabel(`Requirement ${added} number of people`).fill('0')
  await section.getByRole('button', { name: 'Send change request' }).click()
  await expect(
    section.getByText('Give every venue requirement a number of people, as a whole number from 1.'),
  ).toBeVisible()
  expect(raiseCalls).toBe(0)
})
