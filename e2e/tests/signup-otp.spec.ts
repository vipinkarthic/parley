import { expect, test } from "@playwright/test";
import { PASSWORD, uniqueEmail } from "./helpers";

/**
 * Flow 1 - signup through the emailed one-time code.
 *
 * The backend runs with empty SMTP credentials, so it returns the code in the
 * response body and the page prints it. That is what makes this flow testable
 * without a mail server; the test asserts the two agree, so a change that
 * stopped surfacing the code would fail here rather than silently locking
 * every later signup test out of its own account.
 */
test.describe("signup -> OTP", () => {
  test("a new account is created by verifying the emailed code", async ({ page }) => {
    const email = uniqueEmail("signup");
    const name = "Otto Tester";

    // The code, read off the wire, so the assertion below is independent of
    // how the page chooses to render it.
    const otpResponse = page.waitForResponse(
      (r) => r.url().includes("/auth/signup/request-otp") && r.status() === 200
    );

    await page.goto("/signup");
    await expect(page.getByRole("heading", { name: "Get started with Parley" })).toBeVisible();

    await page.locator("#name").fill(name);
    await page.locator("#email").fill(email);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: "Continue" }).click();

    const { dev_code: code } = await (await otpResponse).json();
    expect(code, "dev mode should return the code inline").toMatch(/^\d{6}$/);

    await expect(page.getByRole("heading", { name: "Verify your email" })).toBeVisible();
    await expect(page.getByText(`Dev code:`)).toBeVisible();
    await expect(page.locator("span.tracking-widest")).toHaveText(code);

    await page.getByPlaceholder("••••••").fill(code);
    await page.getByRole("button", { name: "Verify & Create Account" }).click();

    // Verification lands on the dashboard, signed in as the new account.
    await page.waitForURL("**/");
    await expect(page.getByRole("heading", { name: new RegExp(name.split(" ")[0]) })).toBeVisible();
    await expect(page.getByRole("button", { name: "New Meeting" })).toBeVisible();
  });

  test("a wrong code is refused and the right one still works", async ({ page }) => {
    const email = uniqueEmail("signup-wrong");

    const otpResponse = page.waitForResponse(
      (r) => r.url().includes("/auth/signup/request-otp") && r.status() === 200
    );

    await page.goto("/signup");
    await page.locator("#name").fill("Wrong Code");
    await page.locator("#email").fill(email);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: "Continue" }).click();

    const { dev_code: code } = await (await otpResponse).json();

    // A code that is the right shape but the wrong value.
    const wrong = code === "000000" ? "111111" : "000000";
    await page.getByPlaceholder("••••••").fill(wrong);
    await page.getByRole("button", { name: "Verify & Create Account" }).click();

    await expect(page.getByText(/Incorrect code/i)).toBeVisible();
    await expect(page).toHaveURL(/\/signup/);

    // The pending signup survives a bad guess, so the real code still lands.
    await page.getByPlaceholder("••••••").fill(code);
    await page.getByRole("button", { name: "Verify & Create Account" }).click();
    await page.waitForURL("**/");
    await expect(page.getByRole("button", { name: "New Meeting" })).toBeVisible();
  });

  test("the dashboard is not reachable without signing in", async ({ page }) => {
    await page.goto("/");
    await page.waitForURL(/\/login/);
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
  });
});
