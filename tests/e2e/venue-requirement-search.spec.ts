/**
 * Story 8.4 - find a venue for each of an event's venue requirements.
 *
 * AC1  Find a venue on an event with venue requirements (2.7) opens the catalogue with every
 *      requirement listed in the "Finding a venue for" banner - its name, how many people it must
 *      hold, its layout and its times - and the first selected and highlighted.
 * AC2  The filters are set from the selected requirement: capacity from its number of people, the
 *      dates from its own start and end, its layout and facilities, and the event's accessibility
 *      needs. Matching venues show straight away.
 * AC3  Selecting another requirement replaces the filters with that requirement's, and the results
 *      change to match, without leaving the page.
 * AC4  The address records the selected requirement, so a reload, a bookmark, Back and a venue
 *      record's back link all return to it.
 * AC5  An event with one requirement shows it alone, with nothing to switch between.
 * AC6  An event marked "No venue requirements" opens the catalogue as it does today, from the
 *      event's dates and expected attendance, with no requirement listed.
 * AC7  The filters can still be changed by hand; selecting the requirement again restores its own.
 * AC8  An address naming a requirement that is not one of the event's opens with the first selected.
 * AC9  A requirement whose start has passed stays listed; selecting it shows why its search
 *      cannot run (8.1 AC8).
 * AC10 The banner lists the requirements for anyone who may read the event; only the event's
 *      assigned coordinator is offered Request this venue.
 * AC11 Two tabs can have different requirements selected, each keeping its own.
 *
 * 8.4 changes no backend rule: the filters come from the event the page already reads, and the
 * search they run is 8.1's (backend/tests/venues/test_venue_search.py). So every case is here.
 *
 * f11.1.1 - story 11.1 AC1, "for the venue requirement currently selected (8.4)": for the event's
 * assigned coordinator, each venue's Suitable or Unsuitable is judged against the requirement
 * selected in the banner. Its rules are backend cases
 * (backend/tests/venues/test_venue_search_by_requirement.py).
 *
 * Seed (backend/db/seed/020_sample_data.sql): Smart Cities Expo, Chloe's, Planning, 14-15 Mar 2028,
 * 300 people, wheelchair access. Its requirements each find different venues: Plenary hall (300,
 * Theatre, projector, sound system and stage, both days) only Grand Hall; Breakout room (40,
 * Classroom, projector, 15 Mar 13:00-17:00) only Seminar Room 2.1; Exhibition space (150,
 * Exhibition, Wi-Fi) Exhibition Foyer and Grand Hall. No spec sends a request for it, so nothing
 * here changes what another spec sees. Regional Sales Summit is Chloe's one-requirement event.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn, venueCard } from './support'

const EXPO = { id: EVENTS.smartCitiesExpo, name: 'Smart Cities Expo' }
const SUMMIT = { id: EVENTS.planning, name: 'Regional Sales Summit' }

const PLENARY = {
  id: 'cccccccc-0000-0000-0028-000000000001',
  name: 'Plenary hall',
  facts: ['300 people', 'Theatre', 'Tue, 14 Mar 2028, 09:00 – Wed, 15 Mar 2028, 18:00'],
}
const BREAKOUT = {
  id: 'cccccccc-0000-0000-0028-000000000002',
  name: 'Breakout room',
  facts: ['40 people', 'Classroom', 'Wed, 15 Mar 2028 · 13:00–17:00'],
}
const EXHIBITION = {
  id: 'cccccccc-0000-0000-0028-000000000003',
  name: 'Exhibition space',
  facts: ['150 people', 'Exhibition', 'Tue, 14 Mar 2028, 10:00 – Wed, 15 Mar 2028, 16:00'],
}
const EXPO_REQUIREMENTS = [PLENARY, BREAKOUT, EXHIBITION]

/** The address Find a venue writes for the Expo's Breakout room, as a coordinator would share it. */
const BREAKOUT_SEARCH = new URLSearchParams([
  ['event', EXPO.id],
  ['requirement', BREAKOUT.id],
  ['capacity', '40'],
  ['from', '2028-03-15T13:00'],
  ['to', '2028-03-15T17:00'],
  ['layout', 'CLASSROOM'],
  ['facility', 'PROJECTOR'],
  ['accessibility', 'WHEELCHAIR_ACCESS'],
])

