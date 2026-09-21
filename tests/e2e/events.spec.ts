/**
 * Story 7.1 - fe: display full event details.
 * AC1 the detail view shows core event details, venue requirements, accessibility requirements,
 *     equipment requirements, status and assigned coordinator.
 * AC2 users see the detail view only for events they are related to.
 * AC3 fields the user's role may not edit are shown read-only rather than hidden.
 * Which event a signed-in user may open is enforced by story 2.1 AC8's `GET /events/{id}`:
 * backend/tests/events/test_event_request_details.py already covers the 403/404 refusals this
 * relies on (an attendee, another organiser's request, a draft that is not the viewer's own).
 * This spec covers the flows a user actually clicks through, plus the one refusal that is purely
 * a frontend rendering concern: what a blocked direct URL shows.
 */
import { expect, test } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

test('7.1 AC1: a coordinator opens an event from the review queue and sees its full details', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')

  await page.getByRole('link', { name: 'Data Literacy Workshop' }).click()

  await expect(
    page.getByRole('heading', { name: 'Data Literacy Workshop', level: 1 }),
  ).toBeVisible()
  await expect(page.getByText('Submitted')).toBeVisible()
  await expect(page.getByText('Classroom')).toBeVisible()
  await expect(page.getByText('Projector & screen')).toBeVisible()
  await expect(page.getByText('Wi-Fi')).toBeVisible()
  await expect(page.getByText('No accessibility needs recorded.')).toBeVisible()
  await expect(page.getByText('Portable projector')).toBeVisible()
  await expect(page.getByText('Room already has one; spare requested')).toBeVisible()
  await expect(page.locator('img').first()).toHaveAttribute('src', '/images/events/cat.jpg')
})

test('7.1: the back link returns to wherever the event was opened from', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')

  await page.getByRole('link', { name: 'Data Literacy Workshop' }).click()
  await expect(
    page.getByRole('heading', { name: 'Data Literacy Workshop', level: 1 }),
  ).toBeVisible()

  await page.getByRole('link', { name: '← Events inbox' }).click()
  await expect(page.getByRole('heading', { name: 'Events inbox', level: 1 })).toBeVisible()
})

test('7.1 AC1: the organiser who owns the event sees its venue, accessibility and equipment requirements', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.approved}`)

  await expect(
    page.getByRole('heading', { name: 'Nimbus Developer Conference', level: 1 }),
  ).toBeVisible()
  await expect(page.getByText('Approved')).toBeVisible()
  await expect(page.getByText('350')).toBeVisible()
  await expect(page.getByText('Chloe Coordinator')).toBeVisible()

  await expect(page.getByText('Theatre')).toBeVisible()
  await expect(page.getByText('Sound system')).toBeVisible()
  await expect(page.getByText('Stage')).toBeVisible()

  await expect(page.getByText('Wheelchair access')).toBeVisible()
  await expect(page.getByText('Two wheelchair users expected')).toBeVisible()
  await expect(page.getByText('Hearing loop')).toBeVisible()

  await expect(page.getByText('Wireless microphone')).toBeVisible()
  await expect(page.getByText('Two per breakout room')).toBeVisible()
  await expect(page.getByText('Presentation laptop')).toBeVisible()

  // AC3: this page only ever renders fields, it never edits them.
  await expect(page.getByRole('textbox')).toHaveCount(0)
  await expect(page.getByRole('combobox')).toHaveCount(0)
  await expect(page.getByRole('checkbox')).toHaveCount(0)
})

test('7.1 AC1: a draft with no dates, attendance or coordinator shows clear empty states', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.draft}`)

  await expect(
    page.getByRole('heading', { name: 'Q1 Sales Kick-off (draft)', level: 1 }),
  ).toBeVisible()
  await expect(page.getByText('Not yet scheduled · Organised by Olivia Organiser')).toBeVisible()
  await expect(page.getByText('Not yet assigned')).toBeVisible()
  // AC1: no recorded image falls back to the placeholder rather than a broken or empty image.
  await expect(page.locator('img')).toHaveCount(0)
})

test("7.1 AC2: an organiser cannot open another organiser's event by direct URL", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.approved}`)

  await expect(page.getByRole('alert')).toContainText('Event not found.')
})
