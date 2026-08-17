"""Ramp real browsers into a real meeting and record where video collapses.

Phase 5. This is the harness that turns "the mesh caps out around five or six
peers" from a plausible sentence into a number with a command behind it.

What it actually does
---------------------
Launches N headless Chrome instances - real ones, not a simulation - each
with ``--use-fake-device-for-media-stream``, points them at the real Next.js
frontend, and lets them join a real meeting through the real prejoin screen.
So what is measured is the shipped code path: the app's own signalling, the
app's own paging, the app's own encoder caps.

Every peer connection is captured by wrapping ``RTCPeerConnection`` in the
page before any of the app's script runs, which means ``getStats()`` is
available without the application exposing anything for the benefit of a
benchmark.

What it measures, per rung of the ramp
--------------------------------------
* **uplink** - outbound-rtp video bitrate, summed per peer. This is the
  number the mesh punishes: every participant uploads one copy of their
  camera per other participant.
* **downlink** - inbound-rtp video bitrate per peer.
* **sent resolution and framerate** - where "collapse" actually shows up.
  A mesh under strain does not stop; it quietly sends 160x120 at 4fps.
* **CPU** - summed over every Chrome process, from /proc.
* **active video streams** - how many outbound video tracks are actually
  live, which is what paging is supposed to reduce.

The honest caveat, stated here rather than buried
-------------------------------------------------
**All N peers run on this one machine.** That measures "one laptop running N
participants", not "N laptops running one each". Two consequences, and they
point in opposite directions:

* The **bitrate** figures transfer directly. A peer's uplink does not depend
  on where the other peers are running.
* The **CPU** figure does not. A real participant pays for one encode set
  and N-1 decodes; this machine pays for all N of both. Total CPU here is
  therefore an upper bound on a real participant's load, and per-peer CPU is
  the more transferable number.

Usage
-----
    python tools/loadtest.py --ramp 2,4,6,8,10,12 --hold 25
    python tools/loadtest.py --ramp 6 --hold 20 --keep-open   # to eyeball it
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

CHROME_CANDIDATES = (
    "google-chrome-stable",
    "google-chrome",
    "chromium",
    "chromium-browser",
)

# Injected before any application script. Wrapping the constructor is how the
# harness reaches the peer connections without the app having to export them
# for it - a debug hook in shipped code would be a worse trade.
INSTRUMENT = r"""
(() => {
  const Original = window.RTCPeerConnection;
  if (!Original || window.__parleyPcs) return;
  window.__parleyPcs = [];
  const Wrapped = function (...args) {
    const pc = new Original(...args);
    window.__parleyPcs.push(pc);
    return pc;
  };
  Wrapped.prototype = Original.prototype;
  Object.setPrototypeOf(Wrapped, Original);
  window.RTCPeerConnection = Wrapped;
  window.webkitRTCPeerConnection = Wrapped;
})();
"""

# Runs in the page. Returns one flat object per sample; the deltas are done
# on this side so the page does not have to remember anything.
COLLECT = r"""
(async () => {
  const pcs = window.__parleyPcs || [];
  const out = {
    pcs: pcs.length,
    connected: 0,
    outVideo: [],
    inVideo: [],
  };
  for (const pc of pcs) {
    if (pc.connectionState === "connected") out.connected++;
    let report;
    try { report = await pc.getStats(); } catch { continue; }
    report.forEach((s) => {
      if (s.type === "outbound-rtp" && s.kind === "video") {
        out.outVideo.push({
          id: s.id,
          bytes: s.bytesSent || 0,
          frames: s.framesEncoded || 0,
          fps: s.framesPerSecond || 0,
          w: s.frameWidth || 0,
          h: s.frameHeight || 0,
          active: !!s.active,
          limitation: s.qualityLimitationReason || "none",
        });
      }
      if (s.type === "inbound-rtp" && s.kind === "video") {
        out.inVideo.push({
          id: s.id,
          bytes: s.bytesReceived || 0,
          fps: s.framesPerSecond || 0,
          w: s.frameWidth || 0,
          h: s.frameHeight || 0,
        });
      }
    });
  }
  return JSON.stringify(out);
})()
"""


# ---------------------------------------------------------------------------
# A very small CDP client
# ---------------------------------------------------------------------------

class Chrome:
    """One headless Chrome, driven over the DevTools protocol."""

    def __init__(self, label: str, port: int, headless: bool, window: str):
        self.label = label
        self.port = port
        self.headless = headless
        self.window = window
        self.profile = tempfile.mkdtemp(prefix=f"parley-load-{label}-")
        self.proc: subprocess.Popen | None = None
        self.ws = None
        self._msg_id = 0
        self._binary = self._find_chrome()

    @staticmethod
    def _find_chrome() -> str:
        for name in CHROME_CANDIDATES:
            path = shutil.which(name)
            if path:
                return path
        raise SystemExit(
            "no Chrome found. Install one of: " + ", ".join(CHROME_CANDIDATES)
        )

    def launch(self) -> None:
        args = [
            self._binary,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile}",
            # The whole point: a synthetic camera and microphone, and no
            # permission prompt to click.
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
            # The fake camera is a rolling pattern, which is *harder* to
            # encode than a talking head - so these numbers are pessimistic
            # rather than flattering.
            "--autoplay-policy=no-user-gesture-required",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--disable-dev-shm-usage",
            f"--window-size={self.window}",
            "about:blank",
        ]
        if self.headless:
            args.insert(1, "--headless=new")
        self.proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _http(self, path: str) -> list | dict:
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())

    def wait_ready(self, timeout: float = 30) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._http("/json/version")
                return
            except Exception:
                time.sleep(0.15)
        raise SystemExit(f"{self.label}: Chrome did not open a debug port")

    async def attach(self) -> None:
        import websockets

        targets = [
            t for t in self._http("/json") if t.get("type") == "page"
        ]
        if not targets:
            raise SystemExit(f"{self.label}: no page target")
        self.ws = await websockets.connect(
            targets[0]["webSocketDebuggerUrl"], max_size=None, open_timeout=20
        )
        await self.call("Page.enable")
        await self.call("Runtime.enable")
        await self.call(
            "Page.addScriptToEvaluateOnNewDocument", {"source": INSTRUMENT}
        )

    async def call(self, method: str, params: dict | None = None, timeout=30):
        self._msg_id += 1
        mid = self._msg_id
        await self.ws.send(
            json.dumps({"id": mid, "method": method, "params": params or {}})
        )
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            msg = json.loads(raw)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def navigate(self, url: str) -> None:
        await self.call("Page.navigate", {"url": url})

    async def eval(self, expression: str, await_promise: bool = True):
        result = await self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
        )
        return result.get("result", {}).get("value")

    def pids(self) -> list[int]:
        """This browser's whole process tree."""
        if self.proc is None:
            return []
        root = self.proc.pid
        found = [root]
        # /proc walk rather than psutil: one fewer dependency, and the
        # information is right there.
        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                try:
                    with open(f"/proc/{entry}/stat") as fh:
                        fields = fh.read().rsplit(")", 1)[1].split()
                    # field 3 after the comm is ppid (0-indexed: 1)
                    ppid = int(fields[1])
                except Exception:
                    continue
                if ppid == root:
                    found.append(int(entry))
        except Exception:
            pass
        # Chrome's children reparent, so also take anything whose profile
        # directory matches - that is the reliable marker.
        for entry in os.listdir("/proc"):
            if not entry.isdigit() or int(entry) in found:
                continue
            try:
                with open(f"/proc/{entry}/cmdline", "rb") as fh:
                    cmd = fh.read().decode("utf-8", "replace")
            except Exception:
                continue
            if self.profile in cmd:
                found.append(int(entry))
        return found

    def cpu_jiffies(self) -> int:
        total = 0
        for pid in self.pids():
            try:
                with open(f"/proc/{pid}/stat") as fh:
                    fields = fh.read().rsplit(")", 1)[1].split()
                total += int(fields[11]) + int(fields[12])  # utime + stime
            except Exception:
                continue
        return total

    def rss_kb(self) -> int:
        total = 0
        for pid in self.pids():
            try:
                with open(f"/proc/{pid}/status") as fh:
                    for line in fh:
                        if line.startswith("VmRSS:"):
                            total += int(line.split()[1])
                            break
            except Exception:
                continue
        return total

    async def close(self) -> None:
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
        if self.proc is not None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except Exception:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        shutil.rmtree(self.profile, ignore_errors=True)


