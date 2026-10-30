import { expect, test, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  EVENTS,
  approvedEvent,
  changeRequests,
  confirmDetailsDialog,
  confirmRegistration,
  corsHeaders,
  signIn,
} from './support'

/**
 * Story 18.5 - register guests with my registration. END-TO-END tests: what an attendee and an
 * organiser click through.
 *
 * Level: e2e. The rules behind these pages - at most 10 guests, a guest's name and dietary limits,
 * the places a group takes, when guests can no longer change, who may change them, and two
 * requests for the last places - are proven in
 * backend/tests/registrations/test_register_guests_*.py, not repeated here. The exceptions are
 * AC1/AC6's checks in the browser, which stop an 11th guest or a guest with no name before any
 * request is sent, so no backend test can see them.
 *
 * The ACs are the Product Backlog's (row 57, CL-173, CL-185), summarised:
 *
 * AC1 When registering, the attendee can add guests, each with a name, optional dietary
 *     requirements (as 18.4 AC6) and no phone number; they are registered together as one group.
 * AC2 Each guest takes a place against the event's capacity; a group that does not fit is
 *     refused. (Here: the dialog offers no more guests than there are places for, and a refusal
 *     keeps what was typed; the refusal itself is a backend case.)
 * AC3 After registering, the attendee can add, change or remove guests, and sees them on My
 *     registrations - until registration closes (CL-185). (Here: the page offers Change guests
 *     only when the server says so; the rule itself is a backend case.)
 * AC4 The organiser and assigned coordinator see each guest under their attendee in the
 *     registration list (18.3), with their name and dietary requirements.
 * AC5 The change-impact count in 19.3 includes guests.
 * AC6 An attendee can bring 0 to 10 guests. Each guest's name is required.
 * AC7 Withdrawing a registration withdraws the whole group. (Here: the withdraw dialog says so.)
 *
 * An attendee registers from an event's page (18.1 AC9, fix f18.1.2), opened from its card on
 * Upcoming events.
 *
 * Each flow has a seeded attendee of its own (backend/db/seed/020_sample_data.sql, story 18.5's
 * block), since specs run in parallel and a registration happens once: Gina registers for the
 * batik workshop with two guests; Hana, registered alone for the kite afternoon, adds a guest and
 * removes them again. The browser-only checks open Gina's dialog for the kite afternoon and send
 * nothing. Aiden's registrations are only read: the food tasting walk's registration closed on 1
 * Oct 2026 (story 18.4's seed), and his registration with guests is stubbed, so nothing is written.
 */

const UPCOMING_EVENTS_PATH = '/browse'
const KITE_AFTERNOON_API_PATH = `/registrations/events/${EVENTS.kiteAfternoon}`
const MY_REGISTRATIONS_PATH = '/registrations'
const CHANGE_GUESTS_DIALOG = 'Change your guests'
const MAX_GUESTS = 10
const TOO_MANY_GUESTS_MESSAGE = 'You can bring at most 10 guests.'
// Story 18.5 AC2/AC3: the places left, not the 10-guest limit, stop more guests.
const NO_PLACES_FOR_MORE_GUESTS_MESSAGE = 'There are not enough places left for more guests.'
const GUEST_NAME_REQUIRED_MESSAGE = "Enter your guest's name."
const GUEST_DIETARY_MAX_LENGTH = 500
const NOT_ENOUGH_PLACES_MESSAGE = 'There are not enough places left for you and your guests.'
const GUESTS_WITHDRAWN_TOO = 'Your guests are withdrawn with you.'
const GUESTS_NOT_ENOUGH_PLACES_MESSAGE = 'There are not enough places left for these guests.'

const BATIK_WORKSHOP = 'Batik Printing Workshop' // 30 places; Gina registers with two guests
const KITE_AFTERNOON = 'Kite Flying Afternoon' // 30 places; Hana registered alone
const FOOD_TASTING_WALK = 'Food Tasting Walk' // registration closed; Aiden registered (18.4)
const GINA = { name: 'Gina Attendee' }
// Unique to the run, so a rerun's guests are never mistaken for another's (tests/CLAUDE.md).
const RAVI = { name: `Ravi Kumar ${Date.now()}`, dietary: 'Vegetarian' }
const MEI = { name: `Mei Lin ${Date.now()}` }
const ANA = { name: `Ana Cruz ${Date.now()}`, dietary: 'No shellfish' }
const NONE = 'None'
const PHONE = { width: 390, height: 844 }

