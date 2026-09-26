/**
 * Story 1.1 - fe/be: implement user login and logout.
 * AC1 valid credentials start an authenticated session.
 * AC2 invalid credentials are refused with a message that does not reveal whether the account
 *     exists.
 * AC4 after sign-in the user is redirected to the appropriate authenticated page.
 * AC5 after sign-out the session is invalidated.
 * AC6 repeated failed sign-ins lock sign-in for that email for a while, and the page counts down
 *     the minutes left (bug f1.1.2). The countdown never reads a clock time, so these cases move the
 *     browser's clock across leap days and daylight-saving changes to prove it does not care.
 * AC3 (credentials stored hashed) is backend-only: backend/tests/auth/test_passwords.py.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, INVALID_CREDENTIALS_MESSAGE, PASSWORD, expectSignedIn, signIn } from './support'

/** LOGIN_MAX_FAILURES in backend/app/config.py: this many failures lock sign-in (story 1.1 AC6). */
const MAX_FAILED_SIGN_INS = 5
const LOCK_ENDED_MESSAGE = 'You can try signing in again now.'

/**
 * A fresh unknown email: specs run in parallel on one database, so locking a seed account would
 * break every other spec that signs in with it. Failures count per email typed.
 */
function lockoutEmail(): string {
  return `lockout-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@nowhere.example`
}

/** Fail sign-in until the email locks; the last failure itself shows the lock. */
async function lockSignIn(page: Page, email: string) {
  for (let attempt = 1; attempt < MAX_FAILED_SIGN_INS; attempt += 1) {
    await signIn(page, email, 'not-the-password')
    await expect(page.getByRole('alert')).toHaveText(INVALID_CREDENTIALS_MESSAGE)
  }
  await signIn(page, email, 'not-the-password')
  await expect(page.getByRole('timer')).toBeVisible()
}

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

test('1.1 AC6: the 5th failed sign-in in a row shows the lock and the minutes left', async ({
  page,
}) => {
  const email = lockoutEmail()
  for (let attempt = 1; attempt < MAX_FAILED_SIGN_INS; attempt += 1) {
    await signIn(page, email, 'not-the-password')
    await expect(page.getByRole('alert')).toHaveText(INVALID_CREDENTIALS_MESSAGE)
  }

  await signIn(page, email, 'not-the-password')

  await expect(page.getByRole('alert')).toHaveText(
    'Too many failed sign-in attempts. Try again in 15 min.',
  )
  await expect(page).toHaveURL(/\/login$/)
})

test('1.1 AC6: the minutes left count down, then say sign-in is open again', async ({ page }) => {
  await page.clock.install()
  const email = lockoutEmail()
  await lockSignIn(page, email)
  await expect(page.getByRole('timer')).toHaveText('15 min')

  await page.clock.fastForward('05:00')
  await expect(page.getByRole('timer')).toHaveText('10 min')

  // Whole minutes, rounded up: the last minute reads "1 min", never "0 min".
  await page.clock.fastForward('09:30')
  await expect(page.getByRole('timer')).toHaveText('1 min')

  await page.clock.fastForward('00:30')
  await expect(page.getByRole('alert')).toHaveText(LOCK_ENDED_MESSAGE)

  // Only the browser's clock moved; the server still holds the lock and says so again.
  await signIn(page, email)
  await expect(page.getByRole('timer')).toHaveText('15 min')
})

test('1.1 AC6: a computer that sleeps still counts the time it slept', async ({ page }) => {
  await page.clock.install()
  await lockSignIn(page, lockoutEmail())

  // Asleep, the date moves on while the page's timers stand still.
  const now = await page.evaluate(() => Date.now())
  await page.clock.setSystemTime(now + 10 * 60_000)

  await expect(page.getByRole('timer')).toHaveText('5 min')
})

test('1.1 AC6: setting the computer clock back does not add time', async ({ page }) => {
  await page.clock.install()
  await lockSignIn(page, lockoutEmail())

  const now = await page.evaluate(() => Date.now())
  await page.clock.setSystemTime(now - 60 * 60_000)
  await page.clock.fastForward('15:00')

  await expect(page.getByRole('alert')).toHaveText(LOCK_ENDED_MESSAGE)
})

/** Moments where a wall-clock countdown would go wrong; the time left must not notice them. */
const CALENDAR_EDGES = [
  { name: 'into a leap day', timezoneId: 'Asia/Singapore', time: '2028-02-28T23:55:00+08:00' },
  { name: 'over 28 Feb 2100, not a leap year', timezoneId: 'UTC', time: '2100-02-28T23:55:00Z' },
  { name: 'over New Year', timezoneId: 'Asia/Singapore', time: '2026-12-31T23:55:00+08:00' },
  {
    name: 'while New York clocks go back',
    timezoneId: 'America/New_York',
    time: '2026-11-01T01:55:00-04:00',
  },
  {
    name: 'while London clocks go forward',
    timezoneId: 'Europe/London',
    time: '2027-03-28T00:55:00Z',
  },
]

for (const edge of CALENDAR_EDGES) {
  test.describe(edge.name, () => {
    test.use({ timezoneId: edge.timezoneId })

    test(`1.1 AC6: the time left is exact ${edge.name}`, async ({ page }) => {
      await page.clock.install({ time: edge.time })
      await lockSignIn(page, lockoutEmail())

      await page.clock.fastForward('10:00')
      await expect(page.getByRole('timer')).toHaveText('5 min')

      await page.clock.fastForward('05:00')
      await expect(page.getByRole('alert')).toHaveText(LOCK_ENDED_MESSAGE)
    })
  })
}

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

test('b1.1.1: opening sign-in with a live session shows the check, not the form', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await expectSignedIn(page)

  // Hold /auth/me in flight so the state before it answers can be asserted at all.
  await page.route('**/auth/me', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500))
    await route.continue()
  })
  await page.goto('/login')

  await expect(page.getByRole('status')).toHaveText(/Checking your session/)
  await expect(page.getByLabel('Email')).toHaveCount(0)

  await page.unroute('**/auth/me')
  await expect(page).toHaveURL(/\/$/)
})