// As the backend words a search that starts in the past (story 8.1 AC8).
const PAST_SEARCH_MESSAGE = 'Searches cannot start in the past.'

const DAY_MS = 24 * 60 * 60 * 1000

function catalogueBanner(page: Page, eventName: string) {
  return page.getByRole('region', { name: `Finding a venue for ${eventName}` })
}

function requirementChoice(page: Page, requirementName: string) {
  return catalogueBanner(page, EXPO.name).getByRole('button', {
    name: requirementName,
    exact: true,
  })
}

function panel(page: Page) {
  return page.getByRole('complementary', { name: 'Filters' })
}

async function openEvent(page: Page, event: { id: string; name: string }) {
  await page.goto(`/events/${event.id}`)
  await expect(page.getByRole('heading', { name: event.name, level: 1 })).toBeVisible()
}

/** The catalogue as the event's coordinator reaches it: Find a venue on the event's page. */
async function findVenueFor(page: Page, event: { id: string; name: string }) {
  await openEvent(page, event)
  await page.getByRole('link', { name: 'Find a venue' }).click()
  await expect(catalogueBanner(page, event.name)).toBeVisible()
}

/** `selected` is pressed, and every other Expo requirement is listed and not pressed. */
async function expectSelected(page: Page, selected: { name: string }) {
  for (const requirement of EXPO_REQUIREMENTS) {
    await expect(requirementChoice(page, requirement.name)).toHaveAttribute(
      'aria-pressed',
      requirement === selected ? 'true' : 'false',
    )
  }
}

async function expectListed(page: Page, listed: string[], notListed: string[]) {
  for (const name of listed) await expect(venueCard(page, name)).toBeVisible()
  for (const name of notListed) await expect(venueCard(page, name)).toHaveCount(0)
}

/** The Breakout room's own filters, and the one venue they find. */
async function expectBreakoutRoomSearch(page: Page) {
  await expectSelected(page, BREAKOUT)
  await expect(panel(page).getByLabel('Capacity from')).toHaveValue('40')
  await expect(panel(page).getByLabel('Layout')).toHaveValue('CLASSROOM')
  await expectListed(page, ['Seminar Room 2.1'], ['Grand Hall', 'Exhibition Foyer'])
}

function requirementParam(page: Page): string | null {
  return new URL(page.url()).searchParams.get('requirement')
}

test("8.4 AC1/AC2: Find a venue lists the event's requirements, the first selected with its filters set", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)

  await findVenueFor(page, EXPO)

  const requirements = catalogueBanner(page, EXPO.name).getByRole('list', {
    name: 'Venue requirements',
  })
  await expect(requirements.getByRole('listitem')).toHaveCount(3)
  for (const requirement of EXPO_REQUIREMENTS) {
    const choice = requirementChoice(page, requirement.name)
    for (const fact of requirement.facts) await expect(choice).toContainText(fact)
  }
  await expectSelected(page, PLENARY)
  expect(requirementParam(page)).toBe(PLENARY.id)

  // AC2: the plenary hall's own number of people, times, layout and facilities, and the event's
  // accessibility needs.
  const filters = panel(page)
  await expect(filters.getByLabel('Capacity from')).toHaveValue('300')
  await expect(filters.getByLabel('From', { exact: true })).toHaveValue('2028-03-14T09:00')
  await expect(filters.getByLabel('To', { exact: true })).toHaveValue('2028-03-15T18:00')
  await expect(filters.getByLabel('Layout')).toHaveValue('THEATRE')
  for (const facility of ['Projector & screen', 'Sound system', 'Stage']) {
    await expect(filters.getByRole('checkbox', { name: facility })).toBeChecked()
  }
  await expect(filters.getByRole('checkbox', { name: 'Wi-Fi' })).not.toBeChecked()
  await expect(filters.getByRole('checkbox', { name: 'Wheelchair access' })).toBeChecked()

  await expectListed(page, ['Grand Hall'], ['Seminar Room 2.1', 'Exhibition Foyer'])
  await expect(
    venueCard(page, 'Grand Hall').getByRole('link', { name: 'Request this venue' }),
  ).toBeVisible()
})