/** An event's card, found by its name (as in attendee-registration.spec.ts). */
function eventCard(page: Page, name: string) {
  return page.getByRole('listitem').filter({ has: page.getByRole('heading', { level: 3, name }) })
}

function guestGroup(page: Page, n: number) {
  return page.getByRole('group', { name: `Guest ${n}`, exact: true })
}

function addGuestButton(page: Page) {
  return page.getByRole('button', { name: 'Add a guest' })
}

/** Add a guest at the end of the open dialog's list, as the attendee types them. */
async function addGuest(page: Page, n: number, guest: { name: string; dietary?: string }) {
  await addGuestButton(page).click()
  const group = guestGroup(page, n)
  await group.getByLabel("Guest's name").fill(guest.name)
  if (guest.dietary !== undefined) {
    await group.getByLabel("Guest's dietary requirements").fill(guest.dietary)
  }
}

/** 18.1 AC9: where an event's page says where registration stands, and offers Register. */
function registration(page: Page) {
  return page.getByRole('region', { name: 'Registration', exact: true })
}

/** 18.1 AC9: from Upcoming events, open an event's page by its card's link, its title. */
async function openEventPage(page: Page, name: string) {
  await page.goto(UPCOMING_EVENTS_PATH)
  await eventCard(page, name).getByRole('link', { name }).click()
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
}

/** Open an event's page and press Register, which opens "Confirm your details". */
async function startRegistering(page: Page, name: string) {
  await openEventPage(page, name)
  await registration(page).getByRole('button', { name: `Register for ${name}` }).click()
}

/** The places left an event's page shows, as a number. */
async function placesLeft(page: Page): Promise<number> {
  const text = await registration(page)
    .getByText(/\d+ places? left/)
    .innerText()
  return Number(text.match(/\d+/)![0])
}

function registrations(page: Page) {
  return page.getByRole('region', { name: 'Registered attendees', exact: true })
}

test('18.5 AC1/AC2/AC3/AC4: an attendee registers with two guests, who take places and are listed for the organiser', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee7)
  await startRegistering(page, BATIK_WORKSHOP)

  const dialog = confirmDetailsDialog(page)
  await expect(dialog.getByRole('group', { name: 'Guests' })).toBeVisible()
  await addGuest(page, 1, RAVI)
  await addGuest(page, 2, MEI)
  // AC1: nothing but a name and dietary requirements is asked of a guest.
  await expect(guestGroup(page, 1).getByRole('textbox')).toHaveCount(2)
  await confirmRegistration(page)
  await expect(dialog).toHaveCount(0)

  // AC2: the group took three of the thirty places.
  await expect(registration(page).getByText('Registered', { exact: true })).toBeVisible()
  await expect(registration(page)).toContainText('27 places left')

  // AC3: My registrations names the guests.
  await page.goto(MY_REGISTRATIONS_PATH)
  const mine = eventCard(page, BATIK_WORKSHOP)
  await expect(mine).toContainText(RAVI.name)
  await expect(mine).toContainText(MEI.name)

  // AC4: the organiser sees each guest on a row of their own under Gina's, with their dietary
  // requirements - "None" for Mei's - and the count includes them.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/registrations/report?event=${EVENTS.batikWorkshop}`)
  const list = registrations(page)
  await expect(list).toContainText('3 / 30')
  const rows = list.getByRole('row')
  const ravi = rows.filter({ hasText: RAVI.name })
  const mei = rows.filter({ hasText: MEI.name })
  await expect(ravi).toContainText(`Guest of ${GINA.name}`)
  await expect(ravi.getByRole('cell').nth(4)).toHaveText(RAVI.dietary)
  await expect(mei).toContainText(`Guest of ${GINA.name}`)
  await expect(mei.getByRole('cell').nth(4)).toHaveText(NONE)
  // Under their attendee, in the order she gave them.
  const names = await rows.allInnerTexts()
  const at = (name: string) => names.findIndex((row) => row.includes(name))
  expect(at(GINA.name)).toBeLessThan(at(RAVI.name))
  expect(at(RAVI.name)).toBeLessThan(at(MEI.name))
  // On a desktop the table still fits the page, with no Guests column to scroll to.
  await expect(list.getByRole('columnheader', { name: 'Guests' })).toHaveCount(0)

  // On a phone each guest is a card of their own under Gina's, and nothing scrolls sideways.
  await page.setViewportSize(PHONE)
  for (const name of [RAVI.name, MEI.name]) {
    const guest = list.getByText(name)
    await guest.scrollIntoViewIfNeeded()
    const box = (await guest.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(PHONE.width)
  }
  await expect(ravi).toContainText(`Guest of ${GINA.name}`)
  expect(
    await list.evaluate((section) =>
      [section, ...section.querySelectorAll('*')].every(
        (element) => element.scrollWidth <= element.clientWidth + 1,
      ),
    ),
  ).toBe(true)
})

