/**
 * Story 9.1: venue availability calendar (the 14-criterion version; AC6, the Venue Schedule page
 * for Venue Staff, is a later step).
 * AC1 one venue, one month at a time, with previous / next.
 * AC2 a confirmed booking is unavailable; a pending request shows as "Held - pending", with the
 * words as well as the colour.
 * AC3 each occupied period shows its event's name.
 * AC5 a day with entries opens a list of that day's items in time order - event name, times,
 * booked or held - with setup and teardown, and closures with their reason.
 * AC7 / AC8 / AC9 several events on one day, back-to-back events, and a multi-day booking are
 * listed separately, the last on every day it covers. The seed has none of these on one venue,
 * so they stub the calendar fetch (tests/CLAUDE.md's exception for a state the seed cannot
 * reach); backend/tests/venues/test_venue_calendar.py covers the data itself.
 * AC10 previous / next keep the venue and the calendar, whatever is loading or has failed.
 * AC12 a venue with nothing booked shows no unavailable days.
 * AC13 (restricted to Event Coordinator, Venue Staff and Technical Support): the refusals are a
 * backend case, backend/tests/venues/test_venue_calendar.py::test_calendar_is_restricted_to_internal_roles;
 * here Venue Staff and Technical Support open a venue from the catalogue and see its calendar.
 * The calendar opens on the current month, and the real-seed tests reach November 2026 (where the
 * seed data's bookings and maintenance period live) by pressing Next twice from September. Left
 * to the real clock that only works during September 2026 - from 1 October every "November 2026"
 * assertion would fail - so the page's clock is pinned to mid-September (see `beforeEach` below).
 *
 * Bug f9.1.1: two regression tests below stub the calendar fetch to cover the Previous/Next
 * transition itself, not just the end state.
 */
import { expect, test, type Locator, type Page, type Route } from '@playwright/test'
import { ACCOUNTS, corsHeaders, signIn } from './support'

// The calendar opens on the current month and these specs are written against September 2026, so
// the page's own clock is pinned to it. Only the browser's Date moves: the API and its sessions
// keep real time, and timers still run.
test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-09-15T10:00:00+08:00'))
})

/** The "Availability" card - a region via its `aria-labelledby`, same pattern as
 *  venue-detail.spec.ts's cardSection(). */
function availabilitySection(page: Page) {
  return page.getByRole('region', { name: 'Availability', exact: true })
}

async function goToNovember2026(page: Page) {
  const section = availabilitySection(page)
  for (let i = 0; i < 2; i += 1) {
    await section.getByRole('button', { name: 'Next →' }).click()
  }
  await expect(page.getByText('November 2026')).toBeVisible()
  // The title updates before the real fetch resolves (f9.1.1) - wait for it to finish, or the
  // checks below for what November holds would run against whatever month was there before.
  await expect(page.getByText('Loading availability…')).toHaveCount(0)
}

test('9.1 AC2/AC3: an approved booking shows as unavailable, with the event as the label', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  await goToNovember2026(page)

  await expect(page.getByText('Nimbus Developer Conference')).toBeVisible()
})

test('9.1 AC2: a maintenance period shows as unavailable, with its notes as the label', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Seminar Room 2.1' }).click()

  await goToNovember2026(page)

  await expect(page.getByText('Annual air-con servicing').first()).toBeVisible()
})

test('9.1 AC12: a venue with nothing booked shows no unavailable days', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Boardroom 3.4' }).click()

  await goToNovember2026(page)

  await expect(page.getByText('Nimbus Developer Conference')).not.toBeVisible()
  await expect(page.getByText('Annual air-con servicing')).not.toBeVisible()
})

test('9.1 AC1: navigating back a month leaves the current month', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  const section = availabilitySection(page)
  await expect(page.getByText('September 2026')).toBeVisible()
  await section.getByRole('button', { name: '← Prev' }).click()
  await expect(page.getByText('August 2026')).toBeVisible()
})