# ---------------------------------------------------------------------------
# Meeting setup, through the real API
# ---------------------------------------------------------------------------

def _request(
    api: str, path: str, body: dict, token: str | None = None, method="POST"
) -> dict:
    req = urllib.request.Request(
        f"{api}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"{method} {path} -> {e.code}: {e.read().decode()[:300]}"
        )


def _post(api: str, path: str, body: dict, token: str | None = None) -> dict:
    return _request(api, path, body, token, "POST")


def _patch(api: str, path: str, body: dict, token: str | None = None) -> dict:
    return _request(api, path, body, token, "PATCH")


def create_meeting(api: str, email: str, password: str) -> dict:
    login = _post(api, "/auth/login", {"email": email, "password": password})
    token = login.get("token") or login["access_token"]
    meeting = _post(api, "/api/meetings/instant", {"topic": "Load test"},
                    token=token)

    # Settings are patched rather than passed to the create call, because
    # POST /instant *reuses* the host's existing active instant room and
    # ignores the settings on a reuse. First run of this harness created a
    # room, second run silently got the first room back with the waiting
    # room still on, and every peer sat in the lobby with no peer connection
    # while the summary reported a happy zero.
    #
    # Both flags are needed: every peer here is a guest and there is no
    # human to work the waiting room.
    settings = _patch(
        api,
        f"/api/meetings/{meeting['meeting_number']}/settings",
        {"waiting_room": False, "join_before_host": True},
        token=token,
    )
    got = settings.get("settings", settings)
    if got.get("waiting_room") is not False:
        raise SystemExit(f"could not turn the waiting room off: {got}")
    meeting["settings"] = got
    return meeting