test('18.5 AC3: an attendee registered alone adds a guest on My registrations, then removes them', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee8)
  await page.goto(MY_REGISTRATIONS_PATH)
  const card = eventCard(page, KITE_AFTERNOON)
  await card.getByRole('button', { name: `Change guests for ${KITE_AFTERNOON}` }).click()

  const dialog = page.getByRole('dialog', { name: CHANGE_GUESTS_DIALOG })
  await addGuest(page, 1, ANA)
  await dialog.getByRole('button', { name: 'Save guests' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(card).toContainText(ANA.name)

  // Reloading shows what was saved.
  await page.reload()
  await expect(card).toContainText(ANA.name)

  await card.getByRole('button', { name: `Change guests for ${KITE_AFTERNOON}` }).click()
  await expect(guestGroup(page, 1).getByLabel("Guest's name")).toHaveValue(ANA.name)
  await expect(guestGroup(page, 1).getByLabel("Guest's dietary requirements")).toHaveValue(
    ANA.dietary,
  )
  await dialog.getByRole('button', { name: 'Remove guest 1' }).click()
  await dialog.getByRole('button', { name: 'Save guests' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(card).not.toContainText(ANA.name)
  await expect(card.getByText('Registered', { exact: true })).toBeVisible()
})

test('18.5 AC6: after ten guests the dialog offers no more, and says why, before sending anything', async ({
  page,
}) => {
  const sent: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST') sent.push(request.url())
  })
  await signIn(page, ACCOUNTS.attendee7)
  await openEventPage(page, KITE_AFTERNOON)
  sent.length = 0
  await registration(page)
    .getByRole('button', { name: `Register for ${KITE_AFTERNOON}` })
    .click()

  const dialog = confirmDetailsDialog(page)
  for (let n = 1; n <= MAX_GUESTS; n++) {
    await addGuest(page, n, { name: `Guest ${n}` })
  }

  await expect(addGuestButton(page)).toBeDisabled()
  await expect(dialog).toContainText(TOO_MANY_GUESTS_MESSAGE)
  await expect(guestGroup(page, MAX_GUESTS + 1)).toHaveCount(0)
  expect(sent).toEqual([])
})

test("18.5 AC1/AC6: a guest left without a name, or with only spaces, is refused before sending, and a guest's dietary requirements take no more than 500 characters", async ({
  page,
}) => {
  const sent: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST') sent.push(request.url())
  })
  await signIn(page, ACCOUNTS.attendee7)
  await openEventPage(page, KITE_AFTERNOON)
  sent.length = 0
  await registration(page)
    .getByRole('button', { name: `Register for ${KITE_AFTERNOON}` })
    .click()

  const dialog = confirmDetailsDialog(page)
  await addGuestButton(page).click()
  const dietary = guestGroup(page, 1).getByLabel("Guest's dietary requirements")
  await dietary.fill('v'.repeat(GUEST_DIETARY_MAX_LENGTH + 1))
  await expect(dietary).toHaveValue('v'.repeat(GUEST_DIETARY_MAX_LENGTH))
  await addGuest(page, 2, { name: '   ' })

  await confirmRegistration(page)

  await expect(guestGroup(page, 1)).toContainText(GUEST_NAME_REQUIRED_MESSAGE)
  await expect(guestGroup(page, 2)).toContainText(GUEST_NAME_REQUIRED_MESSAGE)
  await expect(dialog).toBeVisible()
  expect(sent).toEqual([])
})

