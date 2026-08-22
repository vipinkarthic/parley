"""Fetch TURN credentials from a metered.ca app, prove they work, emit config.

metered hands out relays through an app-specific API rather than as fixed
values in a dashboard, so the app subdomain alone is not a TURN host -
``<app>.metered.live`` answers HTTP, not STUN. This asks that API for the
real relay hostnames and a credential pair, then does the thing that actually
matters: opens an RFC 5766 Allocate against each one and checks a relay is
handed back.

That distinction is the whole point. Phase 2 shipped a fully plumbed TURN
path pointed at Open Relay's public endpoint, which answers a credential
challenge and then refuses every allocation - identically for its documented
credentials, a wrong password and a nonexistent user. It looked configured
and relayed nothing.

    python tools/turn_setup.py --key-file ~/.metered_key

The API key is read from a file (or METERED_API_KEY) rather than the command
line, so it does not end up in shell history. Credentials are written to
backend/.env.turn and only a masked summary is printed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def mask(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return value[0] + "*" * (len(value) - 1)
    return f"{value[:4]}...{value[-2:]} ({len(value)} chars)"


def read_key(args) -> str:
    if args.key_file:
        p = Path(args.key_file).expanduser()
        if not p.is_file():
            raise SystemExit(f"no such file: {p}")
        key = p.read_text().strip()
    else:
        key = os.environ.get("METERED_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "no API key. Pass --key-file, or set METERED_API_KEY.\n"
            "Find it in the metered dashboard under your app -> Developers/API."
        )
    return key


def fetch(app: str, key: str) -> list[dict]:
    url = (
        f"https://{app}/api/v1/turn/credentials?"
        + urllib.parse.urlencode({"apiKey": key})
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"metered returned {e.code}: {e.read().decode()[:200]}\n"
            "A 401/403 means the API key is wrong for this app."
        )
    if isinstance(body, dict):
        if body.get("error"):
            raise SystemExit(f"metered said: {body['error']}")
        body = body.get("iceServers") or [body]
    if not isinstance(body, list) or not body:
        raise SystemExit(f"unexpected response shape: {str(body)[:200]}")
    return body


def parse_url(url: str) -> tuple[str, int, list[str]] | None:
    """turn(s):host:port[?transport=] -> (host, port, probe flags).

    The transport is not cosmetic. A `turn:` URL with no ?transport= is UDP
    in WebRTC, and testing it over TCP proves nothing - which is how
    turn:...:443 first came back "failed" here when it works perfectly over
    UDP. A `turns:` URL needs the TLS handshake, which is itself part of the
    test.
    """
    for scheme, flags in (("turns:", ["--tls"]), ("turn:", [])):
        if url.startswith(scheme):
            rest = url[len(scheme):]
            query = rest.split("?", 1)[1] if "?" in rest else ""
            rest = rest.split("?")[0]
            if ":" not in rest:
                return None
            host, _, port = rest.rpartition(":")
            if scheme == "turn:" and "transport=tcp" not in query:
                flags = ["--udp"]
            try:
                return host, int(port), flags
            except ValueError:
                return None
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", default="parleymeetings.metered.live",
                    help="the app's API host")
    ap.add_argument("--key-file", default=None)
    ap.add_argument("--out", default=str(BACKEND_ROOT / ".env.turn"))
    args = ap.parse_args()

    key = read_key(args)
    print(f"app      : {args.app}")
    print(f"api key  : {mask(key)}\n")

    servers = fetch(args.app, key)

    urls: list[str] = []
    username = credential = ""
    for entry in servers:
        u = entry.get("urls") or entry.get("url")
        for one in (u if isinstance(u, list) else [u]):
            if one and one not in urls:
                urls.append(one)
        username = entry.get("username") or username
        credential = entry.get("credential") or credential

    turn_urls = [u for u in urls if u.startswith(("turn:", "turns:"))]
    stun_urls = [u for u in urls if u.startswith("stun:")]

    print(f"stun     : {len(stun_urls)}")
    for u in stun_urls:
        print(f"           {u}")
    print(f"turn     : {len(turn_urls)}")
    for u in turn_urls:
        print(f"           {u}")
    print(f"username : {mask(username)}")
    print(f"credential: {mask(credential)}\n")

    if not turn_urls or not username or not credential:
        raise SystemExit("no usable TURN entry came back; nothing to verify.")

    # The part that matters: does a relay actually get allocated?
    print("verifying each relay with an RFC 5766 Allocate "
          "(this is what Open Relay never passed):")
    probe = BACKEND_ROOT / "tools" / "turn_probe.py"
    working: list[str] = []
    for url in turn_urls:
        parsed = parse_url(url)
        if parsed is None:
            print(f"  {url:<52} skipped (unparseable)")
            continue
        host, port, flags = parsed
        res = subprocess.run(
            [sys.executable, str(probe), host, str(port), username, credential,
             *flags],
            capture_output=True, text=True, timeout=90,
        )
        ok = res.returncode == 0
        detail = (res.stdout or res.stderr).strip().splitlines()
        tail = detail[-1].strip() if detail else ""
        how = "tls" if "--tls" in flags else ("udp" if "--udp" in flags else "tcp")
        print(f"  {url:<52} [{how}] {'ALLOCATED' if ok else 'FAILED'}  {tail[:52]}")
        if ok:
            working.append(url)

    print()
    if not working:
        raise SystemExit(
            "No relay allocated. Do NOT put these in Render - that is exactly "
            "the state Open Relay was already in."
        )
    print(f"{len(working)}/{len(turn_urls)} relays allocated.\n")

    out = Path(args.out)
    out.write_text(
        "# Generated by tools/turn_setup.py - verified against a live relay.\n"
        "# Paste these three into Render (service: parley-meeting) as\n"
        "# environment variables. No rebuild is needed: the browser reads them\n"
        "# from GET /api/ice at runtime.\n"
        f"TURN_URLS={','.join(turn_urls)}\n"
        f"TURN_USERNAME={username}\n"
        f"TURN_CREDENTIAL={credential}\n"
    )
    out.chmod(0o600)
    print(f"wrote {out} (chmod 600) - `cat` it to copy into Render.")


if __name__ == "__main__":
    main()
