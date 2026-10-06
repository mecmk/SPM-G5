/**
 * Story 8.3 - fe/be: create and update venue records.
 * AC1 a venue can be created with at least a name, location and capacity.
 * AC2 existing venue characteristics can be edited and saved.
 * AC3 capacity accepts positive whole numbers only (checked in the browser before sending).
 * AC4 only Venue Staff can create or edit venue records.
 * Beyond those ACs this spec also covers delete (Venue Staff have full CRUD), search and a
 * capacity filter, and that every save appears in the notification centre.
 *
 * Story 8.3 AC5-AC8 (bug f8.3.2): a venue's pictures.
 * AC5 Venue Staff add pictures by choosing files or dragging them onto the form, preview them,
 *     arrange them (carrying one across the others, or with its arrows) and remove any of them;
 *     they are saved with the venue's details, in that order.
 * AC6 the record shows them as a gallery, the first also in its banner, and each opens a
 *     carousel; the catalogue card shows the first.
 * AC7 JPEG, PNG or WebP, at most 5 MB each, at most 10 a venue: the form checks each chosen file
 *     on its own and names each one it refuses, before sending anything.
 * AC8 a picture the server refuses leaves the venue saved, and its edit page says why.
 * The server's own refusals, the files, the order's rules, AC9's permissions and AC10's
 * simultaneous changes are backend cases: backend/tests/venues/test_venue_pictures.py.
 *
 * Story 8.1 AC12 (f8.1.1): Venue Staff manage venues from the venue catalogue,
 * the page coordinators browse - New venue, Edit and Delete on each venue, and Show withdrawn
 * venues, for venues:manage holders only. The separate Manage venues page is gone and its old
 * address opens the catalogue. The manage page's name search and capacity filter live on in the
 * catalogue's "Name or location" box and capacity range.
 * Refusals and conflicts (401, 403, 409 in use, 422) are backend cases:
 * backend/tests/venues/test_venue_records.py.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, signIn, uniqueName, venueCard } from './support'

const CATALOGUE_PATH = /\/venues$/
const EDIT_PATH = /\/venues\/[0-9a-f-]{36}\/edit$/
const MAX_PICTURE_BYTES = 5 * 1024 * 1024
const PREVIEW_NAME = /^Picture \d+ preview$/
/** The smallest valid PNG: one transparent pixel. */
const PNG_BYTES = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64',
)

function mainNav(page: Page) {
  return page.getByRole('navigation', { name: 'Main' })
}

function pictureFile(name: string, buffer: Buffer = PNG_BYTES) {
  return { name, mimeType: 'image/png', buffer }
}

/** Open the new-venue form with the required details filled in. */
async function startNewVenue(page: Page, name: string) {
  await page.goto('/venues/new')
  await expect(page.getByRole('heading', { name: 'New venue', level: 1 })).toBeVisible()
  await page.getByLabel('Venue name').fill(name)
  await page.getByLabel('Location').fill('Tower E, Level 2')
  await page.getByLabel('Maximum capacity').fill('45')
}

/** Choose pictures the way the file picker does. */
async function choosePictures(page: Page, ...files: ReturnType<typeof pictureFile>[]) {
  await page.getByLabel('Choose pictures').setInputFiles(files)
}

