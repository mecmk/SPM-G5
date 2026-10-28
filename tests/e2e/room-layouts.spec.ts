/**
 * Story 8.6 - manage the room layouts venues can offer.
 * AC1 Venue Staff open a Room layouts page listing every layout with its name and description,
 *     the seven standard ones first.
 * AC2 a layout Venue Staff add is offered the next time a venue's form or the catalogue's layout
 *     filter opens.
 * AC3 a renamed layout shows its new name wherever it appears, such as on a venue's page.
 * AC4 Venue Staff delete a layout nothing uses, after confirming.
 * AC8 a layout in use cannot be deleted: the dialog says where it is used.
 * AC9 other staff open the page and see the list, without Add, Edit or Delete.
 * AC12 a layout deleted while another Venue Staff member is changing it: their save is refused,
 *      and their list refreshes.
 * The rules behind each refusal (AC5-AC7), the API's 401 and 403 (AC9), the request form's
 * choices (AC2) and the simultaneous saves (AC10, AC11) are backend cases:
 * backend/tests/venues/test_room_layouts.py.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, signIn, uniqueName, venueCard } from './support'

const ROOM_LAYOUTS = 'Room layouts'
const CATALOGUE_PATH = /\/venues$/

function mainNav(page: Page) {
  return page.getByRole('navigation', { name: 'Main' })
}

/** Open Room layouts from the sidebar, as a user would. */
async function openRoomLayouts(page: Page) {
  await mainNav(page).getByRole('link', { name: ROOM_LAYOUTS, exact: true }).click()
  await expect(page.getByRole('heading', { name: ROOM_LAYOUTS, level: 1 })).toBeVisible()
}

/** The page's list of layouts, named by the page heading. */
function layoutList(page: Page) {
  return page.getByRole('list', { name: ROOM_LAYOUTS })
}

/** The list entry of the layout called `name`. */
function layoutEntry(page: Page, name: string) {
  return layoutList(page)
    .getByRole('listitem')
    .filter({ has: page.getByRole('heading', { name, exact: true }) })
}

/** Add a layout from the Room layouts page and wait until it is listed. */
async function addLayout(page: Page, name: string, description?: string) {
  await page.getByRole('button', { name: 'Add layout' }).click()
  const dialog = page.getByRole('dialog', { name: 'Add a room layout' })
  await dialog.getByLabel('Name').fill(name)
  if (description !== undefined) await dialog.getByLabel('Description').fill(description)
  await dialog.getByRole('button', { name: 'Add layout' }).click()
  await expect(dialog).toBeHidden()
  await expect(layoutEntry(page, name)).toBeVisible()
}

test('8.6 AC1/AC2: a layout Venue Staff add is listed, and offered at once on the venue form and in the catalogue filter', async ({
  page,
}) => {
  const name = uniqueName('Cabaret')
  await signIn(page, ACCOUNTS.venueStaff)
  await openRoomLayouts(page)

  // AC1: the standard layouts come first, each with its description.
  await expect(layoutList(page).getByRole('heading').first()).toHaveText('Theatre')
  await expect(layoutEntry(page, 'Theatre')).toContainText(
    'Rows of chairs facing the front; highest capacity.',
  )

  await addLayout(page, name, 'Round tables facing a stage.')
  await expect(layoutEntry(page, name)).toContainText('Round tables facing a stage.')

  // AC2: the next venue form offers it...
  await page.goto('/venues/new')
  await expect(page.getByRole('checkbox', { name, exact: true })).toBeVisible()
  // ...and so does the catalogue's layout filter.
  await page.goto('/venues')
  const layoutFilter = page.getByRole('complementary', { name: 'Filters' }).getByLabel('Layout')
  await layoutFilter.selectOption({ label: name })
  await expect(layoutFilter).not.toHaveValue('')
})