# ---------------------------------------------------------------------------
# One rung of the ramp
# ---------------------------------------------------------------------------

async def join_peer(
    chrome: Chrome, web: str, number: str, passcode: str, name: str
) -> bool:
    url = (
        f"{web}/meeting/{number}"
        f"?name={urllib.parse.quote(name)}&pwd={urllib.parse.quote(passcode)}"
    )
    await chrome.navigate(url)

    # Wait for the prejoin button to become clickable - it is disabled until
    # getUserMedia has resolved, so this doubles as "the fake camera is up".
    for _ in range(160):
        clicked = await chrome.eval(
            """(() => {
                 const b = Array.from(document.querySelectorAll('button'))
                   .find(x => /join now/i.test(x.textContent || ''));
                 if (!b || b.disabled) return false;
                 b.click();
                 return true;
               })()""",
            await_promise=False,
        )
        if clicked:
            break
        await asyncio.sleep(0.25)
    else:
        return False

    # Then wait until the room is actually live.
    #
    # Not "is there a <video>": the prejoin screen has a self-preview, so
    # that is true a moment after the click and stays true in the waiting
    # room. The check has to be that we are in the room proper - no lobby
    # text, and the meeting UI present.
    for _ in range(200):
        state = await chrome.eval(
            """(() => {
                 const text = document.body ? document.body.innerText : "";
                 if (/let you in soon|waiting for the host/i.test(text)) {
                   return "lobby";
                 }
                 if (/is full|meeting is full/i.test(text)) return "full";
                 const pcs = (window.__parleyPcs || []).length;
                 const vids = document.querySelectorAll("video").length;
                 return pcs > 0 || vids > 0 ? "live" : "pending";
               })()""",
            await_promise=False,
        )
        if state == "live":
            return True
        if state == "full":
            return False
        await asyncio.sleep(0.25)
    return False


async def sample(chromes: list[Chrome]) -> list[dict]:
    out = []
    for c in chromes:
        try:
            raw = await c.eval(COLLECT)
            out.append(json.loads(raw) if raw else {})
        except Exception:
            out.append({})
    return out


def _fmt(v: float, width: int = 8, places: int = 1) -> str:
    return f"{v:>{width}.{places}f}"


