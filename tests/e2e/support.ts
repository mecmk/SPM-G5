import { expect, type Page } from '@playwright/test'

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

/** A row in a venue table (Manage venues), matched by name. */
export function venueRow(page: Page, name: string) {
  return page.getByRole('row', { name: new RegExp(name) })
}

/** Fixed event IDs from backend/db/seed/020_sample_data.sql (mirrored in backend/tests/support/seed.py::Events). */
export const EVENTS = {
  draft: '33333333-0000-0000-0000-000000000001',
  approved: '33333333-0000-0000-0000-000000000003',
} as const