test('18.5 AC3: a registration whose registration has closed offers Withdraw but not Change guests', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee)
  await page.goto(MY_REGISTRATIONS_PATH)

  const closed = eventCard(page, FOOD_TASTING_WALK)
  await expect(
    closed.getByRole('button', { name: `Withdraw from ${FOOD_TASTING_WALK}` }),
  ).toBeVisible()
  await expect(
    closed.getByRole('button', { name: `Change guests for ${FOOD_TASTING_WALK}` }),
  ).toHaveCount(0)
})

test("18.5 AC2: the event's page counts the whole group at once, before the event is read again", async ({
  page,
}) => {
  // The registration is stubbed as taken with two guests, and the event read again after it is
  // held back, so the page can only show what it worked out itself. Nothing is written.
  let hasRegistered = false
  let releaseEvent: () => void = () => {}
  const eventHeld = new Promise<void>((resolve) => {
    releaseEvent = resolve
  })
  await page.route(
    (url) => url.pathname === '/registrations' || url.pathname === KITE_AFTERNOON_API_PATH,
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      const path = new URL(request.url()).pathname
      if (path === '/registrations' && request.method() === 'POST') {
        hasRegistered = true
        const sent = request.postDataJSON() as { event_id: string }
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          headers: corsHeaders(request),
          body: JSON.stringify({
            id: '00000000-0000-4000-8000-000000000185',
            event_id: sent.event_id,
            status: 'REGISTERED',
            registered_at: '2026-10-30T02:00:00Z',
            guests: [
              { full_name: RAVI.name, dietary_requirements: RAVI.dietary },
              { full_name: MEI.name, dietary_requirements: null },
            ],
          }),
        })
      }
      if (path === KITE_AFTERNOON_API_PATH && hasRegistered) await eventHeld
      return route.fallback()
    },
  )
  await signIn(page, ACCOUNTS.attendee)
  await openEventPage(page, KITE_AFTERNOON)
  const before = await placesLeft(page)

  await registration(page)
    .getByRole('button', { name: `Register for ${KITE_AFTERNOON}` })
    .click()
  await addGuest(page, 1, RAVI)
  await addGuest(page, 2, MEI)
  await confirmRegistration(page)

  await expect(registration(page).getByText('Registered', { exact: true })).toBeVisible()
  await expect(registration(page)).toContainText(`${before - 3} places left`)
  releaseEvent()
})

test('18.5 AC2: with 2 places left the dialog allows one guest, and says why, before sending anything', async ({
  page,
}) => {
  // The event is the server's own, with the kite afternoon's places cut to 2: a state the seed
  // cannot reach without filling the event. Nothing is sent.
  await page.route(
    (url) => url.pathname === KITE_AFTERNOON_API_PATH,
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      const response = await route.fetch()
      const event = (await response.json()) as { places_left: number }
      event.places_left = 2
      return route.fulfill({ response, json: event })
    },
  )
  const sent: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST') sent.push(request.url())
  })
  await signIn(page, ACCOUNTS.attendee7)
  await openEventPage(page, KITE_AFTERNOON)
  sent.length = 0
  await registration(page)
    .getByRole('button', { name: `Register for ${KITE_AFTERNOON}` })
    .click()

  const dialog = confirmDetailsDialog(page)
  await addGuest(page, 1, { name: 'Guest 1' })

  await expect(addGuestButton(page)).toBeDisabled()
  await expect(dialog).toContainText(NO_PLACES_FOR_MORE_GUESTS_MESSAGE)
  await expect(dialog).not.toContainText(TOO_MANY_GUESTS_MESSAGE)
  expect(sent).toEqual([])
})