/** A picture that is on screen and has actually loaded. */
async function expectLoaded(picture: Locator) {
  await expect(picture).toBeVisible()
  await expect
    .poll(() => picture.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
}

async function createVenue(page: Page, name: string, capacity = '45') {
  await page.goto('/venues')
  await page.getByRole('link', { name: 'New venue' }).click()
  await page.getByLabel('Venue name').fill(name)
  await page.getByLabel('Location').fill('Tower E, Level 2')
  await page.getByLabel('Maximum capacity').fill(capacity)
  await page.getByRole('button', { name: 'Create venue' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)
}

test('8.3 AC1/AC2: venue staff create a venue, then edit it', async ({ page }) => {
  const name = `E2E Room ${Date.now()}`
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues')

  await page.getByRole('link', { name: 'New venue' }).click()
  await page.getByLabel('Venue name').fill(name)
  await page.getByLabel('Location').fill('Tower E, Level 2')
  await page.getByLabel('Maximum capacity').fill('45')
  await page.getByRole('checkbox', { name: 'Wi-Fi', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Theatre', exact: true }).check()
  await page.getByRole('button', { name: 'Create venue' }).click()

  await expect(page).toHaveURL(CATALOGUE_PATH)
  await expect(venueCard(page, name)).toContainText('45')

  await venueCard(page, name).getByRole('link', { name: 'Edit' }).click()
  await expect(page.getByRole('heading', { name: `Edit ${name}` })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'Wi-Fi', exact: true })).toBeChecked()
  await page.getByLabel('Maximum capacity').fill('60')
  await page.getByRole('button', { name: 'Save changes' }).click()

  await expect(page).toHaveURL(CATALOGUE_PATH)
  await expect(venueCard(page, name)).toContainText('60')
})

test('8.3 AC3: capacity must be a positive whole number before anything is sent', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/new')
  let createCalls = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/venues')) createCalls += 1
  })
  await page.getByLabel('Venue name').fill('Capacity check room')
  await page.getByLabel('Location').fill('Nowhere')

  for (const value of ['0', '-3', '12.5']) {
    await page.getByLabel('Maximum capacity').fill(value)
    await page.getByRole('button', { name: 'Create venue' }).click()
    await expect(page.getByRole('alert')).toContainText('positive whole number')
  }
  expect(createCalls).toBe(0)
})

test('8.3 AC1: a duplicate venue name is refused with the reason', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/new')
  await page.getByLabel('Venue name').fill('Grand Hall')
  await page.getByLabel('Location').fill('Anywhere')
  await page.getByLabel('Maximum capacity').fill('10')
  await page.getByRole('button', { name: 'Create venue' }).click()

  await expect(page.getByRole('main').getByRole('alert')).toContainText('already exists')
  await expect(page).toHaveURL(/\/venues\/new$/)
})

test('8.3: every save appears in the notification centre', async ({ page }) => {
  const name = `E2E Notify ${Date.now()}`
  await signIn(page, ACCOUNTS.venueStaff)

  await createVenue(page, name)

  await expect(page.getByRole('status').filter({ hasText: 'Venue created' })).toBeVisible()
  await page.getByRole('button', { name: /^Notifications/ }).click()
  const panel = page.getByRole('region', { name: 'Notifications' })
  await expect(panel.getByText(`${name} was added to the catalogue.`)).toBeVisible()
})

test('8.3 AC4: an event coordinator cannot open venue management', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)

  await page.goto('/venues/new')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
  await expect(page.getByLabel('Venue name')).toHaveCount(0)

  // The old Manage venues address is still behind venues:manage, so it does not redirect them.
  await page.goto('/venues/manage')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
  await expect(page).toHaveURL(/\/venues\/manage$/)
})

test('8.3: a link to the new-venue form survives signing in', async ({ page }) => {
  await page.goto('/venues/new')
  await expect(page).toHaveURL(/\/login$/)

  await signIn(page, ACCOUNTS.venueStaff)

  await expect(page).toHaveURL(/\/venues\/new$/)
  await expect(page.getByRole('heading', { name: 'New venue' })).toBeVisible()
})