/**
 * Intercepts exactly the next matching `/calendar` fetch (falling back to the real network for
 * every other request, including ones before and after it), so a test can control one month's
 * response without disturbing the rest of the page. CORS headers are required since the app and
 * API are on different ports (tests/CLAUDE.md).
 */
async function interceptNextCalendarFetch(page: Page, fulfill: (route: Route) => Promise<void>) {
  let handled = false
  await page.route(
    (url) => /\/venues\/[^/]+\/calendar$/.test(url.pathname),
    async (route) => {
      if (handled || route.request().resourceType() !== 'fetch') return route.fallback()
      handled = true
      await fulfill(route)
    },
  )
}

/**
 * Regression test for bug f9.1.1: clicking Next/Previous used to unmount the whole calendar
 * (including its own Prev/Next buttons) the instant the new range's fetch started, replacing it
 * with a bare loading message until the fetch resolved - and never brought it back at all if the
 * fetch failed, stranding the user with no way to navigate elsewhere. The regression guard is
 * that the calendar's own controls stay on screen throughout, not just that the data is right.
 *
 * The stub holds its response behind a promise the test resolves itself, rather than a fixed
 * delay: a hard-coded timeout races the test's own assertions on a slow CI runner, where enough
 * of them together could eat the delay before the loading check even runs.
 */
test('9.1 AC10: the calendar and its controls stay visible while the next range is slow to load', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  const section = availabilitySection(page)
  await expect(page.getByText('September 2026')).toBeVisible()

  let resolveFetch: () => void = () => {}
  const fetchGate = new Promise<void>((resolve) => {
    resolveFetch = resolve
  })
  await interceptNextCalendarFetch(page, async (route) => {
    await fetchGate
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
      headers: corsHeaders(route.request()),
    })
  })

  await section.getByRole('button', { name: 'Next →' }).click()

  // Checked first, and before the gate is released, so this can never pass by the stub simply
  // having resolved before the assertion ran.
  await expect(page.getByText('Loading availability…')).toBeVisible()
  await expect(page.getByText('October 2026')).toBeVisible()
  await expect(section.getByRole('button', { name: '← Prev' })).toBeVisible()
  await expect(section.getByRole('button', { name: 'Next →' })).toBeVisible()

  resolveFetch()
  await expect(page.getByText('Loading availability…')).toHaveCount(0)
})

/**
 * Regression test for bug f9.1.1 AC2: an empty grid alone cannot say whether a month is loading,
 * genuinely free, or unknown because its fetch failed - so a failed re-fetch must render as
 * visibly unknown, not as a normal fully-available month, while still leaving Prev/Next usable.
 */
test('9.1 AC10: a failed re-fetch shows availability as unknown, not a dead end', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  const section = availabilitySection(page)
  await expect(page.getByText('September 2026')).toBeVisible()

  await interceptNextCalendarFetch(page, async (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: null }),
      headers: corsHeaders(route.request()),
    }),
  )

  await section.getByRole('button', { name: 'Next →' }).click()

  await expect(page.getByText('October 2026')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('The server hit a problem')
  // AC10: shown as unknown, not silently rendered as if the month were confirmed available.
  await expect(page.getByRole('status')).toHaveText(/Availability unknown/)
  await expect(section.getByRole('button', { name: '← Prev' })).toBeVisible()

  // Recovers on the next navigation (unstubbed, real network) instead of staying stuck.
  await section.getByRole('button', { name: '← Prev' }).click()
  await expect(page.getByText('September 2026')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('status')).toHaveText('')
})

/** Story 9.1 AC5: the button that opens a day's list - a day cell with entries. Its name is the
 *  date, how many items it holds and what the cell shows of them, so it can be found by any of
 *  those without the grid's own text. */
function dayButton(page: Page, name: RegExp = /, \d+ items?/) {
  return availabilitySection(page).getByRole('button', { name })
}

/** The list a day opens, a region named after the day (e.g. "Wed, 25 Nov 2026"). */
function dayList(page: Page, name: RegExp) {
  return page.getByRole('region', { name })
}

