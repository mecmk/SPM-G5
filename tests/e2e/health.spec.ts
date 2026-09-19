import { expect, test } from '@playwright/test'

test('sign-in page loads and reports that the backend is reachable', async ({ page }) => {
  await page.goto('/')

  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByText('Backend status:')).toBeVisible()
  await expect(page.getByText('ok', { exact: true })).toBeVisible()
})