test('8.1 AC12: Venue Staff add and edit venues from the catalogue', async ({ page }) => {
  const name = `E2E Catalogue ${Date.now()}`
  await signIn(page, ACCOUNTS.venueStaff)

  await expect(mainNav(page).getByRole('link', { name: 'Manage venues' })).toHaveCount(0)
  await mainNav(page).getByRole('link', { name: 'Venue catalogue', exact: true }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)
  await expect(page.getByRole('heading', { name: 'Venue catalogue', level: 1 })).toBeVisible()
  await expect(page.getByText('Keep the venue records accurate.', { exact: false })).toBeVisible()

  await page.getByRole('link', { name: 'New venue' }).click()
  await expect(page.getByRole('heading', { name: 'New venue', level: 1 })).toBeVisible()
  // Backing out of the form returns to the catalogue.
  await page.getByRole('link', { name: '← Venue catalogue' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)

  await page.getByRole('link', { name: 'New venue' }).click()
  await page.getByLabel('Venue name').fill(name)
  await page.getByLabel('Location').fill('Tower E, Level 3')
  await page.getByLabel('Maximum capacity').fill('30')
  await page.getByRole('button', { name: 'Create venue' }).click()

  await expect(page).toHaveURL(CATALOGUE_PATH)
  const card = venueCard(page, name)
  await expect(card).toContainText('Tower E, Level 3')
  await expect(card).toContainText('30')

  await card.getByRole('link', { name: 'Edit', exact: true }).click()
  await expect(page.getByRole('heading', { name: `Edit ${name}` })).toBeVisible()
  await page.getByRole('link', { name: 'Cancel' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)

  await card.getByRole('link', { name: 'Edit', exact: true }).click()
  // Wait for the form: until it opens, "Location" also matches the catalogue's search box.
  await expect(page.getByRole('heading', { name: `Edit ${name}` })).toBeVisible()
  await page.getByLabel('Location').fill('Tower F, Level 5')
  await page.getByRole('button', { name: 'Save changes' }).click()

  await expect(page).toHaveURL(CATALOGUE_PATH)
  await expect(card).toContainText('Tower F, Level 5')
})

test('8.1 AC12: Venue Staff delete a venue from the catalogue', async ({ page }) => {
  const name = `E2E Delete ${Date.now()}`
  await signIn(page, ACCOUNTS.venueStaff)
  await createVenue(page, name)

  await venueCard(page, name).getByRole('button', { name: 'Delete', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: `Delete ${name}?` })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Delete venue' }).click()

  await expect(dialog).toHaveCount(0)
  await expect(venueCard(page, name)).toHaveCount(0)
  await expect(page).toHaveURL(CATALOGUE_PATH)
})

test('8.1 AC12: a venue with bookings is not deleted, and the dialog says why', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues')

  await venueCard(page, 'Grand Hall').getByRole('button', { name: 'Delete', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Delete Grand Hall?' })
  await dialog.getByRole('button', { name: 'Delete venue' }).click()

  await expect(dialog.getByRole('alert')).toContainText('cannot delete a venue that has bookings')
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(venueCard(page, 'Grand Hall')).toBeVisible()
})

test('8.1 AC12: withdrawn venues can be shown, marked', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues')
  const showWithdrawn = page.getByRole('checkbox', { name: 'Show withdrawn venues' })
  await expect(showWithdrawn).not.toBeChecked()
  await expect(venueCard(page, 'Grand Hall')).toBeVisible()
  await expect(venueCard(page, 'Old Annex Room')).toHaveCount(0)

  await showWithdrawn.check()

  await expect(
    venueCard(page, 'Old Annex Room').getByText('Withdrawn', { exact: true }),
  ).toBeVisible()
  await expect(venueCard(page, 'Grand Hall').getByText('Withdrawn', { exact: true })).toHaveCount(0)

  await showWithdrawn.uncheck()

  await expect(venueCard(page, 'Old Annex Room')).toHaveCount(0)
  await expect(venueCard(page, 'Grand Hall')).toBeVisible()
})

test('8.1 AC12: the catalogue keeps the manage page’s name search and capacity range', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues')
  await expect(venueCard(page, 'Grand Hall')).toBeVisible()

  // Name or location, ignoring case: "seminar" is a name, "tOWER b" a location.
  await page.getByLabel('Name or location').fill('seminar')
  await expect(venueCard(page, 'Seminar Room 2.1')).toBeVisible()
  await expect(venueCard(page, 'Grand Hall')).toHaveCount(0)

  await page.getByLabel('Name or location').fill('tOWER b')
  await expect(venueCard(page, 'Boardroom 3.4')).toBeVisible()
  await expect(venueCard(page, 'Exhibition Foyer')).toBeVisible()
  await expect(venueCard(page, 'Seminar Room 2.1')).toHaveCount(0)

  // The capacity range includes both ends: Exhibition Foyer holds exactly 250.
  await page.getByLabel('Name or location').fill('')
  await page.getByLabel('Capacity from').fill('250')
  await page.getByLabel('Capacity to').fill('250')
  await expect(venueCard(page, 'Exhibition Foyer')).toBeVisible()
  await expect(venueCard(page, 'Grand Hall')).toHaveCount(0)
  await expect(venueCard(page, 'Boardroom 3.4')).toHaveCount(0)
})

test('8.1 AC12: the old Manage venues address opens the catalogue', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)

  await page.goto('/venues/manage')

  await expect(page).toHaveURL(CATALOGUE_PATH)
  await expect(page.getByRole('heading', { name: 'Venue catalogue', level: 1 })).toBeVisible()
  await expect(page.getByRole('link', { name: 'New venue' })).toBeVisible()
})