test('9.1 AC2: a pending request shows as held, in words as well as colour', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Seminar Room 2.1' }).click()

  await goToNovember2026(page)

  const section = availabilitySection(page)
  await expect(section.getByText('Held – Nimbus Developer Conference')).toBeVisible()
  // The legend names the style; exact, so the day list's own badge cannot be what matches.
  await expect(section.getByText('Held – pending', { exact: true })).toBeVisible()
})

test('9.1 AC5: opening a day lists its booking with the event, times and "Booked"', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()
  await goToNovember2026(page)

  const button = dayButton(page, /25 November 2026/)
  await expect(button).toHaveAttribute('aria-expanded', 'false')
  await button.click()

  await expect(button).toHaveAttribute('aria-expanded', 'true')
  const list = dayList(page, /25 Nov 2026/)
  await expect(list).toContainText('Nimbus Developer Conference')
  await expect(list).toContainText('09:00–18:00')
  await expect(list).toContainText('Booked')
  // The seed's 60 minutes each side of the event.
  await expect(list).toContainText('Setup and teardown included: 08:00–19:00')
})

test('9.1 AC5: a held request in the day list says "Held – pending" with its setup and teardown', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Seminar Room 2.1' }).click()
  await goToNovember2026(page)

  await dayButton(page, /25 November 2026/).click()

  const list = dayList(page, /25 Nov 2026/)
  await expect(list).toContainText('Nimbus Developer Conference')
  await expect(list).toContainText('13:00–18:00')
  await expect(list).toContainText('Held – pending')
  await expect(list).toContainText('Setup and teardown included: 12:30–18:15')
})

test('9.1 AC5: a closure in the day list shows its reason', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Seminar Room 2.1' }).click()
  await goToNovember2026(page)

  await dayButton(page, /2 November 2026/).click()

  const list = dayList(page, /2 Nov 2026/)
  await expect(list).toContainText('Annual air-con servicing')
  await expect(list).toContainText('Closed – Maintenance')
})

test('9.1 AC5: a day opens and closes from the keyboard', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()
  await goToNovember2026(page)

  const button = dayButton(page, /25 November 2026/)
  await button.focus()
  await expect(button).toBeFocused()

  await page.keyboard.press('Enter')
  await expect(button).toHaveAttribute('aria-expanded', 'true')
  await expect(dayList(page, /25 Nov 2026/)).toBeVisible()

  await page.keyboard.press('Space')
  await expect(button).toHaveAttribute('aria-expanded', 'false')
  await expect(dayList(page, /25 Nov 2026/)).toHaveCount(0)
})

test('9.1 AC5: opening a day does not move the month grid', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()
  await goToNovember2026(page)

  const grid = page.getByLabel('Calendar for November 2026')
  const button = dayButton(page, /25 November 2026/)

  // Relative to the page, not the window: pressing a button may scroll it into view.
  async function pageBox(locator: Locator) {
    const box = await locator.boundingBox()
    const scrollY = await page.evaluate(() => window.scrollY)
    return box && { ...box, y: box.y + scrollY }
  }
  const gridBefore = await pageBox(grid)
  const buttonBefore = await pageBox(button)

  await button.click()
  await expect(dayList(page, /25 Nov 2026/)).toBeVisible()

  // The list is a panel below the grid, so neither the grid nor the pressed cell changes place
  // or size.
  expect(await pageBox(grid)).toEqual(gridBefore)
  expect(await pageBox(button)).toEqual(buttonBefore)
})

test('9.1 AC10: previous and next close an open day and keep the calendar working', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()
  await goToNovember2026(page)
  await dayButton(page, /25 November 2026/).click()
  await expect(dayList(page, /25 Nov 2026/)).toBeVisible()

  const section = availabilitySection(page)
  await section.getByRole('button', { name: '← Prev' }).click()

  await expect(page.getByText('October 2026')).toBeVisible()
  await expect(dayList(page, /25 Nov 2026/)).toHaveCount(0)
  await expect(section.getByRole('button', { name: 'Next →' })).toBeVisible()

  // Back in November the booking is still there, and its day opens again.
  await section.getByRole('button', { name: 'Next →' }).click()
  await expect(page.getByText('Loading availability…')).toHaveCount(0)
  await dayButton(page, /25 November 2026/).click()
  await expect(dayList(page, /25 Nov 2026/)).toContainText('Nimbus Developer Conference')
})

