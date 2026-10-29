/**
 * Story 19.1 - fe: raise an event change request, and withdraw it.
 *
 * AC1 on an event in Planning the organiser picks a field, enters the new value and a reason,
 *     and submits; the request shows as Pending to the organiser and to the assigned coordinator.
 * AC2 the point of contact is updated directly from the same page.
 * AC4 the form will not submit without a reason (the client-side half; the server's refusal and
 *     every value rule are backend cases).
 * AC11 (fix f19.1.1) change requests are offered on a Confirmed event too, saying that approving
 *     one sends the event back to Planning for a new safety check.
 * AC12 they are not offered before approval, while the event awaits its safety check (Q20), once
 *     it is completed or cancelled, or within 24 hours of its set-up time - the page says when
 *     they close, or that they have.
 * AC9 the organiser withdraws a pending request after confirming, and it reads as Withdrawn.
 * AC14 (f19.1.2) the attendance field says the lowest it can go and which venue requirement sets
 *     it - a waiting venue requirements change's, when lower.
 * AC16 (f19.1.2) a lower attendance shows the server's refusal, saying what to change first.
 * AC17 (f19.1.2) an attendance change the venue requirements do not allow yet says what it waits
 *     for, to the organiser and the coordinator: the waiting venue requirements change, or, when
 *     none would make room, what can be done.
 *
 * Validation rules, refusals (401/403/404/409/422), the one-pending-per-field rule, the conflict
 * cases (AC8, AC10, AC13) and the notifications are backend cases:
 * backend/tests/change_requests/test_raise_change_request.py.
 *
 * Each test that raises a request does so on a fresh event it creates, submits and has approved
 * through the UI, rather than on a shared seed event: a Pending request blocks its field (AC6),
 * so a retried test, or a parallel one, would otherwise collide with a request left behind.
 */
import { expect, test, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  approvedEvent,
  changeRequests,
  corsHeaders,
  EVENTS,
  expectNoSidewaysScroll,
  inFuture,
  MIN_TOUCH_TARGET,
  PHONE,
  signIn,
} from './support'

const REASON = 'The keynote speaker can only attend a day later.'
// Team decision on the review of #125 (19.1 AC12): change requests close 24 hours before set-up,
// and the page says when - or, when that can't be read (a stubbed failure), says so instead.
const CLOSE_NOTE = /^Change requests close 24 hours before set-up, on .+\.$/
const CLOSED_NOTE = 'Change requests for this event closed 24 hours before its set-up time.'
const WINDOW_FAILED = 'The cut-off could not be read.'
// f19.1.1 (19.1 AC11, 19.2 AC8): what the organiser is told when asking to change a Confirmed event.
const BACK_TO_PLANNING_NOTE =
  'If this change is approved, the event goes back to Planning and needs a new safety check before it is confirmed again.'

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

