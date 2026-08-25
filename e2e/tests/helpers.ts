import { expect, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";

export const API_BASE = "http://127.0.0.1:8111";

/**
 * Unique per call, so a run never collides with a previous one's accounts even
 * if the throwaway database somehow survives. `signup` is the one place that
 * 409s on a duplicate, and that failure looks nothing like its cause.
 */
let seq = 0;
export function uniqueEmail(prefix = "e2e"): string {
  seq += 1;
  return `${prefix}-${Date.now()}-${seq}@example.com`;
}

export const PASSWORD = "hunter2222";

export type Account = { name: string; email: string; password: string; token: string };

/**
 * Create a verified account over the API and hand back its token.
 *
 * The signup *screen* is covered properly by signup-otp.spec.ts. Driving that
 * UI again as setup for every other flow would triple the runtime and make an
 * unrelated signup regression fail all three files, so the flows that merely
 * need "a logged-in host" take this door instead.
 */
export async function createAccount(
  request: APIRequestContext,
  name = "E2E Host"
): Promise<Account> {
  const email = uniqueEmail();

  const requested = await request.post(`${API_BASE}/auth/signup/request-otp`, {
    data: { name, email, password: PASSWORD },
  });
  expect(requested.ok(), await requested.text()).toBeTruthy();

  const { dev_code: code } = await requested.json();
  expect(code, "the backend must be in dev mode for the OTP to come back inline").toBeTruthy();

  const verified = await request.post(`${API_BASE}/auth/signup/verify`, {
    data: { email, code },
  });
  expect(verified.ok(), await verified.text()).toBeTruthy();

  const { token } = await verified.json();
  return { name, email, password: PASSWORD, token };
}

/**
 * Put a token where the app looks for it, before any page script runs.
 *
 * addInitScript rather than a plain evaluate: the dashboard is behind
 * AuthGuard, so a token written after navigation arrives too late and the
 * guard has already bounced the page to /login.
 */
export async function signIn(context: BrowserContext, token: string): Promise<void> {
  await context.addInitScript((value) => {
    window.localStorage.setItem("parley_token", value);
  }, token);
}

/** The host's own view of a meeting, including the passcode guests need. */
export async function fetchMeeting(request: APIRequestContext, token: string, number: string) {
  const res = await request.get(`${API_BASE}/api/meetings/${number}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.json();
}

/**
 * Walk a page through the pre-join screen into the room.
 *
 * Waits for the button to leave its "Preparing devices..." state first: it is
 * disabled until getUserMedia settles, and clicking early is a no-op that only
 * shows up later as a timeout on something unrelated.
 */
export async function joinFromPreJoin(page: Page, displayName?: string): Promise<void> {
  // Name first, then wait for the button. The order matters for guests: an
  // anonymous joiner starts with an empty name field and the button stays
  // disabled until it is filled, so waiting for "enabled" before typing waits
  // forever - on a screen that otherwise looks completely ready.
  const nameField = page.locator("#pj-name");
  await expect(nameField).toBeVisible({ timeout: 30_000 });
  if (displayName !== undefined) {
    await nameField.fill(displayName);
  }
  await expect(nameField).not.toHaveValue("");

  // The label is "Preparing devices..." until getUserMedia settles, so this
  // locator only resolves once the camera is ready.
  const joinButton = page.getByRole("button", { name: "Join now" });
  await expect(joinButton).toBeEnabled({ timeout: 30_000 });
  await joinButton.click();
}

/** In the room and connected - the status pill is the app's own readiness signal. */
export async function expectInMeeting(page: Page): Promise<void> {
  await expect(page.getByRole("button", { name: "Participants" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("Live", { exact: true })).toBeVisible({ timeout: 30_000 });
}

/** The meeting number out of /meeting/<number>, which is where the app puts it. */
export function meetingNumberFromUrl(url: string): string {
  const match = /\/meeting\/(\d+)/.exec(url);
  if (!match) throw new Error(`no meeting number in ${url}`);
  return match[1];
}