test('8.1 AC12: a venue deleted elsewhere cannot be deleted again, and the list reloads', async ({
  page,
}) => {
  const name = `E2E Gone ${Date.now()}`
  await signIn(page, ACCOUNTS.venueStaff)
  await createVenue(page, name)
  await expect(venueCard(page, name)).toBeVisible()

  // A second tab in the same session deletes it first; tests/CLAUDE.md forbids calling the API.
  const otherTab = await page.context().newPage()
  await otherTab.goto('/venues')
  await venueCard(otherTab, name).getByRole('button', { name: 'Delete', exact: true }).click()
  await otherTab.getByRole('button', { name: 'Delete venue' }).click()
  await expect(venueCard(otherTab, name)).toHaveCount(0)
  await otherTab.close()

  await venueCard(page, name).getByRole('button', { name: 'Delete', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: `Delete ${name}?` })
  await dialog.getByRole('button', { name: 'Delete venue' }).click()

  await expect(dialog.getByRole('alert')).toContainText('Venue not found.')
  await expect(venueCard(page, name)).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(venueCard(page, 'Grand Hall')).toBeVisible()
})

for (const { role, email } of [
  { role: 'a coordinator', email: ACCOUNTS.coordinator },
  { role: 'Technical Support', email: ACCOUNTS.techSupport },
]) {
  test(`8.1 AC12: ${role} browses the catalogue without the manage controls`, async ({ page }) => {
    await signIn(page, email)
    await page.goto('/venues')
    const grandHall = venueCard(page, 'Grand Hall')
    await expect(grandHall).toBeVisible()

    await expect(page.getByText('Venues currently in service.', { exact: false })).toBeVisible()
    await expect(page.getByRole('link', { name: 'New venue' })).toHaveCount(0)
    await expect(page.getByRole('checkbox', { name: 'Show withdrawn venues' })).toHaveCount(0)
    await expect(grandHall.getByRole('link', { name: 'Edit', exact: true })).toHaveCount(0)
    await expect(grandHall.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(0)
  })
}

// --- 8.3 AC5-AC8: pictures (f8.3.2) -----------------------------------------------------------
test('8.3 AC5/AC6: pictures chosen for a new venue are saved and shown on its card and record', async ({
  page,
}) => {
  const name = uniqueName('Pictures')
  await signIn(page, ACCOUNTS.venueStaff)
  await startNewVenue(page, name)

  await choosePictures(page, pictureFile('front.png'), pictureFile('stage.png'))
  await expect(page.getByRole('img', { name: PREVIEW_NAME })).toHaveCount(2)
  await page.getByRole('button', { name: 'Create venue' }).click()

  await expect(page).toHaveURL(CATALOGUE_PATH)
  await expectLoaded(venueCard(page, name).getByRole('presentation', { includeHidden: true }))

  await venueCard(page, name).getByRole('link', { name }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
  const gallery = page.getByRole('region', { name: 'Pictures' })
  await expectLoaded(gallery.getByRole('img', { name: 'Picture 1 of 2' }))
  await expectLoaded(gallery.getByRole('img', { name: 'Picture 2 of 2' }))
  // The first picture also fills the banner behind the venue's name.
  await expectLoaded(page.getByRole('main').getByRole('presentation'))
})

test('8.3 AC5: pictures can be dragged onto the form', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/new')
  const zone = page.getByRole('group', { name: 'Pictures drop area' })

  const transfer = await page.evaluateHandle((base64) => {
    const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0))
    const data = new DataTransfer()
    data.items.add(new File([bytes], 'hall.png', { type: 'image/png' }))
    data.items.add(new File([bytes], 'foyer.png', { type: 'image/png' }))
    return data
  }, PNG_BYTES.toString('base64'))
  await zone.dispatchEvent('dragenter', { dataTransfer: transfer })
  await expect(page.getByText('Drop the pictures here')).toBeVisible()
  await zone.dispatchEvent('drop', { dataTransfer: transfer })

  await expect(page.getByRole('img', { name: PREVIEW_NAME })).toHaveCount(2)
  await expect(page.getByText('Drop the pictures here')).toHaveCount(0)
})

