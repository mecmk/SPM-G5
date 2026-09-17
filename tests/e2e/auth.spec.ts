/**
 * Story 1.1 - fe/be: implement user login and logout.
 * AC1 valid credentials start an authenticated session.
 * AC2 invalid credentials are refused with a message that does not reveal whether the account
 *     exists.
 * AC4 after sign-in the user is redirected to the appropriate authenticated page.
 * AC5 after sign-out the session is invalidated.
 * AC3 (credentials stored hashed) is backend-only: backend/tests/auth/test_passwords.py.
 */
import { expect, test } from '@playwright/test'
import { ACCOUNTS, INVALID_CREDENTIALS_MESSAGE, PASSWORD, expectSignedIn, signIn } from './support'

test('1.1 AC1: valid credentials sign the user in', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)

  await expectSignedIn(page)
  await expect(page.getByText('Vera Venue', { exact: true })).toBeVisible()
})

test('1.1 AC1: the session survives a page reload', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await expectSignedIn(page)

  await page.reload()

  await expectSignedIn(page)
})

test('1.1 AC2: a wrong password shows a generic message and stays on sign-in', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff, 'not-the-password')

  await expect(page.getByRole('alert')).toHaveText(INVALID_CREDENTIALS_MESSAGE)
  await expect(page).toHaveURL(/\/login$/)
})

test('1.1 AC2: an unknown email shows exactly the same message', async ({ page }) => {
  await signIn(page, 'nobody@nowhere.example', PASSWORD)

  await expect(page.getByRole('alert')).toHaveText(INVALID_CREDENTIALS_MESSAGE)
})

test('1.1 AC2: email and password are required before anything is sent', async ({ page }) => {
  await page.goto('/login')
  let loginCalls = 0
  page.on('request', (request) => {
    if (request.url().endsWith('/auth/login')) loginCalls += 1
  })

  await page.getByRole('button', { name: 'Sign in' }).click()

  const emailMissing = await page
    .getByLabel('Email')
    .evaluate((input: HTMLInputElement) => input.validity.valueMissing)
  expect(emailMissing).toBe(true)
  expect(loginCalls).toBe(0)
  await expect(page).toHaveURL(/\/login$/)
})

test('1.1 AC4: after sign-in the user lands on their main page', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)

  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { name: /Welcome, Olivia Organiser/ })).toBeVisible()
})

test('1.1 AC4: a signed-out visitor is sent to sign in, then back where they started', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)

  await signIn(page, ACCOUNTS.organiser)

  await expect(page).toHaveURL(/\/$/)
  await expectSignedIn(page)
})

test('1.1 AC5: signing out ends the session', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await expectSignedIn(page)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login$/)

  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
})