/** One window as `GET /venues/{id}/calendar` returns it (backend/app/venues/schemas.py). */
interface StubWindow {
  starts_at: string
  ends_at: string
  event_starts_at: string | null
  event_ends_at: string | null
  reason: string
  label: string
}

/**
 * Answers every calendar fetch with `windowsFor(month)`, `month` being "YYYY-MM" of the range
 * asked for, so a test does not depend on which month the page happens to open on. Stubs only
 * the `fetch`, with CORS headers (tests/CLAUDE.md). Register before the page requests it.
 */
async function stubCalendar(page: Page, windowsFor: (month: string) => StubWindow[]) {
  await page.route(
    (url) => /\/venues\/[^/]+\/calendar$/.test(url.pathname),
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      const startsAt = new URL(route.request().url()).searchParams.get('starts_at') ?? ''
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(windowsFor(startsAt.slice(0, 7))),
        headers: corsHeaders(route.request()),
      })
    },
  )
}

/** A Singapore-time moment, as the API writes it. */
function at(month: string, day: number, time: string) {
  return `${month}-${String(day).padStart(2, '0')}T${time}:00+08:00`
}

/** A window with no setup or teardown: the event's own period is the whole of it. */
function plainWindow(
  month: string,
  day: number,
  [from, to]: [string, string],
  fields: Pick<StubWindow, 'reason' | 'label'>,
): StubWindow {
  return {
    starts_at: at(month, day, from),
    ends_at: at(month, day, to),
    event_starts_at: at(month, day, from),
    event_ends_at: at(month, day, to),
    ...fields,
  }
}

test('9.1 AC7/AC8: several events on one day are all listed in time order, back-to-back apart', async ({
  page,
}) => {
  // Given out of order on purpose. The evening one runs 16:00-18:00 with 30 minutes of setup.
  await stubCalendar(page, (month) => [
    {
      ...plainWindow(month, 10, ['16:00', '18:00'], {
        reason: 'BOOKED',
        label: 'Stub Evening Reception',
      }),
      starts_at: at(month, 10, '15:30'),
    },
    plainWindow(month, 10, ['12:00', '14:00'], { reason: 'HELD', label: 'Stub Midday Briefing' }),
    plainWindow(month, 10, ['09:00', '12:00'], {
      reason: 'BOOKED',
      label: 'Stub Morning Workshop',
    }),
  ])
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  const section = availabilitySection(page)
  await expect(dayButton(page)).toHaveCount(1)
  // The cell shows two entries and says there is another; the list below has all three.
  await expect(section.getByText('+1 more')).toBeVisible()
  await dayButton(page).click()

  const items = dayList(page, /10 \w+ \d{4}/).getByRole('listitem')
  await expect(items).toHaveText([
    /09:00–12:00.*Stub Morning Workshop.*Booked/s,
    /12:00–14:00.*Stub Midday Briefing.*Held – pending/s,
    /16:00–18:00.*Stub Evening Reception.*Booked.*Setup and teardown included: 15:30–18:00/s,
  ])
})