test('8.3 AC5/AC6: pictures can be removed while editing', async ({ page }) => {
  const name = uniqueName('Fewer pictures')
  await signIn(page, ACCOUNTS.venueStaff)
  await startNewVenue(page, name)
  await choosePictures(page, pictureFile('one.png'), pictureFile('two.png'))
  await page.getByRole('button', { name: 'Create venue' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)

  await venueCard(page, name).getByRole('link', { name: 'Edit', exact: true }).click()
  await expect(page.getByRole('heading', { name: `Edit ${name}` })).toBeVisible()
  await expect(page.getByRole('img', { name: PREVIEW_NAME })).toHaveCount(2)
  await page.getByRole('button', { name: 'Remove picture 1' }).click()
  await expect(page.getByRole('img', { name: PREVIEW_NAME })).toHaveCount(1)
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)

  await venueCard(page, name).getByRole('link', { name }).click()
  const gallery = page.getByRole('region', { name: 'Pictures' })
  await expectLoaded(gallery.getByRole('img', { name: 'Picture 1 of 1' }))
  await expect(gallery.getByRole('img')).toHaveCount(1)

  // Taking the last one off leaves the placeholder: no banner picture and no gallery.
  await page.goto('/venues')
  await venueCard(page, name).getByRole('link', { name: 'Edit', exact: true }).click()
  await expect(page.getByRole('heading', { name: `Edit ${name}` })).toBeVisible()
  await page.getByRole('button', { name: 'Remove picture 1' }).click()
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)
  await expect(
    venueCard(page, name).getByRole('presentation', { includeHidden: true }),
  ).toHaveCount(0)

  await venueCard(page, name).getByRole('link', { name }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Pictures' })).toHaveCount(0)
  await expect(page.getByRole('main').getByRole('presentation')).toHaveCount(0)
})

test('8.3 AC7: a file that is not a JPEG, PNG or WebP is refused in the browser', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/new')

  await page.getByLabel('Choose pictures').setInputFiles({
    name: 'brief.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4'),
  })

  await expect(page.getByText('Choose a JPEG, PNG or WebP picture.')).toBeVisible()
  await expect(page.getByRole('img', { name: PREVIEW_NAME })).toHaveCount(0)
})

test('8.3 AC7: a file over 5 MB is refused in the browser', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/new')

  await choosePictures(page, pictureFile('huge.png', Buffer.alloc(MAX_PICTURE_BYTES + 1)))

  await expect(page.getByText('The picture must be 5 MB or smaller.')).toBeVisible()
  await expect(page.getByRole('img', { name: PREVIEW_NAME })).toHaveCount(0)
})

test('8.3 AC7: an eleventh picture is refused in the browser', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/new')

  await choosePictures(
    page,
    ...Array.from({ length: 11 }, (_, index) => pictureFile(`room-${index + 1}.png`)),
  )

  await expect(page.getByRole('img', { name: PREVIEW_NAME })).toHaveCount(10)
  await expect(page.getByText('A venue can have at most 10 pictures.')).toBeVisible()
})

test('8.3 AC8: a picture the server refuses leaves the new venue saved and says why', async ({
  page,
}) => {
  const name = uniqueName('Refused picture')
  await signIn(page, ACCOUNTS.venueStaff)
  await startNewVenue(page, name)
  // Named and typed as a PNG, so the browser lets it through; the server reads the bytes.
  await choosePictures(page, pictureFile('fake.png', Buffer.from('not a picture')))

  await page.getByRole('button', { name: 'Create venue' }).click()

  await expect(page).toHaveURL(EDIT_PATH)
  await expect(page.getByRole('heading', { name: `Edit ${name}` })).toBeVisible()
  await expect(page.getByRole('main').getByRole('alert')).toContainText(
    'Choose a JPEG, PNG or WebP picture.',
  )
  await page.goto('/venues')
  await expect(venueCard(page, name)).toBeVisible()
})

test('8.3 AC7: a batch keeps the pictures that pass and names each one refused', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/new')

  await choosePictures(
    page,
    pictureFile('hall.png'),
    pictureFile('stage-at-full-size.png', Buffer.alloc(MAX_PICTURE_BYTES + 1)),
    pictureFile('foyer.png'),
  )

  // The two that fit are taken; the one that does not is named, with the reason.
  await expect(page.getByRole('img', { name: PREVIEW_NAME })).toHaveCount(2)
  await expect(page.getByText('These pictures were not added.')).toBeVisible()
  await expect(
    page.getByText('stage-at-full-size.png: The picture must be 5 MB or smaller.'),
  ).toBeVisible()
  await expect(page.getByText('hall.png')).toHaveCount(0)
})

