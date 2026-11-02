/**
 * Story 19.4 - view my change requests across all my events, as an organiser.
 *
 * AC1 the "Change requests" page lists the organiser's change requests, each with its event's
 *     name, what it changes, when it was raised and its status.
 * AC3 each row opens that event's page.
 * AC4 another role opening the page's address sees the "not permitted" page there (the API's 403,
 *     and that only the organiser's own requests come back, are backend cases).
 * AC5 with no requests, the page says so and points to My events.
 *
 * Every status being listed (AC1), the order (AC2) and the scoping to the organiser's own events
 * (AC4) are backend cases: backend/tests/change_requests/test_my_change_requests.py. The page keeps
 * the order the backend sends. No conflict case: the page only reads.
 *
 * Other specs raise change requests as the same organiser, so the list is read by event name,
 * never by its length. The seed does not promise an organiser with none, so AC5 stubs the list
 * call: the empty answer itself is a backend case.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, approvedEvent, changeRequests, corsHeaders, inFuture, signIn } from './support'

const PAGE_PATH = '/change-requests'
const LIST_PATH = '/change-requests/mine'
const REASON = 'The venue can only take us a day later.'

/** The list call answers with no requests. */
async function stubNoRequests(page: Page) {
  await page.route(
    (url) => url.pathname === LIST_PATH,
    (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: '[]',
        headers: corsHeaders(request),
      })
    },
  )
}

test('19.4 AC1/AC3: an organiser sees a raised request on the page and opens its event', async ({
  page,
}) => {
  // Three sign-ins (organiser, coordinator, organiser) to reach an approved event.
  test.setTimeout(90_000)
  const { eventId, name } = await approvedEvent(page, 'My changes')
  await changeRequests(page).getByRole('button', { name: 'Request a change' }).click()
  await changeRequests(page).getByLabel('What to change').selectOption({ label: 'Date and time' })
  await changeRequests(page).getByLabel('New start').fill(inFuture(31, 9))
  await changeRequests(page).getByLabel('New end').fill(inFuture(31, 17))
  await changeRequests(page).getByLabel('Reason for the change').fill(REASON)
  await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()
  await expect(
    changeRequests(page).getByRole('listitem').filter({ hasText: 'Date and time' }),
  ).toContainText('Pending')

  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'Change requests', exact: true })
    .click()

  await expect(page).toHaveURL(new RegExp(`${PAGE_PATH}$`))
  const row = page.getByRole('listitem').filter({ hasText: name })
  await expect(row).toContainText('Changes to date and time')
  await expect(row).toContainText('Pending')
  await expect(row).toContainText(/Requested at.+\d{4}/)

  // The status tabs list only their own status.
  await page.getByRole('tab', { name: /^Withdrawn/ }).click()
  await expect(row).toHaveCount(0)
  await page.getByRole('tab', { name: /^Pending/ }).click()
  await expect(row).toContainText('Pending')

  await row.getByRole('link', { name }).click()

  await expect(page).toHaveURL(new RegExp(`/events/${eventId}$`))
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()

  // The event leads back to this page, and a click anywhere on the row opens it too.
  await page.getByRole('main').getByRole('link', { name: 'Change requests' }).click()
  await expect(page).toHaveURL(new RegExp(`${PAGE_PATH}$`))
  await row.getByText('Requested at').click()
  await expect(page).toHaveURL(new RegExp(`/events/${eventId}$`))
})

test('19.4 AC4: a coordinator opening the page sees Not permitted at the same address', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)

  await page.goto(PAGE_PATH)

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`${PAGE_PATH}$`))
})

test('19.4 AC5: with no change requests the page says so and points to My events', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await stubNoRequests(page)

  await page.goto(PAGE_PATH)

  await expect(page.getByText('You have not raised any change requests yet.')).toBeVisible()
  await page.getByRole('main').getByRole('link', { name: 'My events' }).click()

  await expect(page).toHaveURL(/\/events\/mine$/)
})
