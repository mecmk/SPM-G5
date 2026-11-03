import { expect, test } from '@playwright/test'

/**
 * Smoke test: the sign-in page loads. Chore c16 took the developer tools off it, so it asserts
 * they are gone. The runner serves a development build, where the sample accounts were shown.
 */
test('sign-in page loads with no developer tools on it', async ({ page }) => {
  await page.goto('/')

  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByRole('form', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByText('Sample accounts for local testing')).toHaveCount(0)
  await expect(page.getByText('Backend status:')).toHaveCount(0)
})
