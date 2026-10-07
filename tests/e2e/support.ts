import { expect, type Page, type Request } from '@playwright/test'

/**
 * Seed accounts from backend/db/seed/020_sample_data.sql (mirrored in
 * backend/tests/support/seed.py). Every account shares one password.
 */
export const PASSWORD = 'Password123!'

export const ACCOUNTS = {
  organiser: 'organiser@acme.example',
  organiser2: 'organiser@nimbus.example',
  coordinator: 'coordinator@connectsphere.example',
  coordinator2: 'coordinator2@connectsphere.example',
  venueStaff: 'venue@connectsphere.example',
  techSupport: 'tech@connectsphere.example',
  attendee: 'attendee@example.com',
} as const

export const INVALID_CREDENTIALS_MESSAGE = 'Invalid email or password.'

/** Fixed event IDs from backend/db/seed/020_sample_data.sql (mirrored in
 *  backend/tests/support/seed.py::Events). */
export const EVENTS = {
  submitted: '33333333-0000-0000-0000-000000000002', // organiser: organiser, no decision yet
  approved: '33333333-0000-0000-0000-000000000003', // organiser: organiser2, approved by coordinator
  rejected: '33333333-0000-0000-0000-000000000004', // organiser: organiser2, rejected by coordinator2
  clarificationRequested: '33333333-0000-0000-0000-000000000006', // organiser: organiser
  draft: '33333333-0000-0000-0000-000000000001',
  planning: '33333333-0000-0000-0000-000000000012', // organiser: organiser, coordinator, Theatre only
  partnerBriefing: '33333333-0000-0000-0000-000000000018', // coordinator; 12.1's request is sent for it
  confirmed: '33333333-0000-0000-0000-000000000013', // organiser: organiser2, coordinator, Confirmed
  // Story 15.1, both Planning, organiser: organiser, coordinator, dated May 2027. Only the
  // equipment flow changes the workshop's equipment; nothing changes the showcase's.
  equipmentWorkshop: '33333333-0000-0000-0000-000000000019',
  equipmentShowcase: '33333333-0000-0000-0000-000000000020',
  // Story 15.2, Planning, organiser: organiser2, coordinator, dated June 2027. One equipment item
  // per Technical Support tab; nothing changes them.
  equipmentRoadshow: '33333333-0000-0000-0000-000000000021',
  // Story 16.1, Planning, organiser: organiser2, coordinator, dated December 2027. Six pending
  // equipment items; the 16.1 spec accepts and declines them.
  equipmentDecisions: '33333333-0000-0000-0000-000000000027',
} as const

/** Fill and submit the sign-in form, waiting for the backend to answer. */
export async function signIn(page: Page, email: string, password: string = PASSWORD) {
  if (!page.url().endsWith('/login')) await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/auth/login')),
    page.getByRole('button', { name: 'Sign in' }).click(),
  ])
}

export async function expectSignedIn(page: Page) {
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
}

/** A unique name, since specs share one database and run in parallel. */
export function uniqueName(label: string): string {
  return `E2E ${label} ${Date.now()}-${Math.floor(Math.random() * 1e6)}`
}

/** A `datetime-local` value (Singapore time) `days` from today, safely in the future. */
export function inFuture(days: number, hour = 9): string {
  const day = new Date(Date.now() + days * 24 * 60 * 60 * 1000)
  const date = day.toISOString().slice(0, 10)
  return `${date}T${String(hour).padStart(2, '0')}:00`
}

/** Create and submit a fresh, minimal request as the signed-in organiser; returns its id. */
export async function createAndSubmitRequest(page: Page, name: string): Promise<string> {
  await page.goto('/events/new')
  await page.getByLabel('Event name').fill(name)
  await page.getByLabel('Purpose').fill('Staff training')
  await page.getByLabel('Description').fill('One-day hands-on workshop.')
  await page.getByLabel('Proposed start').fill(inFuture(30, 9))
  await page.getByLabel('Proposed end').fill(inFuture(30, 17))
  await page.getByLabel('Expected attendance').fill('60')
  await page.getByLabel('Contact name').fill('Priya Nair')
  await page.getByLabel('Contact email').fill('priya.nair@example.com')
  await page.getByLabel('Contact phone number').fill('+65 9123 4567')
  await page.getByRole('checkbox', { name: 'No venue requirements' }).check()
  await page.getByRole('checkbox', { name: 'No accessibility needs' }).check()
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(/\/events\/[0-9a-f-]{36}\/edit$/)
  const match = page.url().match(/\/events\/([0-9a-f-]{36})\/edit$/)
  if (!match) throw new Error(`could not read the event id from ${page.url()}`)
  const eventId = match[1]

  await page.getByRole('button', { name: 'Submit request' }).click()
  await expect(page).toHaveURL(/\/events\/mine$/)
  return eventId
}

/** The two seeded Event Coordinators story 5.1's round robin can land a submission on. */
export const COORDINATORS = [
  { account: ACCOUNTS.coordinator, name: 'Chloe Coordinator' },
  { account: ACCOUNTS.coordinator2, name: 'Carl Coordinator' },
] as const

/**
 * Which seeded coordinator an event page shows as assigned, plus the other one - story 5.1's
 * round robin means a spec that submits a request cannot know in advance. Matched on the e-mail
 * the page prints beside the name, because the stat block it sits in carries no role and specs
 * must not select by CSS class (tests/CLAUDE.md).
 */
export async function assignedCoordinator(page: Page) {
  await expect(page.getByText('Assigned coordinator')).toBeVisible()
  for (const [index, coordinator] of COORDINATORS.entries()) {
    if (await page.getByText(coordinator.account, { exact: true }).isVisible()) {
      return { ...coordinator, other: COORDINATORS[1 - index] }
    }
  }
  throw new Error('no seeded coordinator shown as assigned on the event page')
}

/** The clarification thread on an event's detail page (stories 4.2, 4.6). */
export function clarificationsSection(page: Page) {
  return page.getByRole('region', { name: 'Clarifications', exact: true })
}

/** A venue card in the venue catalogue, matched by the venue's name. */
export function venueCard(page: Page, name: string) {
  return page.getByRole('article').filter({ has: page.getByRole('heading', { name }) })
}

/** Headers a stubbed `route.fulfill` needs, since the app and API run on different ports. */
export function corsHeaders(request: Request) {
  return {
    'access-control-allow-origin': request.headers()['origin'] ?? '*',
    'access-control-allow-credentials': 'true',
  }
}