test('8.6 AC3: a renamed layout shows its new name on the venue that offers it', async ({
  page,
}) => {
  const layout = uniqueName('Hollow square')
  const renamed = `${layout} renamed`
  const venue = uniqueName('Layout Room')
  await signIn(page, ACCOUNTS.venueStaff)
  await openRoomLayouts(page)
  await addLayout(page, layout)

  await page.goto('/venues/new')
  await page.getByLabel('Venue name').fill(venue)
  await page.getByLabel('Location').fill('Tower E, Level 2')
  await page.getByLabel('Maximum capacity').fill('45')
  await page.getByRole('checkbox', { name: layout, exact: true }).check()
  await page.getByRole('button', { name: 'Create venue' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)

  await openRoomLayouts(page)
  await layoutEntry(page, layout)
    .getByRole('button', { name: `Edit ${layout}` })
    .click()
  const dialog = page.getByRole('dialog', { name: `Edit ${layout}` })
  await dialog.getByLabel('Name').fill(renamed)
  await dialog.getByRole('button', { name: 'Save changes' }).click()
  await expect(dialog).toBeHidden()
  await expect(layoutEntry(page, renamed)).toBeVisible()

  await page.goto('/venues')
  await venueCard(page, venue).getByRole('link', { name: venue }).click()
  await expect(page.getByRole('region', { name: 'Capacity' })).toContainText(renamed)
})

test('8.6 AC4: Venue Staff delete a layout nothing uses, after confirming', async ({ page }) => {
  const name = uniqueName('Fishbowl')
  await signIn(page, ACCOUNTS.venueStaff)
  await openRoomLayouts(page)
  await addLayout(page, name)

  await layoutEntry(page, name)
    .getByRole('button', { name: `Delete ${name}` })
    .click()
  const dialog = page.getByRole('dialog', { name: `Delete ${name}?` })
  await dialog.getByRole('button', { name: 'Delete layout' }).click()

  await expect(dialog).toBeHidden()
  await expect(layoutEntry(page, name)).toHaveCount(0)
})

test('8.6 AC8: deleting a layout in use is refused, and the dialog says where it is used', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await openRoomLayouts(page)

  await layoutEntry(page, 'Theatre').getByRole('button', { name: 'Delete Theatre' }).click()
  const dialog = page.getByRole('dialog', { name: 'Delete Theatre?' })
  await dialog.getByRole('button', { name: 'Delete layout' }).click()

  await expect(dialog.getByRole('alert')).toHaveText(
    'You cannot delete "Theatre" because venues, venue requirements and booking requests use it. You can still rename it.',
  )
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(layoutEntry(page, 'Theatre')).toBeVisible()
})

test('8.6 AC9: an Event Coordinator sees the layouts but cannot change them', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openRoomLayouts(page)

  await expect(layoutEntry(page, 'Theatre')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add layout' })).toHaveCount(0)
  await expect(layoutList(page).getByRole('button')).toHaveCount(0)
})

test('8.6 AC12: a layout deleted while another Venue Staff member renames it is refused, and their list refreshes', async ({
  browser,
  page,
}) => {
  const name = uniqueName('Banquet rounds')
  await signIn(page, ACCOUNTS.venueStaff)
  await openRoomLayouts(page)
  await addLayout(page, name)
  await layoutEntry(page, name)
    .getByRole('button', { name: `Edit ${name}` })
    .click()
  const dialog = page.getByRole('dialog', { name: `Edit ${name}` })
  await dialog.getByLabel('Name').fill(`${name} renamed`)

  // Meanwhile another Venue Staff member deletes it.
  const elsewhere = await browser.newContext({ baseURL: new URL(page.url()).origin })
  const other = await elsewhere.newPage()
  await signIn(other, ACCOUNTS.venueStaff)
  await openRoomLayouts(other)
  await layoutEntry(other, name)
    .getByRole('button', { name: `Delete ${name}` })
    .click()
  await other
    .getByRole('dialog', { name: `Delete ${name}?` })
    .getByRole('button', { name: 'Delete layout' })
    .click()
  await expect(layoutEntry(other, name)).toHaveCount(0)
  await elsewhere.close()

  await dialog.getByRole('button', { name: 'Save changes' }).click()

  await expect(dialog.getByRole('alert')).toHaveText('This room layout no longer exists.')
  await expect(layoutEntry(page, name)).toHaveCount(0)
})