test('18.5 AC3: Change guests allows only as many guests as there are places for', async ({
  page,
}) => {
  // Hana's registrations are the server's own, with no places left for the kite afternoon's
  // guests: a state the seed cannot reach without filling the event. Nothing is sent.
  await page.route(
    (url) => url.pathname === '/registrations',
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch' || request.method() !== 'GET') {
        return route.fallback()
      }
      const response = await route.fetch()
      const mine = (await response.json()) as {
        event_name: string
        guests: unknown[]
        max_guests: number
      }[]
      for (const registration of mine) {
        if (registration.event_name === KITE_AFTERNOON) {
          registration.guests = []
          registration.max_guests = 0
        }
      }
      return route.fulfill({ response, json: mine })
    },
  )
  await signIn(page, ACCOUNTS.attendee8)
  await page.goto(MY_REGISTRATIONS_PATH)
  await eventCard(page, KITE_AFTERNOON)
    .getByRole('button', { name: `Change guests for ${KITE_AFTERNOON}` })
    .click()

  const dialog = page.getByRole('dialog', { name: CHANGE_GUESTS_DIALOG })
  await expect(addGuestButton(page)).toBeDisabled()
  await expect(dialog).toContainText(NO_PLACES_FOR_MORE_GUESTS_MESSAGE)
})

test('18.5 AC1: removing a guest takes away that guest, and the others keep their order', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee7)
  await startRegistering(page, KITE_AFTERNOON)

  const dialog = confirmDetailsDialog(page)
  await addGuest(page, 1, RAVI)
  await addGuest(page, 2, MEI)
  await addGuest(page, 3, ANA)
  await dialog.getByRole('button', { name: 'Remove guest 2' }).click()

  await expect(guestGroup(page, 3)).toHaveCount(0)
  await expect(guestGroup(page, 1).getByLabel("Guest's name")).toHaveValue(RAVI.name)
  await expect(guestGroup(page, 2).getByLabel("Guest's name")).toHaveValue(ANA.name)
  await expect(guestGroup(page, 2).getByLabel("Guest's dietary requirements")).toHaveValue(
    ANA.dietary,
  )
})

test('18.5 AC2: a group the server refuses for want of places keeps the dialog open, with every guest typed', async ({
  page,
}) => {
  // The registration is refused as the server refuses a group that no longer fits - another
  // attendee took a place meanwhile, a state the seed cannot reach - and the event read after it
  // has 2 places left. Nothing is written.
  let isRefused = false
  await page.route(
    (url) => url.pathname === '/registrations' || url.pathname === KITE_AFTERNOON_API_PATH,
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      if (new URL(request.url()).pathname === KITE_AFTERNOON_API_PATH) {
        if (!isRefused) return route.fallback()
        const response = await route.fetch()
        const event = (await response.json()) as { places_left: number }
        event.places_left = 2
        return route.fulfill({ response, json: event })
      }
      if (request.method() !== 'POST') return route.fallback()
      isRefused = true
      return route.fulfill({
        status: 409,
        contentType: 'application/json',
        headers: corsHeaders(request),
        body: JSON.stringify({ detail: NOT_ENOUGH_PLACES_MESSAGE }),
      })
    },
  )
  await signIn(page, ACCOUNTS.attendee7)
  await startRegistering(page, KITE_AFTERNOON)
  const dialog = confirmDetailsDialog(page)
  await addGuest(page, 1, RAVI)
  await addGuest(page, 2, MEI)

  await confirmRegistration(page)

  await expect(dialog.getByRole('alert')).toContainText(NOT_ENOUGH_PLACES_MESSAGE)
  await expect(guestGroup(page, 1).getByLabel("Guest's name")).toHaveValue(RAVI.name)
  await expect(guestGroup(page, 1).getByLabel("Guest's dietary requirements")).toHaveValue(
    RAVI.dietary,
  )
  await expect(guestGroup(page, 2).getByLabel("Guest's name")).toHaveValue(MEI.name)
  // The event is read again, so the guest limit catches up: 2 places left is one guest, and two
  // are typed, so no more can be added and the dialog says why.
  await expect(addGuestButton(page)).toBeDisabled()
  await expect(dialog).toContainText(NO_PLACES_FOR_MORE_GUESTS_MESSAGE)
})

