import { expect, test } from '@playwright/test'

test('intentional failure for tooling verification', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByText('This text does not exist on the page')).toBeVisible()
})