test('9.1 AC9: a multi-day booking is listed on every day it covers, with that day’s part', async ({
  page,
}) => {
  // The event runs the 10th 20:00 to the 12th 10:00, with a whole day of setup and of teardown.
  await stubCalendar(page, (month) => [
    {
      starts_at: at(month, 9, '20:00'),
      ends_at: at(month, 13, '10:00'),
      event_starts_at: at(month, 10, '20:00'),
      event_ends_at: at(month, 12, '10:00'),
      reason: 'BOOKED',
      label: 'Stub Multi-day Summit',
    },
  ])
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  // One cell on each of the five days the held period touches.
  await expect(dayButton(page)).toHaveCount(5)

  const list = dayList(page, /\d+ \w+ \d{4}/)
  await dayButton(page, /^9 /).click()
  await expect(list).toContainText('20:00–24:00')
  await expect(list).toContainText('Setup and teardown only')
  // The event is not on this day, so the row does not call it booked.
  await expect(list).not.toContainText('Booked')
  await dayButton(page, /^10 /).click()
  await expect(list).toContainText('20:00–24:00')
  await dayButton(page, /^11 /).click()
  await expect(list).toContainText('00:00–24:00')
  await dayButton(page, /^12 /).click()
  await expect(list).toContainText('00:00–10:00')
  await dayButton(page, /^13 /).click()
  await expect(list).toContainText('00:00–10:00')
  await expect(list).toContainText('Setup and teardown only')
  await expect(list).not.toContainText('Booked')
})

test('9.1 AC9: a held request on a day only its setup reaches says held, not booked', async ({
  page,
}) => {
  // Held from the 11th 20:00; the event itself is on the 12th, 10:00-11:00.
  await stubCalendar(page, (month) => [
    {
      starts_at: at(month, 11, '20:00'),
      ends_at: at(month, 12, '11:00'),
      event_starts_at: at(month, 12, '10:00'),
      event_ends_at: at(month, 12, '11:00'),
      reason: 'HELD',
      label: 'Stub Held Workshop',
    },
  ])
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  const list = dayList(page, /\d+ \w+ \d{4}/)
  await dayButton(page, /^11 /).click()
  await expect(list).toContainText('Held – pending, setup and teardown only')
  await expect(list).not.toContainText('Booked')
  await dayButton(page, /^12 /).click()
  await expect(list).toContainText('10:00–11:00')
  await expect(list).toContainText('Held – pending')
})

// D1: Venue Staff have no other route to a calendar than the shared catalogue (f8.1.1), and
// Technical Support keeps calendar access, so both are shown reaching it the way they would.
for (const viewer of [
  { who: 'Venue Staff', email: ACCOUNTS.venueStaff },
  { who: 'Technical Support', email: ACCOUNTS.techSupport },
]) {
  test(`9.1 AC13: ${viewer.who} open a venue from the catalogue and see its calendar`, async ({
    page,
  }) => {
    await signIn(page, viewer.email)
    await page.goto('/venues')
    await page.getByRole('link', { name: 'Grand Hall' }).click()

    await goToNovember2026(page)

    await expect(availabilitySection(page)).toBeVisible()
    await expect(page.getByText('Nimbus Developer Conference')).toBeVisible()
  })
}

// D3: the button's name carries what its cell shows, not just how many items there are.
test('9.1 AC5: a day’s button is named with its date and what the cell shows, overflow included', async ({
  page,
}) => {
  await stubCalendar(page, (month) => [
    plainWindow(month, 10, ['09:00', '12:00'], { reason: 'BOOKED', label: 'Stub Morning Workshop' }),
    plainWindow(month, 10, ['12:00', '14:00'], { reason: 'HELD', label: 'Stub Midday Briefing' }),
    plainWindow(month, 10, ['16:00', '18:00'], { reason: 'BOOKED', label: 'Stub Evening Reception' }),
  ])
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  // The cell shows the first two entries and "+1 more"; the name says the same.
  await expect(dayButton(page)).toHaveAccessibleName(
    /^10 \w+ \d{4}, 3 items: Stub Morning Workshop; Held – Stub Midday Briefing; \+1 more$/,
  )
})

// D2: the list opens under the grid and legend, which on a short screen is below the fold.
test('9.1 AC5: opening a day brings its list into view and leaves focus on the day', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 400 })
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()
  await goToNovember2026(page)

  const button = dayButton(page, /25 November 2026/)
  await button.click()

  await expect(dayList(page, /25 Nov 2026/)).toBeInViewport({ ratio: 1 })
  // Focus stays on the button, so pressing it again still closes the list.
  await expect(button).toBeFocused()
})