test('8.4 AC3: selecting another requirement replaces the filters with its own, on the same page', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, EXPO)
  await expectListed(page, ['Grand Hall'], ['Seminar Room 2.1'])
  // A full page load would clear this.
  await page.evaluate(() => document.body.setAttribute('data-e2e-same-page', 'yes'))

  await requirementChoice(page, BREAKOUT.name).click()

  await expectBreakoutRoomSearch(page)
  const filters = panel(page)
  await expect(filters.getByLabel('From', { exact: true })).toHaveValue('2028-03-15T13:00')
  await expect(filters.getByLabel('To', { exact: true })).toHaveValue('2028-03-15T17:00')
  await expect(filters.getByRole('checkbox', { name: 'Projector & screen' })).toBeChecked()
  for (const facility of ['Sound system', 'Stage']) {
    await expect(filters.getByRole('checkbox', { name: facility })).not.toBeChecked()
  }
  await expect(filters.getByRole('checkbox', { name: 'Wheelchair access' })).toBeChecked()

  expect(new URL(page.url()).pathname).toBe('/venues')
  expect(requirementParam(page)).toBe(BREAKOUT.id)
  expect(await page.evaluate(() => document.body.getAttribute('data-e2e-same-page'))).toBe('yes')

  // And on to the third: Exhibition Foyer and Grand Hall both hold 150 for an exhibition.
  await requirementChoice(page, EXHIBITION.name).click()

  await expectSelected(page, EXHIBITION)
  await expectListed(page, ['Exhibition Foyer', 'Grand Hall'], ['Seminar Room 2.1'])
})

test("8.4 AC4: the selected requirement comes back after a reload, from a bookmark, with Back and with the record's back link", async ({
  page,
  context,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, EXPO)
  await requirementChoice(page, BREAKOUT.name).click()
  await expectBreakoutRoomSearch(page)
  const address = page.url()

  await page.reload()
  await expectBreakoutRoomSearch(page)

  // A bookmark: the same address opened afresh.
  const bookmark = await context.newPage()
  await bookmark.goto(address)
  await expectBreakoutRoomSearch(bookmark)
  await bookmark.close()

  // Into a venue's record and Back.
  await venueCard(page, 'Seminar Room 2.1').getByRole('link', { name: 'Seminar Room 2.1' }).click()
  await expect(page.getByRole('heading', { name: 'Seminar Room 2.1', level: 1 })).toBeVisible()
  await page.goBack()
  await expectBreakoutRoomSearch(page)
  expect(page.url()).toBe(address)

  // Into the record again, and out by its own back link.
  await venueCard(page, 'Seminar Room 2.1').getByRole('link', { name: 'Seminar Room 2.1' }).click()
  await expect(page.getByRole('heading', { name: 'Seminar Room 2.1', level: 1 })).toBeVisible()
  await page.getByRole('link', { name: '← Venue catalogue' }).click()
  await expectBreakoutRoomSearch(page)
  expect(page.url()).toBe(address)
})