test('18.5 AC3: a change the server refuses for want of places keeps every guest typed, and the limit catches up', async ({
  page,
}) => {
  // Hana's registrations are the server's own, with room for two guests on the kite afternoon
  // until the change is refused - another attendee took the places meanwhile, a state the seed
  // cannot reach - and none after it. Nothing is written.
  let isRefused = false
  await page.route(
    (url) => url.pathname.startsWith('/registrations'),
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      if (request.method() === 'PUT') {
        isRefused = true
        return route.fulfill({
          status: 409,
          contentType: 'application/json',
          headers: corsHeaders(request),
          body: JSON.stringify({ detail: GUESTS_NOT_ENOUGH_PLACES_MESSAGE }),
        })
      }
      if (new URL(request.url()).pathname !== '/registrations' || request.method() !== 'GET') {
        return route.fallback()
      }
      const response = await route.fetch()
      const mine = (await response.json()) as {
        event_name: string
        guests: unknown[]
        max_guests: number
      }[]
      for (const registration of mine) {
        if (registration.event_name === KITE_AFTERNOON) {
          registration.guests = []
          registration.max_guests = isRefused ? 0 : 2
        }
      }
      return route.fulfill({ response, json: mine })
    },
  )
  await signIn(page, ACCOUNTS.attendee8)
  await page.goto(MY_REGISTRATIONS_PATH)
  await eventCard(page, KITE_AFTERNOON)
    .getByRole('button', { name: `Change guests for ${KITE_AFTERNOON}` })
    .click()
  const dialog = page.getByRole('dialog', { name: CHANGE_GUESTS_DIALOG })
  await addGuest(page, 1, RAVI)

  await dialog.getByRole('button', { name: 'Save guests' }).click()

  await expect(dialog.getByRole('alert')).toContainText(GUESTS_NOT_ENOUGH_PLACES_MESSAGE)
  await expect(guestGroup(page, 1).getByLabel("Guest's name")).toHaveValue(RAVI.name)
  await expect(addGuestButton(page)).toBeDisabled()
  await expect(dialog).toContainText(NO_PLACES_FOR_MORE_GUESTS_MESSAGE)
})

test('18.5 AC7: withdrawing a registration with guests says the guests are withdrawn too', async ({
  page,
}) => {
  // Hana's registrations are the server's own, with a guest on the kite afternoon's: the dialog is
  // only opened and cancelled, so nothing is written.
  await page.route(
    (url) => url.pathname === '/registrations',
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch' || request.method() !== 'GET') {
        return route.fallback()
      }
      const response = await route.fetch()
      const mine = (await response.json()) as { event_name: string; guests: unknown[] }[]
      for (const registration of mine) {
        if (registration.event_name === KITE_AFTERNOON) {
          registration.guests = [{ full_name: ANA.name, dietary_requirements: ANA.dietary }]
        }
      }
      return route.fulfill({ response, json: mine })
    },
  )
  await signIn(page, ACCOUNTS.attendee8)
  await page.goto(MY_REGISTRATIONS_PATH)
  await eventCard(page, KITE_AFTERNOON)
    .getByRole('button', { name: `Withdraw from ${KITE_AFTERNOON}` })
    .click()

  await expect(page.getByRole('dialog')).toContainText(GUESTS_WITHDRAWN_TOO)
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()
})

test("18.5 AC5: 19.3's change impact counts guests as people, not attendees", async ({ page }) => {
  // The impact is the server's own, with its registrations made an attendee and two guests over an
  // attendance of 2: a state that needs an approved event with a group registered, and an
  // attendance below what its venues need. Only the change request the coordinator reads is
  // written.
  test.setTimeout(90_000)
  const { eventId, coordinator } = await approvedEvent(page, 'Guests impact')
  await changeRequests(page).getByRole('button', { name: 'Request a change' }).click()
  await changeRequests(page)
    .getByLabel('What to change')
    .selectOption({ label: 'Expected attendance' })
  await changeRequests(page).getByLabel('New expected attendance').fill('150')
  await changeRequests(page).getByLabel('Reason for the change').fill('Fewer can come.')
  await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()
  await expect(changeRequests(page).getByRole('listitem')).toContainText('Pending')
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.route(
    (url) => url.pathname.endsWith('/impact'),
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      const response = await route.fetch()
      const impact = await response.json()
      impact.registrations = {
        active_count: 3,
        proposed_attendance: 2,
        over_by: 1,
        dates_change: false,
      }
      impact.has_impact = true
      return route.fulfill({ response, json: impact })
    },
  )

  await signIn(page, coordinator)
  await page.goto(`/events/${eventId}`)
  await changeRequests(page).getByRole('button', { name: 'Show impact' }).click()

  await expect(changeRequests(page)).toContainText(
    '3 people registered, 1 more than the proposed attendance of 2.',
  )
  await expect(changeRequests(page)).not.toContainText('3 attendees')
})