async def run_rung(args, meeting: dict, peers: int) -> dict:
    number = meeting["meeting_number"]
    passcode = meeting.get("passcode") or ""
    chromes = [
        Chrome(f"p{i}", 9400 + i, headless=not args.headful, window=args.window)
        for i in range(peers)
    ]

    try:
        for c in chromes:
            c.launch()
        for c in chromes:
            c.wait_ready()
        for c in chromes:
            await c.attach()

        joined = 0
        for i, c in enumerate(chromes):
            ok = await join_peer(c, args.web, number, passcode, f"Load {i}")
            joined += 1 if ok else 0
            # Stagger: a simultaneous stampede measures the join path, not
            # the steady state the ramp is about.
            await asyncio.sleep(args.stagger)

        if joined < peers:
            print(f"  !! only {joined}/{peers} peers joined")

        # Let the mesh settle: ICE, DTLS, and the encoders finding their
        # level. Measuring before this is measuring the handshake.
        await asyncio.sleep(args.settle)

        first = await sample(chromes)
        cpu0 = [c.cpu_jiffies() for c in chromes]
        t0 = time.time()

        await asyncio.sleep(args.hold)

        last = await sample(chromes)
        cpu1 = [c.cpu_jiffies() for c in chromes]
        elapsed = time.time() - t0
        hz = os.sysconf("SC_CLK_TCK")

        up_kbps = []
        down_kbps = []
        fps_sent = []
        heights = []
        active_out = []
        limits: dict[str, int] = {}
        for a, b in zip(first, last):
            if not a or not b:
                continue
            before = {s["id"]: s for s in a.get("outVideo", [])}
            up = 0
            for s in b.get("outVideo", []):
                prev = before.get(s["id"])
                if prev:
                    up += max(0, s["bytes"] - prev["bytes"])
                if s["fps"]:
                    fps_sent.append(s["fps"])
                if s["h"]:
                    heights.append(s["h"])
                if s["bytes"] > (before.get(s["id"], {}).get("bytes", 0)):
                    active_out.append(1)
                limits[s["limitation"]] = limits.get(s["limitation"], 0) + 1
            up_kbps.append(up * 8 / 1000 / elapsed)

            before_in = {s["id"]: s for s in a.get("inVideo", [])}
            down = 0
            for s in b.get("inVideo", []):
                prev = before_in.get(s["id"])
                if prev:
                    down += max(0, s["bytes"] - prev["bytes"])
            down_kbps.append(down * 8 / 1000 / elapsed)

        cpu_pct = sum(
            (b - a) / hz / elapsed * 100 for a, b in zip(cpu0, cpu1)
        )
        rss_mb = sum(c.rss_kb() for c in chromes) / 1024

        def avg(xs):
            return sum(xs) / len(xs) if xs else 0.0

        row = {
            "peers": peers,
            "joined": joined,
            "up_kbps_per_peer": avg(up_kbps),
            "down_kbps_per_peer": avg(down_kbps),
            "fps_sent": avg(fps_sent),
            "height_sent": avg(heights),
            "outbound_streams": sum(active_out),
            "cpu_pct_total": cpu_pct,
            "cpu_pct_per_peer": cpu_pct / max(1, peers),
            "rss_mb": rss_mb,
            "limitations": limits,
        }
        print(
            f"  peers={peers:<3} joined={joined:<3} "
            f"up/peer={_fmt(row['up_kbps_per_peer'])}kbps "
            f"down/peer={_fmt(row['down_kbps_per_peer'])}kbps "
            f"fps={_fmt(row['fps_sent'], 5)} "
            f"h={_fmt(row['height_sent'], 5, 0)}p "
            f"streams={row['outbound_streams']:<4} "
            f"cpu={_fmt(cpu_pct, 6)}% ({_fmt(row['cpu_pct_per_peer'], 5)}%/peer) "
            f"rss={rss_mb:.0f}MB"
        )
        if limits:
            print(f"      quality limited by: {limits}")

        if args.keep_open:
            print("  --keep-open: press Enter to tear down")
            await asyncio.get_running_loop().run_in_executor(None, input)
        return row
    finally:
        for c in chromes:
            await c.close()


async def main_async(args) -> None:
    meeting = create_meeting(args.api, args.email, args.password)
    print(
        f"meeting {meeting['meeting_number']} "
        f"(passcode {meeting.get('passcode')}) on {args.web}"
    )
    rungs = [int(x) for x in args.ramp.split(",")]
    rows = []
    for peers in rungs:
        print(f"\n-- {peers} peers --")
        rows.append(await run_rung(args, meeting, peers))
        await asyncio.sleep(2)

    print("\n\n=== summary ===")
    print(
        f"{'peers':>6} {'joined':>7} {'up/peer':>10} {'down/peer':>10} "
        f"{'fps':>6} {'height':>7} {'streams':>8} {'cpu%':>8} {'cpu%/peer':>10}"
    )
    for r in rows:
        print(
            f"{r['peers']:>6} {r['joined']:>7} "
            f"{r['up_kbps_per_peer']:>10.1f} {r['down_kbps_per_peer']:>10.1f} "
            f"{r['fps_sent']:>6.1f} {r['height_sent']:>7.0f} "
            f"{r['outbound_streams']:>8} {r['cpu_pct_total']:>8.1f} "
            f"{r['cpu_pct_per_peer']:>10.1f}"
        )
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"\nwrote {args.json}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", default="http://127.0.0.1:3100")
    parser.add_argument("--api", default="http://127.0.0.1:8100")
    parser.add_argument("--email", default="demo1@parley.app")
    parser.add_argument("--password", default="demo1234")
    parser.add_argument("--ramp", default="2,4,6,8,10,12")
    parser.add_argument("--hold", type=float, default=20.0,
                        help="seconds of steady state to measure over")
    parser.add_argument("--settle", type=float, default=8.0,
                        help="seconds to let ICE and the encoders settle")
    parser.add_argument("--stagger", type=float, default=1.0)
    parser.add_argument("--window", default="1280,720")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":

    main()