test('19.1 AC12: change requests are not offered before approval, while awaiting the safety check, or once completed or cancelled', async ({
  page,
}) => {
  // Every event here is only looked at, never changed.
  // Planning: offered. Olivia's Regional Sales Summit.
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.planning}`)
  await expect(page.getByRole('button', { name: 'Request a change' })).toBeVisible()

  // Under review: Olivia's submitted request goes through clarification instead.
  await page.goto(`/events/${EVENTS.submitted}`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Request a change' })).toHaveCount(0)

  // Completed: Olivia's New Year Town Hall still lists its change requests, and takes no new one.
  // (It is also long past its set-up, so the 24-hour rule hides the button too; the Cancelled line
  // below tests the status alone.)
  await page.goto(`/events/${EVENTS.completed}`)
  await expect(changeRequests(page)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Request a change' })).toHaveCount(0)

  // Awaiting its safety check: Omar's concert, until Q20 decides.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.harbourConcert}`)
  await expect(page.getByRole('heading', { name: 'Harbour Lights Concert' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Request a change' })).toHaveCount(0)

  // Cancelled: Omar's Charity Fun Run, still ahead (April 2027), so only its status hides it.
  await page.goto(`/events/${EVENTS.cancelledFunRun}`)
  await expect(changeRequests(page)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Request a change' })).toHaveCount(0)
})

test('19.1 AC12: change requests are offered until 24 hours before set-up, saying when they close', async ({
  page,
}) => {
  // Read only. Omar's dinner, Confirmed and months ahead, offers them, and says until when...
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.confirmed}`)
  await expect(page.getByRole('button', { name: 'Request a change' })).toBeVisible()
  await expect(changeRequests(page).getByText(CLOSE_NOTE)).toBeVisible()

  // ...his Autumn Book Swap, still Confirmed but over since 3 Oct (Q57), is long past its set-up:
  // none are offered, and it says why.
  await page.goto(`/events/${EVENTS.bookSwap}`)
  await expect(changeRequests(page).getByText(CLOSED_NOTE)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Request a change' })).toHaveCount(0)
})

test('19.1 AC12: when reading the cut-off fails, change requests are not offered and the page says so', async ({
  page,
}) => {
  // Read only. Omar's dinner offers them (the test above); here the cut-off can't be read.
  await page.route(
    (url) => url.pathname === `/events/${EVENTS.confirmed}/change-request-window`,
    (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: WINDOW_FAILED }),
        headers: corsHeaders(request),
      })
    },
  )
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.confirmed}`)

  await expect(changeRequests(page).getByRole('alert')).toHaveText(WINDOW_FAILED)
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

test('19.1 AC14/AC16: the attendance field says the lowest it can go, and why lower is refused', async ({
  page,
}) => {
  // Nothing is saved: the server refuses the request, so Olivia's Regional Sales Summit, for 220
  // with its Main venue for 220, is unchanged.
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.planning}`)
  await openChangeForm(page, 'Expected attendance')
  const attendance = changeRequests(page).getByLabel('New expected attendance')
  await expect(attendance).toHaveAccessibleDescription(
    'At least 220: Main venue needs room for 220 people.',
  )

  await attendance.fill('150')
  await changeRequests(page).getByLabel('Reason for the change').fill(REASON)
  await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()
  await expect(
    changeRequests(page).getByText(
      'The expected attendance cannot be lower than 220 while Main venue needs room for 220 people. Ask for a venue requirements change that lowers it first.',
    ),
  ).toBeVisible()
  await expect(
    changeRequests(page).getByRole('listitem').filter({ hasText: 'Expected attendance' }),
  ).toHaveCount(0)
})

test('19.1 AC14/AC17: with a venue requirements change waiting, the attendance field says its minimum and the request what it waits for', async ({
  page,
}) => {
  // Four sign-ins: three in approvedEvent, then the coordinator. The fresh event is for 60, its
  // Main venue for 60.
  test.setTimeout(120_000)
  const { eventId, coordinator } = await approvedEvent(page, 'Minimum with change')
  const section = changeRequests(page)
  await openChangeForm(page, 'Venue requirements')
  await section.getByLabel('Requirement 1 number of people').fill('40')
  await section.getByLabel('Reason for the change').fill(REASON)
  await section.getByRole('button', { name: 'Send change request' }).click()
  await expect(
    section.getByRole('listitem').filter({ hasText: 'Changes to venue requirements' }),
  ).toContainText('Pending')

  // CL-172 (4): the minimum is the one the server takes now - the waiting change's.
  await openChangeForm(page, 'Expected attendance')
  const attendance = section.getByLabel('New expected attendance')
  await expect(attendance).toHaveAccessibleDescription(
    'At least 40: with your venue requirements change, Main venue needs room for 40 people. That change is approved before this one.',
  )
  await attendance.fill('40')
  await section.getByLabel('Reason for the change').fill(REASON)
  await section.getByRole('button', { name: 'Send change request' }).click()
  const raised = section.getByRole('listitem').filter({ hasText: 'Changes to expected attendance' })
  await expect(raised).toContainText('Pending')
  await expect(raised).toContainText(
    'This waits for your venue requirements change to be approved first, since Main venue needs room for 60 people until then.',
  )

  // AC17's other half: with no venue requirements change waiting, nothing makes room.
  await section
    .getByRole('listitem')
    .filter({ hasText: 'Changes to venue requirements' })
    .getByRole('button', { name: 'Withdraw request' })
    .click()
  await page
    .getByRole('dialog', { name: 'Withdraw this change request?' })
    .getByRole('button', { name: 'Withdraw' })
    .click()
  await expect(raised).toContainText(
    'Main venue needs room for 60 people, so this cannot be approved yet. Ask for a venue requirements change that lowers it, or withdraw this request.',
  )
  // Fix f19.1.2: a venue requirements change that waits but does not lower it enough.
  await openChangeForm(page, 'Venue requirements')
  await section.getByLabel('Requirement 1 number of people').fill('50')
  await section.getByLabel('Reason for the change').fill(REASON)
  await section.getByRole('button', { name: 'Send change request' }).click()
  await expect(raised).toContainText(
    'Main venue needs room for 60 people, so this cannot be approved yet. Your venue requirements change does not lower it enough: withdraw it and ask for one that does, or withdraw this request.',
  )
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator)
  await page.goto(`/events/${eventId}`)
  await expect(raised).toContainText(
    'Main venue needs room for 60 people, so this cannot be approved until a venue requirements change lowers it.',
  )
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
    await section.getByLabel(`Item ${position} type`).selectOption({ label: 'Wireless microphone' })
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

test('19.1 AC11: change requests are offered on a confirmed event, with what approval means', async ({
  page,
}) => {
  // Read only: each form is opened and nothing is sent.
  // Planning: the form, with no note - approving there does not move the event back.
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.planning}`)
  await openChangeForm(page, 'Expected attendance')
  await expect(
    changeRequests(page).getByRole('button', { name: 'Send change request' }),
  ).toBeVisible()
  await expect(changeRequests(page).getByText(BACK_TO_PLANNING_NOTE)).toHaveCount(0)

  // Confirmed: Omar's dinner takes change requests now (Q39), and says what approving one means.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.confirmed}`)
  await openChangeForm(page, 'Expected attendance')
  await expect(
    changeRequests(page).getByRole('button', { name: 'Send change request' }),
  ).toBeVisible()
  await expect(changeRequests(page).getByText(BACK_TO_PLANNING_NOTE)).toBeVisible()
})

test('19.1 AC11: the change form on a confirmed event fits a phone', async ({ page }) => {
  // Read only: the form is opened on Omar's dinner and nothing is sent.
  await page.setViewportSize(PHONE)
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.confirmed}`)
  const request = changeRequests(page).getByRole('button', { name: 'Request a change' })
  await expect(request).toBeVisible()
  expect((await request.boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET)

  await openChangeForm(page, 'Expected attendance')
  const note = changeRequests(page).getByText(BACK_TO_PLANNING_NOTE)
  await expect(note).toBeVisible()
  const box = (await note.boundingBox())!
  expect(box.x + box.width).toBeLessThanOrEqual(PHONE.width)
  await expectNoSidewaysScroll(page)
})
