"""Capture the README screenshots from a running Parley.

1440x900, light mode, viewport only - no OS chrome, no real email in frame.
Uses the demo accounts, so nothing personal ends up in a committed image.

    python tools/screenshots.py --out ../docs/screenshots

Chrome's synthetic camera is a bright green rolling pattern, and a shot of it
looks broken rather than like a video call. So the in-meeting shots are taken
with **cameras off**, which renders the avatar tiles - a real state of the
product, and one that photographs well. Retake them with real faces if you
want faces.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import urllib.parse
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "tools"))

import loadtest as L  # noqa: E402

WIDTH, HEIGHT = 1440, 900


async def expect(chrome: L.Chrome, js: str, what: str) -> bool:
    """Assert the page really is what we think before photographing it.

    Learned the hard way: without this the script cheerfully wrote the login
    page to dashboard.png, and the only reason anyone noticed was that the
    PNG was three times the expected size.
    """
    if await wait_for(chrome, js, tries=40):
        return True
    text = (await chrome.eval(
        "(document.body ? document.body.innerText : '').slice(0, 90)",
        await_promise=False,
    )) or ""
    print(f"  !! expected {what}; page says: {text!r}")
    return False


async def shot(chrome: L.Chrome, path: Path, full: bool = False) -> None:
    result = await chrome.call(
        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": full}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(result["data"]))
    kb = path.stat().st_size / 1024
    print(f"  wrote {path.name:<18} {kb:>7.0f} KB")


async def setup(chrome: L.Chrome) -> None:
    await chrome.call(
        "Emulation.setDeviceMetricsOverride",
        {"width": WIDTH, "height": HEIGHT, "deviceScaleFactor": 2,
         "mobile": False},
    )
    # Light mode explicitly - the machine's own preference must not leak into
    # a committed image.
    await chrome.call(
        "Emulation.setEmulatedMedia",
        {"features": [{"name": "prefers-color-scheme", "value": "light"}]},
    )


async def wait_for(chrome: L.Chrome, js: str, tries: int = 80) -> bool:
    for _ in range(tries):
        if await chrome.eval(js, await_promise=False):
            return True
        await asyncio.sleep(0.25)
    return False


async def login(chrome: L.Chrome, web: str, email: str, password: str) -> bool:
    await chrome.navigate(f"{web}/login")
    await wait_for(chrome, "!!document.querySelector('input[type=email]')")
    # React has to finish hydrating before the inputs will keep a value set
    # from outside. Without this the native setter writes, React re-renders
    # from its own empty state, and the form submits blank - which is exactly
    # how dashboard.png ended up being a screenshot of the login page.
    await asyncio.sleep(2.5)
    await chrome.eval(
        f"""(() => {{
          const set = (el, v) => {{
            const proto = Object.getPrototypeOf(el);
            Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
          }};
          set(document.querySelector('input[type=email]'), {json.dumps(email)});
          set(document.querySelector('input[type=password]'), {json.dumps(password)});
          const b = Array.from(document.querySelectorAll('button'))
            .find(x => /sign in|log in/i.test(x.textContent || ''));
          if (b) b.click();
          return true;
        }})()""",
        await_promise=False,
    )
    ok = await wait_for(chrome, "!location.pathname.startsWith('/login')", tries=60)
    await asyncio.sleep(2.5)
    return ok


async def main_async(args) -> None:
    out = Path(args.out).resolve()
    print(f"capturing to {out} at {WIDTH}x{HEIGHT} @2x, light mode\n")

    token = L._post(args.api, "/auth/login",
                    {"email": args.email, "password": args.password})["token"]

    # POST /meetings/instant reuses the host's existing active instant room,
    # so a previous run's topic ("Load test") would survive into the shot.
    # End it first, then the create call really creates.
    try:
        existing = L._request(args.api, "/api/meetings", {}, token, "GET")
    except SystemExit:
        existing = []
    for m in existing if isinstance(existing, list) else []:
        if m.get("meeting_type") == "instant" and m.get("status") != "ended":
            try:
                L._post(args.api, f"/api/meetings/{m['meeting_number']}/end",
                        {}, token=token)
            except SystemExit:
                pass

    meeting = L._post(args.api, "/api/meetings/instant",
                      {"topic": args.topic}, token=token)
    L._patch(args.api, f"/api/meetings/{meeting['meeting_number']}/settings",
             {"waiting_room": False, "join_before_host": True}, token=token)
    number = meeting["meeting_number"]
    passcode = meeting.get("passcode") or ""
    print(f"  meeting: {number}  topic: {meeting.get('topic')!r}")

    main = L.Chrome("shot", 9700, headless=True, window=f"{WIDTH},{HEIGHT}")
    extras: list[L.Chrome] = []
    try:
        main.launch()
        main.wait_ready()
        await main.attach()
        await setup(main)

        # --- signup form, then the OTP step --------------------------------
        # In its own browser. Pushing through signup in the same instance
        # left the session on an auth screen, and the "dashboard" shot that
        # followed was actually the signup page again - caught only because
        # the PNG was suspiciously the same size.
        signup = L.Chrome("signup", 9705, headless=True,
                          window=f"{WIDTH},{HEIGHT}")
        try:
            signup.launch()
            signup.wait_ready()
            await signup.attach()
            await setup(signup)
            await signup.navigate(f"{args.web}/signup")
            await wait_for(signup, "!!document.querySelector('input')")
            await asyncio.sleep(2.5)   # hydration; see login()
            await shot(signup, out / "signup.png")

            # Email is disabled in dev, so the code comes back in the response
            # body and nothing is ever sent.
            import time as _t
            fake = f"jane.doe+{int(_t.time())}@example.com"
            await signup.eval(
                f"""(() => {{
                  const set = (el, v) => {{
                    const proto = Object.getPrototypeOf(el);
                    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                  }};
                  const ins = document.querySelectorAll('input');
                  set(ins[0], 'Jane Doe');
                  set(ins[1], {json.dumps(fake)});
                  set(ins[2], 'hunter2222');
                  const b = Array.from(document.querySelectorAll('button'))
                    .find(x => /continue/i.test(x.textContent||''));
                  if (b) b.click();
                  return true;
                }})()""",
                await_promise=False,
            )
            # The OTP step is the only screen with a 6-character input.
            # Matching on the word "verify" instead picks up "Secure email
            # verification" in the marketing panel, which is on both screens.
            reached = await wait_for(
                signup, "!!document.querySelector('input[maxlength=\"6\"]')",
                tries=80,
            )
            await asyncio.sleep(2.0)
            if reached:
                await shot(signup, out / "signup-otp.png")
            else:
                print("  !! never reached the OTP step; skipped signup-otp.png")
        finally:
            await signup.close()

        # --- dashboard ------------------------------------------------------
        if not await login(main, args.web, args.email, args.password):
            print("  !! login did not navigate away from /login")
        await asyncio.sleep(2.0)
        if await expect(main,
                        "/good (morning|afternoon|evening)/i.test("
                        "document.body.innerText||'')",
                        "the dashboard"):
            await shot(main, out / "dashboard.png")

        # --- schedule modal -------------------------------------------------
        await main.eval(
            """(() => {
                 const nodes = Array.from(
                   document.querySelectorAll('button, a, [role=button], div'));
                 // The card's text is "SchedulePlan for later", so a \b
                 // after Schedule never matches - there is no word boundary
                 // between "Schedule" and "Plan".
                 const b = nodes.find(x =>
                   /^Schedule/i.test((x.textContent||'').trim()) &&
                   x.getBoundingClientRect().width > 100);
                 if (!b) return false;
                 b.click();
                 return true;
               })()""",
            await_promise=False,
        )
        # Confirm the modal is really open rather than trusting the click.
        if await wait_for(
            main, "/schedule a meeting/i.test(document.body.innerText||'')",
            tries=20,
        ):
            await asyncio.sleep(1.5)
            await shot(main, out / "schedule.png")
        else:
            print("  !! schedule modal did not open; skipped schedule.png")

        # --- prejoin --------------------------------------------------------
        url = (f"{args.web}/meeting/{number}"
               f"?name={urllib.parse.quote('Demo One')}"
               f"&pwd={urllib.parse.quote(passcode)}")
        await main.navigate(url)
        await wait_for(
            main,
            "Array.from(document.querySelectorAll('button'))"
            ".some(b => /join now/i.test(b.textContent||'') && !b.disabled)",
        )
        # Camera off before the shot - see the module docstring.
        await main.eval(
            """(() => {
                 const btns = Array.from(document.querySelectorAll('button'));
                 const cam = btns.find(b => /camera|video/i.test(
                   (b.getAttribute('aria-label')||'') + (b.title||'')));
                 if (cam) { cam.click(); return true; }
                 return false;
               })()""",
            await_promise=False,
        )
        await asyncio.sleep(2.0)
        await shot(main, out / "prejoin.png")

        # --- in-meeting, three peers ---------------------------------------
        ok = await L.join_peer(main, args.web, number, passcode, "Demo One")
        if not ok:
            print("  !! main peer never reached the room; skipped meeting.png")
            return
        for i, name in enumerate(("Demo Two", "Demo Three")):
            c = L.Chrome(f"peer{i}", 9710 + i, headless=True,
                         window=f"{WIDTH},{HEIGHT}")
            c.launch()
            c.wait_ready()
            await c.attach()
            extras.append(c)
            await L.join_peer(c, args.web, number, passcode, name)
            await asyncio.sleep(1.0)

        print("  settling, then turning every camera off for the shot...")
        await asyncio.sleep(8)
        for c in [main] + extras:
            await c.eval(
                """(() => {
                     const b = Array.from(document.querySelectorAll('button'))
                       .find(x => /stop video/i.test(x.textContent||''));
                     if (b) { b.click(); return true; }
                     return false;
                   })()""",
                await_promise=False,
            )
        await asyncio.sleep(5)
        await shot(main, out / "meeting.png")
    finally:
        for c in extras:
            await c.close()
        await main.close()
        L.cleanup() if hasattr(L, 'cleanup') else None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--web", default="http://127.0.0.1:3200")
    p.add_argument("--api", default="http://127.0.0.1:8200")
    p.add_argument("--email", default="demo1@parley.app")
    p.add_argument("--password", default="demo1234")
    p.add_argument("--topic", default="Product Design Review",
                   help="meeting topic shown in the in-meeting shots")
    p.add_argument("--out", default=str(BACKEND_ROOT.parent / "docs" / "screenshots"))
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
