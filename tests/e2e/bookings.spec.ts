/**
 * Story 13.1 - fe/be: display the venue staff booking requests queue.
 * AC1 the queue lists all pending requests for venues the staff member is responsible for.
 * AC2 each entry shows event name, requested venue, period, expected attendance and stated
 *     requirements.
 * AC3 decided requests do not appear in the pending queue.
 * Entry shape across several rows, malformed input and 401/403 refusals are backend cases:
 * backend/tests/bookings/test_list_bookings.py.
 */
import { expect, test } from '@playwright/test'
import { ACCOUNTS, signIn } from './support'

test('13.1 AC1/AC2: venue staff see a pending request with its summary', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  await expect(page.getByRole('heading', { name: 'Booking Requests' })).toBeVisible()
  const card = page.getByRole('listitem').filter({ hasText: 'Nimbus Developer Conference' })
  await expect(card).toContainText('Seminar Room 2.1')
  await expect(card).toContainText('60')
  await expect(card).toContainText('Breakout track B.')
})

test('13.1 AC2: the request detail page shows the event, booking and requirements', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  const card = page.getByRole('listitem').filter({ hasText: 'Nimbus Developer Conference' })
  await card.getByRole('link', { name: 'View details' }).click()

  await expect(page.getByRole('heading', { name: 'Nimbus Developer Conference' })).toBeVisible()
  await expect(page.getByText('Omar Organiser')).toBeVisible()
  await expect(page.getByText('Annual customer conference')).toBeVisible()
  await expect(page.getByText('Seminar Room 2.1')).toBeVisible()
  await expect(page.getByText('Classroom')).toBeVisible()
  await expect(page.getByText('Breakout track B.')).toBeVisible()
  await expect(page.getByText('Projector & screen')).toBeVisible()
  await expect(page.getByText('Wheelchair access')).toBeVisible()
})

test('13.1 AC1: the queue shows requests across different events, venues and dates', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  await expect(
    page.getByRole('listitem').filter({ hasText: 'Nimbus Developer Conference' }),
  ).toBeVisible()
  await expect(
    page.getByRole('listitem').filter({ hasText: 'Annual Wellness Summit' }),
  ).toBeVisible()
  await expect(
    page.getByRole('listitem').filter({ hasText: 'Product Roadmap Townhall' }),
  ).toBeVisible()
})

test('13.1 AC3: an approved booking does not appear in the pending queue', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  await expect(page.getByRole('heading', { name: 'Booking Requests' })).toBeVisible()
  // The APPROVED Nimbus/Grand Hall booking must not appear, even though a different, PENDING
  // request (Product Roadmap Townhall) also books Grand Hall.
  const decidedCard = page
    .getByRole('listitem')
    .filter({ hasText: 'Nimbus Developer Conference' })
    .filter({ hasText: 'Grand Hall' })
  await expect(decidedCard).toHaveCount(0)
})

test('13.1: a coordinator cannot open the booking requests queue', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venue-staff/booking-requests')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
})
