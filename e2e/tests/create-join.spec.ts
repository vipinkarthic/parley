import { expect, test, type Browser } from "@playwright/test";
import {
  createAccount,
  expectInMeeting,
  fetchMeeting,
  joinFromPreJoin,
  meetingNumberFromUrl,
  signIn,
} from "./helpers";

/**
 * Flow 2 - a host starts a meeting and a guest gets into it.
 *
 * The guest goes through the waiting room rather than around it, because the
 * waiting room defaults to ON: this is the path a real invite link actually
 * takes, and a test that disabled it first would be testing a configuration
 * nobody ships with.
 */
test.describe("create -> join", () => {
  test("a guest joins from the invite link once the host admits them", async ({
    browser,
    page,
    request,
  }) => {
    const host = await createAccount(request, "Hattie Host");
    await signIn(page.context(), host.token);

    // --- the host starts the meeting ------------------------------------
    await page.goto("/");
    await page.getByRole("button", { name: "New Meeting" }).click();
    await page.waitForURL(/\/meeting\/\d+/);

    const number = meetingNumberFromUrl(page.url());
    await joinFromPreJoin(page);
    await expectInMeeting(page);

    // --- the guest follows the invite link -------------------------------
    const meeting = await fetchMeeting(request, host.token, number);
    expect(meeting.passcode, "the host is shown the passcode").toBeTruthy();

    const guestContext = await browser.newContext();
    const guest = await guestContext.newPage();

    // The real invite link: /j/<number>?pwd=<passcode>, which redirects into
    // the meeting with the passcode already supplied.
    await guest.goto(`/j/${number}?pwd=${meeting.passcode}`);
    await guest.waitForURL(/\/meeting\/\d+/);

    await joinFromPreJoin(guest, "Gus Guest");

    // The waiting room is on by default, so the guest is held.
    await expect(
      guest.getByText("Please wait, the meeting host will let you in soon")
    ).toBeVisible({ timeout: 30_000 });

    // --- the host lets them in -------------------------------------------
    // first(): the same sentence appears in the banner and in a toast.
    await expect(
      page.getByText(/Gus Guest.*is waiting to join/).first()
    ).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Admit all" }).click();

    await expectInMeeting(guest);

    // Both sides now agree there are two people in the room.
    await expect(page.getByRole("button", { name: "Participants" })).toContainText("2");
    await expect(guest.getByRole("button", { name: "Participants" })).toContainText("2");

    await guestContext.close();
  });

  test("a guest with the wrong passcode is refused", async ({ browser, page, request }) => {
    const host = await createAccount(request, "Gatekeeper Host");
    await signIn(page.context(), host.token);

    await page.goto("/");
    await page.getByRole("button", { name: "New Meeting" }).click();
    await page.waitForURL(/\/meeting\/\d+/);
    const number = meetingNumberFromUrl(page.url());
    await joinFromPreJoin(page);
    await expectInMeeting(page);

    const guestContext = await browser.newContext();
    const guest = await guestContext.newPage();
    await guest.goto(`/meeting/${number}?pwd=000000`);

    await joinFromPreJoin(guest, "Wrong Passcode");
    await expect(guest.getByText(/Incorrect meeting passcode/i)).toBeVisible({
      timeout: 30_000,
    });
    await expect(guest.getByRole("button", { name: "Participants" })).toHaveCount(0);

    await guestContext.close();
  });

  test("an unknown meeting number does not open a room", async ({ page, request }) => {
    const host = await createAccount(request, "Lost Host");
    await signIn(page.context(), host.token);

    await page.goto("/meeting/00000000000");
    await expect(page.getByText(/this meeting isn.t available/i)).toBeVisible({
      timeout: 30_000,
    });
  });
});
