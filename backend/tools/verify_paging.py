"""Prove, in real browsers, that Phase 4 does what it claims.

Four claims, and none of them is visible to a unit test:

1. **Every grid agrees.** All clients receive the identical `active-speakers`
   list from the server. This is the whole reason ranking moved server-side;
   if it fails, clients subscribe to different people and tracks thrash.
2. **Paging actually drops tracks.** With more peers than the video budget,
   some senders are sending `null` to some peers.
3. **Track swaps cost no renegotiation.** `replaceTrack` is called, and no
   `setLocalDescription` / `setRemoteDescription` happens while it is. This
   is the non-negotiable from the plan, and getting it wrong at six peers
   talking over each other is a renegotiation storm.
4. **Transceivers stay `sendrecv`.** The other half of the same claim: the
   direction is never flipped and the m-line never moves.

Everything is measured by wrapping browser APIs before any application
script runs, so the app exposes nothing for the benefit of a test.

    python tools/verify_paging.py --peers 7
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import loadtest as L  # noqa: E402  (same directory, shared Chrome driver)


# Wraps the three things the claims are about, plus the socket, before the
# app runs. Counters only - no behaviour changes.
INSTRUMENT = r"""
(() => {
  if (window.__pv) return;
  const s = {
    setLocal: 0, setRemote: 0, replace: 0, replaceNull: 0,
    negotiationNeeded: 0, lastRanking: null, rankingCount: 0,
    videoRequestsSent: 0, videoRequestsRecv: 0,
  };
  window.__pv = s;

  const OrigPC = window.RTCPeerConnection;
  window.__parleyPcs = [];
  const PC = function (...a) {
    const pc = new OrigPC(...a);
    window.__parleyPcs.push(pc);
    pc.addEventListener("negotiationneeded", () => { s.negotiationNeeded++; });
    return pc;
  };
  PC.prototype = OrigPC.prototype;
  Object.setPrototypeOf(PC, OrigPC);
  window.RTCPeerConnection = PC;
  window.webkitRTCPeerConnection = PC;

  const sld = OrigPC.prototype.setLocalDescription;
  OrigPC.prototype.setLocalDescription = function (...a) {
    s.setLocal++;
    return sld.apply(this, a);
  };
  const srd = OrigPC.prototype.setRemoteDescription;
  OrigPC.prototype.setRemoteDescription = function (...a) {
    s.setRemote++;
    return srd.apply(this, a);
  };

  const rt = RTCRtpSender.prototype.replaceTrack;
  RTCRtpSender.prototype.replaceTrack = function (track) {
    s.replace++;
    if (track === null) s.replaceNull++;
    return rt.call(this, track);
  };

  const OrigWS = window.WebSocket;
  const WS = function (...a) {
    const ws = new OrigWS(...a);
    ws.addEventListener("message", (e) => {
      try {
        const m = JSON.parse(e.data);
        if (m.type === "active-speakers") {
          s.rankingCount++;
          s.lastRanking = { ranked: m.ranked, speaking: m.speaking };
        }
        if (m.type === "video-request") s.videoRequestsRecv++;
      } catch {}
    });
    const send = ws.send.bind(ws);
    ws.send = (data) => {
      try {
        if (typeof data === "string" &&
            JSON.parse(data).type === "video-request") {
          s.videoRequestsSent++;
        }
      } catch {}
      return send(data);
    };
    return ws;
  };
  WS.prototype = OrigWS.prototype;
  Object.setPrototypeOf(WS, OrigWS);
  Object.defineProperty(WS, "OPEN", { value: OrigWS.OPEN });
  Object.defineProperty(WS, "CLOSED", { value: OrigWS.CLOSED });
  Object.defineProperty(WS, "CONNECTING", { value: OrigWS.CONNECTING });
  Object.defineProperty(WS, "CLOSING", { value: OrigWS.CLOSING });
  window.WebSocket = WS;
})();
"""

SNAPSHOT = r"""
(() => {
  const s = window.__pv || {};
  const pcs = window.__parleyPcs || [];
  const senders = [];
  const directions = [];
  for (const pc of pcs) {
    for (const tx of pc.getTransceivers()) {
      if (tx.sender && tx.sender.track === null && tx.receiver &&
          tx.receiver.track && tx.receiver.track.kind === "video") {
        // receive-only shape we did not ask for; recorded via direction below
      }
      directions.push(tx.direction);
    }
    for (const sender of pc.getSenders()) {
      if (!sender.track) { senders.push("null"); continue; }
      senders.push(sender.track.kind);
    }
  }
  return JSON.stringify({
    counters: {
      setLocal: s.setLocal || 0,
      setRemote: s.setRemote || 0,
      replace: s.replace || 0,
      replaceNull: s.replaceNull || 0,
      negotiationNeeded: s.negotiationNeeded || 0,
      rankingCount: s.rankingCount || 0,
      videoRequestsSent: s.videoRequestsSent || 0,
      videoRequestsRecv: s.videoRequestsRecv || 0,
    },
    lastRanking: s.lastRanking || null,
    pcCount: pcs.length,
    senderKinds: senders,
    directions: directions,
  });
})()
"""


def _c(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


async def main_async(args) -> int:
    meeting = L.create_meeting(args.api, args.email, args.password)
    number = meeting["meeting_number"]
    passcode = meeting.get("passcode") or ""
    print(f"meeting {number} on {args.web}, {args.peers} peers, "
          f"video budget is 5\n")

    chromes = [
        L.Chrome(f"v{i}", 9600 + i, headless=not args.headful, window="1280,720")
        for i in range(args.peers)
    ]
    failures = []
    try:
        for c in chromes:
            c.launch()
        for c in chromes:
            c.wait_ready()
        for c in chromes:
            await c.attach()
            await c.call(
                "Page.addScriptToEvaluateOnNewDocument", {"source": INSTRUMENT}
            )

        joined = 0
        for i, c in enumerate(chromes):
            ok = await L.join_peer(c, args.web, number, passcode, f"Verify {i}")
            joined += 1 if ok else 0
            await asyncio.sleep(1.0)
        print(f"joined {joined}/{args.peers}")
        if joined < args.peers:
            failures.append(f"only {joined}/{args.peers} peers joined")

        print(f"settling {args.settle}s (ICE, DTLS, first ranking)...")
        await asyncio.sleep(args.settle)
        first = [json.loads(await c.eval(SNAPSHOT, await_promise=False))
                 for c in chromes]

        print(f"observing {args.observe}s of steady state...\n")
        await asyncio.sleep(args.observe)
        last = [json.loads(await c.eval(SNAPSHOT, await_promise=False))
                for c in chromes]

        # -- 1. every grid agrees -------------------------------------------
        rankings = [s["lastRanking"] for s in last if s["lastRanking"]]
        print("1. do all grids agree on the ranking?")
        if len(rankings) < 2:
            failures.append("fewer than two clients ever saw a ranking")
            print("   FAIL - fewer than two clients received active-speakers")
        else:
            sets = {tuple(sorted(r["ranked"])) for r in rankings}
            agree = len(sets) == 1
            print(f"   {_c(agree)} - {len(rankings)} clients reported a "
                  f"ranking, {len(sets)} distinct set(s)")
            print(f"          ranked = {sorted(rankings[0]['ranked'])}")
            if not agree:
                for r in rankings:
                    print(f"            {sorted(r['ranked'])}")
                failures.append("clients disagree on the ranking")

        # -- 2. paging drops tracks -----------------------------------------
        print("\n2. is paging actually dropping tracks?")
        nulls = sum(s["senderKinds"].count("null") for s in last)
        total_senders = sum(len(s["senderKinds"]) for s in last)
        req_sent = sum(s["counters"]["videoRequestsSent"] for s in last)
        req_recv = sum(s["counters"]["videoRequestsRecv"] for s in last)
        expect_paging = args.peers - 1 > args.budget
        print(f"   video-request sent={req_sent} recv={req_recv}")
        print(f"   senders with a null track: {nulls} of {total_senders}")
        if expect_paging:
            ok = nulls > 0
            print(f"   {_c(ok)} - {args.peers - 1} remote peers vs a budget "
                  f"of {args.budget}, so some tracks must be dropped")
            if not ok:
                failures.append("no tracks were dropped despite exceeding the budget")
        else:
            print(f"   n/a - {args.peers - 1} remote peers is within the "
                  f"budget of {args.budget}, nothing should be dropped")

        # -- 3. no renegotiation during steady state ------------------------
        print("\n3. do track swaps cost a renegotiation?")
        d_replace = sum(l["counters"]["replace"] - f["counters"]["replace"]
                        for f, l in zip(first, last))
        d_local = sum(l["counters"]["setLocal"] - f["counters"]["setLocal"]
                      for f, l in zip(first, last))
        d_remote = sum(l["counters"]["setRemote"] - f["counters"]["setRemote"]
                       for f, l in zip(first, last))
        print(f"   during the observation window: replaceTrack={d_replace}, "
              f"setLocalDescription={d_local}, setRemoteDescription={d_remote}")
        if d_replace == 0:
            print("   (no track swaps happened in this window - inconclusive, "
                  "not a failure)")
        ok = d_local == 0 and d_remote == 0
        print(f"   {_c(ok)} - no SDP exchange may accompany a track swap")
        if not ok:
            failures.append(
                f"renegotiation during steady state: "
                f"setLocal={d_local} setRemote={d_remote}"
            )

        # -- 4. transceiver directions --------------------------------------
        print("\n4. are transceivers left alone?")
        dirs: dict[str, int] = {}
        for s in last:
            for d in s["directions"]:
                dirs[d] = dirs.get(d, 0) + 1
        bad = {d: n for d, n in dirs.items()
               if d not in ("sendrecv", "stopped")}
        print(f"   directions seen: {dirs}")
        ok = not bad
        print(f"   {_c(ok)} - nothing may be flipped to sendonly/recvonly/inactive")
        if not ok:
            failures.append(f"transceiver directions were changed: {bad}")

        total_rankings = sum(s["counters"]["rankingCount"] for s in last)
        print(f"\nactive-speakers frames delivered in total: {total_rankings}")

        if args.keep_open:
            print("\n--keep-open: press Enter to tear down")
            await asyncio.get_running_loop().run_in_executor(None, input)
    finally:
        for c in chromes:
            await c.close()

    print("\n" + "=" * 60)
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--web", default="http://127.0.0.1:3200")
    p.add_argument("--api", default="http://127.0.0.1:8200")
    p.add_argument("--email", default="demo1@parley.app")
    p.add_argument("--password", default="demo1234")
    p.add_argument("--peers", type=int, default=7)
    p.add_argument("--budget", type=int, default=5)
    p.add_argument("--settle", type=float, default=12.0)
    p.add_argument("--observe", type=float, default=20.0)
    p.add_argument("--headful", action="store_true")
    p.add_argument("--keep-open", action="store_true")
    raise SystemExit(asyncio.run(main_async(p.parse_args())))


if __name__ == "__main__":
    main()