/** Where each picture in `list` is loaded from, in the order shown. */
function sourcesIn(list: Locator) {
  return list
    .getByRole('img')
    .evaluateAll((pictures) => pictures.map((picture) => picture.getAttribute('src')))
}

test('8.3 AC5: pictures can be put in a new order while editing', async ({ page }) => {
  const name = uniqueName('Arranged')
  await signIn(page, ACCOUNTS.venueStaff)
  await startNewVenue(page, name)
  await choosePictures(
    page,
    pictureFile('one.png'),
    pictureFile('two.png'),
    pictureFile('three.png'),
  )
  await page.getByRole('button', { name: 'Create venue' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)
  await venueCard(page, name).getByRole('link', { name }).click()
  const gallery = page.getByRole('region', { name: 'Pictures' })
  await expect(gallery.getByRole('img')).toHaveCount(3)
  const [one, two, three] = await sourcesIn(gallery)

  await page.goto('/venues')
  await venueCard(page, name).getByRole('link', { name: 'Edit', exact: true }).click()
  await expect(page.getByRole('heading', { name: `Edit ${name}` })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Move picture 1 earlier' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Move picture 3 later' })).toBeDisabled()
  await page.getByRole('button', { name: 'Move picture 3 earlier' }).click()
  await page.getByRole('button', { name: 'Move picture 1 later' }).click()
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)

  // Three, one, two: the third picture is now the cover.
  await expect(
    venueCard(page, name).getByRole('presentation', { includeHidden: true }),
  ).toHaveAttribute('src', three!)
  await venueCard(page, name).getByRole('link', { name }).click()
  await expect(gallery.getByRole('img')).toHaveCount(3)
  expect(await sourcesIn(gallery)).toEqual([three, one, two])
})

/** The middle of `element` on the page. */
async function centreOf(element: Locator) {
  const box = await element.boundingBox()
  if (box === null) throw new Error('The element is not on the page.')
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 }
}

test('8.3 AC5: pictures shift aside as a picture is dragged across them', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/new')
  await choosePictures(page, pictureFile('a.png'), pictureFile('b.png'), pictureFile('c.png'))
  const previews = page.getByRole('list', { name: 'Pictures to save' })
  await expect(previews.getByRole('img')).toHaveCount(3)
  const [a, b, c] = await sourcesIn(previews)
  const from = await centreOf(previews.getByRole('img', { name: 'Picture 3 preview' }))
  const to = await centreOf(previews.getByRole('img', { name: 'Picture 1 preview' }))

  // Pick the third picture up and carry it over the first, without letting go.
  await page.mouse.move(from.x, from.y)
  await page.mouse.down()
  await page.mouse.move(to.x, to.y, { steps: 12 })

  // The others have already moved aside for it, as apps do on a phone's home screen.
  await expect.poll(() => sourcesIn(previews)).toEqual([c, a, b])
  await page.mouse.up()
  await expect.poll(() => sourcesIn(previews)).toEqual([c, a, b])
})

test('8.3 AC5: a picture moved aside glides to its new place, never jumps there', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/new')
  await choosePictures(page, pictureFile('a.png'), pictureFile('b.png'), pictureFile('c.png'))
  const previews = page.getByRole('list', { name: 'Pictures to save' })
  await expect(previews.getByRole('img')).toHaveCount(3)
  const second = await previews.getByRole('listitem').nth(1).elementHandle()
  // Let the pictures' own entrance finish first.
  await page.waitForTimeout(600)

  // Moving the third picture earlier pushes the second one place along; follow the second, frame
  // by frame, by how far it is drawn from the place it now belongs in.
  const [offsets] = await Promise.all([
    second!.evaluate(
      (tile) =>
        new Promise<number[]>((resolve) => {
          const seen: number[] = []
          const start = performance.now()
          function frame() {
            const box = tile.getBoundingClientRect()
            const list = tile.parentElement!.getBoundingClientRect()
            seen.push(box.left - (list.left + tile.offsetLeft))
            if (performance.now() - start < 500) requestAnimationFrame(frame)
            else resolve(seen)
          }
          requestAnimationFrame(frame)
        }),
    ),
    page.getByRole('button', { name: 'Move picture 3 earlier' }).click(),
  ])

  // It starts a whole place back and passes through the places between, rather than appearing
  // in its new place at once.
  const step = Math.max(...offsets.map(Math.abs))
  const between = offsets.filter((offset) => offset < -0.15 * step && offset > -0.85 * step)
  expect(step).toBeGreaterThan(100)
  expect(between.length).toBeGreaterThanOrEqual(3)
})