test('8.4 AC5: an event with one requirement shows it alone, with nothing to switch between', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)

  await findVenueFor(page, SUMMIT)

  const banner = catalogueBanner(page, SUMMIT.name)
  const requirement = banner.getByRole('listitem')
  await expect(requirement).toHaveCount(1)
  await expect(requirement).toContainText('Main venue')
  await expect(requirement).toContainText('220 people')
  await expect(requirement).toContainText('Theatre')
  await expect(banner.getByRole('button')).toHaveCount(0)
  await expect(panel(page).getByLabel('Capacity from')).toHaveValue('220')
})

test('8.4 AC6: an event marked "No venue requirements" opens from its dates and attendance, listing none', async ({
  page,
}) => {
  // No seeded event in Planning records "No venue requirements" (story 2.1 AC4), so Summit's real
  // record is answered with it set, as 12.1 AC15's case for Nimbus does.
  await page.route(`**/events/${SUMMIT.id}`, async (route) => {
    if (route.request().resourceType() !== 'fetch') return route.fallback()
    const response = await route.fetch()
    const event = await response.json()
    return route.fulfill({
      response,
      json: { ...event, venue_none_required: true, venue_requirements: [] },
    })
  })
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, SUMMIT)
  await expect(page.getByText('No venue is required for this event.')).toBeVisible()

  await page.getByRole('link', { name: 'Find a venue' }).click()

  const banner = catalogueBanner(page, SUMMIT.name)
  await expect(banner).toBeVisible()
  await expect(banner).toContainText('220 attendees expected')
  await expect(banner.getByRole('list')).toHaveCount(0)
  expect(new URL(page.url()).searchParams.has('requirement')).toBe(false)
  const filters = panel(page)
  await expect(filters.getByLabel('Capacity from')).toHaveValue('220')
  await expect(filters.getByLabel('From', { exact: true })).toHaveValue('2026-12-15T09:00')
  await expect(filters.getByLabel('To', { exact: true })).toHaveValue('2026-12-16T17:00')
  await expect(filters.getByLabel('Layout')).toHaveValue('')
})

test('8.4 AC7: filters changed by hand stay until the requirement is selected again', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, EXPO)
  await requirementChoice(page, BREAKOUT.name).click()
  await expectBreakoutRoomSearch(page)

  // Seminar Room 2.1 holds 80, so a classroom for 100 finds nothing.
  await panel(page).getByLabel('Capacity from').fill('100')

  await expect(page).toHaveURL(/[?&]capacity=100(&|$)/)
  await expect(page.getByText('No venues match these filters.')).toBeVisible()
  await expectSelected(page, BREAKOUT)
  const banner = catalogueBanner(page, EXPO.name)
  await expect(banner).toContainText(`Select ${BREAKOUT.name} again to restore its own filters.`)

  await requirementChoice(page, BREAKOUT.name).click()

  await expect(page).toHaveURL(/[?&]capacity=40(&|$)/)
  await expectBreakoutRoomSearch(page)
  await expect(banner).not.toContainText('restore its own filters')
})

test("8.4 AC8: an address naming a requirement that is not the event's opens with the first selected", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  const searched: URL[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (request.resourceType() === 'fetch' && url.pathname === '/venues/search') searched.push(url)
  })
  // Another event's requirement, with filters that are not the Expo's.
  const stray = new URLSearchParams([
    ['event', EXPO.id],
    ['requirement', 'cccccccc-0000-0000-0000-000000000003'],
    ['capacity', '5'],
  ])

  await page.goto(`/venues?${stray}`)

  await expectSelected(page, PLENARY)
  await expect(page).toHaveURL(new RegExp(`[?&]requirement=${PLENARY.id}(&|$)`))
  await expect(panel(page).getByLabel('Capacity from')).toHaveValue('300')
  await expectListed(page, ['Grand Hall'], ['Seminar Room 2.1', 'Exhibition Foyer'])
  // Corrected before searching: no search ever ran with the stray address's filters.
  expect(searched.length).toBeGreaterThan(0)
  expect(searched.every((url) => url.searchParams.get('capacity') === '300')).toBe(true)
})

