import { expect, test } from '@playwright/test'

test('placeholder page loads and reports backend status', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'ConnectSphere' })).toBeVisible()
  await expect(page.getByText('Backend status:')).toBeVisible()
  await expect(page.getByText('ok', { exact: true })).toBeVisible()
})
