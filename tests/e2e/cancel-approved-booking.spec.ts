/**
 * Story 12.8 - fe/be: cancel an approved venue booking.
 * AC1 the assigned coordinator cancels an approved booking from the event page, giving a reason;
 *     a blank reason is refused in the dialog before anything is sent.
 * AC2 the cancelled booking stays in the event's booking list as Cancelled, with its reason, and
 *     its requirement needs a venue again.
 * AC8 only the assigned coordinator is offered the cancel, and only on an approved booking. Every
 *     refusal the API makes is a backend case.
 * Every other AC (AC3-AC7, AC9) is a backend case:
 * backend/tests/bookings/test_cancel_approved_booking.py.
 *
 * The tests run in order on one seeded event, the riverside product briefing. The first two leave
 * its booking approved; the third cancels it for good and the fourth reads what that left. A retry
 * could only fail on the cancelled booking and hide the first trace: serial, no retries.
 */
import { expect, test, type Page } from "@playwright/test";
import { ACCOUNTS, EVENTS, signIn } from "./support";

test.describe.configure({ mode: "serial", retries: 0 });

const EVENT_NAME = "Riverside Product Briefing";
const CANCEL_BUTTON = "Cancel the booking of Seminar Room 2.1 for Main hall";
const REASON = "The client moved the briefing online.";
const REASON_REQUIRED = "Enter a reason for cancelling this booking.";
const CANCELLED_LINE = "Cancelled by the coordinator";
const CANCELLED_MESSAGE =
  "The coordinator cancelled this booking, so the venue is free for other events.";

function section(page: Page, name: string) {
  return page.getByRole("region", { name, exact: true });
}

async function openCancelDialog(page: Page) {
  await section(page, "Venue booking")
    .getByRole("button", { name: CANCEL_BUTTON })
    .click();
  return page.getByRole("dialog", { name: "Cancel this venue booking?" });
}

test("12.8 AC8: only the assigned coordinator is offered the cancel", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser);
  await page.goto(`/events/${EVENTS.productBriefing}`);
  await expect(page.getByRole("heading", { name: EVENT_NAME })).toBeVisible();
  await expect(page.getByRole("main")).toContainText("Seminar Room 2.1");
  await expect(page.getByRole("button", { name: CANCEL_BUTTON })).toHaveCount(
    0,
  );
});

test("12.8 AC1: a blank reason is refused before anything is sent", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator);
  await page.goto(`/events/${EVENTS.productBriefing}`);
  const sent: string[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/cancel")) sent.push(request.url());
  });

  const dialog = await openCancelDialog(page);
  await dialog.getByLabel("Reason for cancelling").fill("   ");
  await dialog.getByRole("button", { name: "Cancel booking" }).click();

  await expect(dialog.getByRole("alert")).toHaveText(REASON_REQUIRED);
  expect(sent).toEqual([]);
  await dialog.getByRole("button", { name: "Keep booking" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(section(page, "Venue booking")).toContainText("Approved");
});

test("12.8 AC1: the coordinator cancels an approved booking with a reason", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator);
  await page.goto(`/events/${EVENTS.productBriefing}`);

  const dialog = await openCancelDialog(page);
  await dialog.getByLabel("Reason for cancelling").fill(REASON);
  await dialog.getByRole("button", { name: "Cancel booking" }).click();

  await expect(dialog).toHaveCount(0);
  await expect(
    section(page, "Venue booking").getByText(CANCELLED_LINE, { exact: true }),
  ).toBeVisible();
});

test("12.8 AC2: the cancelled booking stays listed with its reason, and its requirement needs a venue again", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator);
  await page.goto(`/events/${EVENTS.productBriefing}`);

  const bookings = section(page, "Venue booking");
  await expect(bookings).toContainText("Seminar Room 2.1");
  await expect(bookings).toContainText("Cancelled");
  await expect(
    bookings.getByText(CANCELLED_LINE, { exact: true }),
  ).toBeVisible();
  await expect(bookings).toContainText(CANCELLED_MESSAGE);
  await expect(bookings.getByText("Reason", { exact: true })).toBeVisible();
  await expect(bookings).toContainText(REASON);
  // AC8: a booking no longer approved offers no cancel.
  await expect(
    bookings.getByRole("button", { name: CANCEL_BUTTON }),
  ).toHaveCount(0);

  await page.getByRole("link", { name: "Find a venue" }).click();
  const main = page
    .getByRole("region", { name: `Finding a venue for ${EVENT_NAME}` })
    .getByRole("listitem")
    .filter({ hasText: "Main hall" });
  await expect(main).toContainText("Needs a venue");
});
