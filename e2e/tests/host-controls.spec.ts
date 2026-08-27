import { expect, test, type Page } from "@playwright/test";
import {
  createAccount,
  expectInMeeting,
  fetchMeeting,
  joinFromPreJoin,
  meetingNumberFromUrl,
  signIn,
} from "./helpers";

/**
 * Flow 3 - the controls only the host has.
 *
 * Every assertion here is made on the *other* participant's screen. A host
 * control that only updated the host's own UI would pass a single-page test
 * and be useless in a real meeting, so the guest page is the witness.
 */

/** Host in a fresh meeting with an admitted guest. Returns both pages. */
async function meetingWithGuest(browser: any, page: Page, request: any) {
  const host = await createAccount(request, "Helena Host");
  await signIn(page.context(), host.token);

  await page.goto("/");
  await page.getByRole("button", { name: "New Meeting" }).click();
  await page.waitForURL(/\/meeting\/\d+/);
  const number = meetingNumberFromUrl(page.url());
  await joinFromPreJoin(page);
  await expectInMeeting(page);

  const meeting = await fetchMeeting(request, host.token, number);

  const guestContext = await browser.newContext();
  const guest = await guestContext.newPage();
  await guest.goto(`/j/${number}?pwd=${meeting.passcode}`);
  await guest.waitForURL(/\/meeting\/\d+/);
  await joinFromPreJoin(guest, "Gwen Guest");

  // The arrival shows up twice - in the yellow banner and in a toast - so
  // match the banner's own button rather than the name, which is ambiguous.
  const admitAll = page.getByRole("button", { name: "Admit all" });
  await expect(admitAll).toBeVisible({ timeout: 30_000 });
  await admitAll.click();
  await expectInMeeting(guest);

  return { host, number, passcode: meeting.passcode, guest, guestContext };
}

test.describe("host controls", () => {
  test("the host can mute a participant", async ({ browser, page, request }) => {
    const { guest, guestContext } = await meetingWithGuest(browser, page, request);

    // The guest starts able to mute themselves, which is the control we expect
    // to flip once the host acts.
    await expect(guest.getByRole("button", { name: "Mute" })).toBeVisible();

    await page.getByRole("button", { name: "Participants" }).click();
    await page.getByRole("button", { name: "Manage participant" }).first().click();
    // Scoped to the dropdown: the control bar has its own "Mute" button, and
    // an unscoped match muted the host instead - which looks identical in a
    // screenshot and proves nothing about the host control.
    await page
      .locator("div.w-44")
      .getByRole("button", { name: "Mute", exact: true })
      .click();

    // The witness: the guest's own control bar now offers to *unmute*.
    await expect(guest.getByRole("button", { name: "Unmute" })).toBeVisible({
      timeout: 30_000,
    });

    await guestContext.close();
  });

  test("the host can remove a participant", async ({ browser, page, request }) => {
    const { guest, guestContext } = await meetingWithGuest(browser, page, request);

    await page.getByRole("button", { name: "Participants" }).click();
    await page.getByRole("button", { name: "Manage participant" }).first().click();
    await page
      .locator("div.w-44")
      .getByRole("button", { name: "Remove", exact: true })
      .click();

    await expect(guest.getByText("You were removed from the meeting")).toBeVisible({
      timeout: 30_000,
    });

    await guestContext.close();
  });

  test("locking the meeting keeps the next guest out", async ({ browser, page, request }) => {
    const { number, passcode, guestContext } = await meetingWithGuest(
      browser,
      page,
      request
    );

    // Lock it from the host's security menu, the way a host actually would.
    await page.getByRole("button", { name: "Security" }).click();
    await page.getByRole("button", { name: "security: Lock meeting" }).click();

    // A second guest, with a valid passcode, is now refused at the door.
    const latecomerContext = await browser.newContext();
    const latecomer = await latecomerContext.newPage();
    await latecomer.goto(`/j/${number}?pwd=${passcode}`);
    await latecomer.waitForURL(/\/meeting\/\d+/);
    await joinFromPreJoin(latecomer, "Late Larry");

    await expect(latecomer.getByText(/locked by the host/i)).toBeVisible({
      timeout: 30_000,
    });
    await expect(latecomer.getByRole("button", { name: "Participants" })).toHaveCount(0);

    await latecomerContext.close();
    await guestContext.close();
  });

  test("a host setting reaches the guest's own UI", async ({ browser, page, request }) => {
    const { guest, guestContext } = await meetingWithGuest(browser, page, request);

    await expect(guest.getByRole("button", { name: "React" })).toBeEnabled();

    await page.getByRole("button", { name: "Security" }).click();
    await page.getByRole("button", { name: "security: React" }).click();

    // The guest's react button is disabled by the host's toggle, not by the
    // guest's own page state - which is the whole point of the broadcast.
    await expect(guest.getByRole("button", { name: "React" })).toBeDisabled({
      timeout: 30_000,
    });

    await guestContext.close();
  });

  test("the guest has no host controls at all", async ({ browser, page, request }) => {
    const { guest, guestContext } = await meetingWithGuest(browser, page, request);

    // Not a security assertion - the server enforces that, and the pytest
    // suite covers it. This is the UI half: the guest is never shown a lever
    // that the backend would refuse anyway.
    await expect(guest.getByRole("button", { name: "Security" })).toHaveCount(0);

    await guest.getByRole("button", { name: "Participants" }).click();
    await expect(guest.getByRole("button", { name: "Manage participant" })).toHaveCount(0);

    await guestContext.close();
  });

  test("the host can end the meeting for everyone", async ({ browser, page, request }) => {
    const { guest, guestContext } = await meetingWithGuest(browser, page, request);

    // The host's hangup button says "End" and opens a menu; a guest's says
    // "Leave" and acts immediately.
    await page.getByRole("button", { name: "End" }).click();
    await page.getByRole("button", { name: "End meeting for all" }).click();

    await expect(guest.getByText("This meeting has ended")).toBeVisible({
      timeout: 30_000,
    });

    await guestContext.close();
  });
});