test('8.4 AC9: a requirement whose start has passed stays listed, and selecting it says why it cannot be searched', async ({
  page,
}) => {
  // The seed's dates are fixed, so no seeded requirement is under way. The Expo's real record is
  // answered with its Breakout room started yesterday and running until tomorrow.
  await page.route(`**/events/${EXPO.id}`, async (route) => {
    if (route.request().resourceType() !== 'fetch') return route.fallback()
    const response = await route.fetch()
    const event = await response.json()
    const [plenary, breakout, exhibition] = event.venue_requirements
    const started = {
      ...breakout,
      starts_at: new Date(Date.now() - DAY_MS).toISOString(),
      ends_at: new Date(Date.now() + DAY_MS).toISOString(),
    }
    return route.fulfill({
      response,
      json: { ...event, venue_requirements: [plenary, started, exhibition] },
    })
  })
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, EXPO)
  await expectListed(page, ['Grand Hall'], ['Seminar Room 2.1'])

  await expect(requirementChoice(page, BREAKOUT.name)).toBeVisible()
  await requirementChoice(page, BREAKOUT.name).click()

  await expectSelected(page, BREAKOUT)
  await expect(panel(page).getByRole('alert')).toHaveText(PAST_SEARCH_MESSAGE)
})

for (const viewer of [
  { who: 'Venue Staff', email: ACCOUNTS.venueStaff },
  { who: 'a coordinator not assigned to the event', email: ACCOUNTS.coordinator2 },
]) {
  test(`8.4 AC10: ${viewer.who} see the requirements and can switch between them, but are offered no request`, async ({
    page,
  }) => {
    await signIn(page, viewer.email)

    // The address the event's coordinator's Find a venue writes, shared with them.
    await page.goto(`/venues?${BREAKOUT_SEARCH}`)

    await expectBreakoutRoomSearch(page)
    await requirementChoice(page, EXHIBITION.name).click()
    await expectSelected(page, EXHIBITION)
    await expectListed(page, ['Exhibition Foyer', 'Grand Hall'], ['Seminar Room 2.1'])
    await expect(page.getByRole('link', { name: 'Request this venue' })).toHaveCount(0)
  })
}

test('8.4 AC11: two tabs keep their own requirement selected', async ({ page, context }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, EXPO)
  await requirementChoice(page, BREAKOUT.name).click()
  await expectBreakoutRoomSearch(page)

  const other = await context.newPage()
  await findVenueFor(other, EXPO)
  await requirementChoice(other, EXHIBITION.name).click()
  await expectSelected(other, EXHIBITION)

  await expectBreakoutRoomSearch(page)
  await page.reload()
  await expectBreakoutRoomSearch(page)
  await other.reload()
  await expectSelected(other, EXHIBITION)
  await expectListed(other, ['Exhibition Foyer', 'Grand Hall'], ['Seminar Room 2.1'])
  expect(requirementParam(page)).toBe(BREAKOUT.id)
  expect(requirementParam(other)).toBe(EXHIBITION.id)
})

test('11.1 AC1: each venue is judged against the requirement selected in the banner', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, EXPO)
  await expect(
    venueCard(page, 'Grand Hall').getByText('Suitable for Plenary hall', { exact: true }),
  ).toBeVisible()

  await requirementChoice(page, BREAKOUT.name).click()

  await expect(
    venueCard(page, 'Seminar Room 2.1').getByText('Suitable for Breakout room', { exact: true }),
  ).toBeVisible()
  // With the filters cleared the selection stays, and a room too small for the breakout room
  // fails by the breakout room's own number, not the plenary hall's.
  await panel(page).getByRole('button', { name: 'Clear all filters' }).click()
  const boardroom = venueCard(page, 'Boardroom 3.4')
  await expect(boardroom.getByText('Unsuitable for Breakout room', { exact: true })).toBeVisible()
  await expect(boardroom.getByText('Capacity 16 < 40 people', { exact: true })).toBeVisible()
})