test('8.3 AC6: a picture opens in a carousel that steps through the pictures', async ({ page }) => {
  const name = uniqueName('Carousel')
  await signIn(page, ACCOUNTS.venueStaff)
  await startNewVenue(page, name)
  await choosePictures(
    page,
    pictureFile('one.png'),
    pictureFile('two.png'),
    pictureFile('three.png'),
  )
  await page.getByRole('button', { name: 'Create venue' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)
  await venueCard(page, name).getByRole('link', { name }).click()
  const gallery = page.getByRole('region', { name: 'Pictures' })
  await expect(gallery.getByRole('img')).toHaveCount(3)
  const [one, two, three] = await sourcesIn(gallery)

  await gallery.getByRole('button', { name: 'Picture 2 of 3' }).click()

  const viewer = page.getByRole('dialog', { name: `Pictures of ${name}` })
  const shown = viewer.getByRole('img')
  await expect(viewer).toBeVisible()
  await expect(shown).toHaveAccessibleName('Picture 2 of 3')
  await expect(shown).toHaveAttribute('src', two!)
  await expectLoaded(shown)
  await viewer.getByRole('button', { name: 'Next picture' }).click()
  await expect(shown).toHaveAttribute('src', three!)
  // Past the last picture it comes round to the first.
  await viewer.getByRole('button', { name: 'Next picture' }).click()
  await expect(shown).toHaveAccessibleName('Picture 1 of 3')
  await expect(shown).toHaveAttribute('src', one!)
  await page.keyboard.press('ArrowLeft')
  await expect(shown).toHaveAttribute('src', three!)
  await viewer.getByRole('button', { name: 'Previous picture' }).click()
  await expect(shown).toHaveAttribute('src', two!)

  await page.keyboard.press('Escape')
  await expect(viewer).toHaveCount(0)
  await expect(gallery.getByRole('button', { name: 'Picture 2 of 3' })).toBeFocused()
})

test('8.3 AC6: the carousel moves by thumbnail and by swipe, and closes from outside the picture', async ({
  page,
}) => {
  const name = uniqueName('Swipe')
  await signIn(page, ACCOUNTS.venueStaff)
  await startNewVenue(page, name)
  await choosePictures(
    page,
    pictureFile('one.png'),
    pictureFile('two.png'),
    pictureFile('three.png'),
  )
  await page.getByRole('button', { name: 'Create venue' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)
  await venueCard(page, name).getByRole('link', { name }).click()
  const gallery = page.getByRole('region', { name: 'Pictures' })
  await expect(gallery.getByRole('img')).toHaveCount(3)
  const [, two, three] = await sourcesIn(gallery)
  await gallery.getByRole('button', { name: 'Picture 1 of 3' }).click()
  const viewer = page.getByRole('dialog', { name: `Pictures of ${name}` })
  const shown = viewer.getByRole('img')

  // Every picture is a thumbnail too; choosing one shows it.
  await viewer.getByRole('button', { name: 'Show picture 3' }).click()
  await expect(shown).toHaveAttribute('src', three!)
  await expect(viewer.getByRole('button', { name: 'Show picture 3' })).toHaveAttribute(
    'aria-current',
    'true',
  )

  // Swiping the picture to the right goes back one.
  const middle = await centreOf(shown)
  await page.mouse.move(middle.x - 120, middle.y)
  await page.mouse.down()
  await page.mouse.move(middle.x + 120, middle.y, { steps: 8 })
  await page.mouse.up()
  await expect(shown).toHaveAttribute('src', two!)
  await expect(viewer).toBeVisible()

  // A click on the dark space around the picture closes it.
  await page.mouse.click(8, Math.round(middle.y))
  await expect(viewer).toHaveCount(0)
})
