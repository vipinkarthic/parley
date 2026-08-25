# Testing

Parley is covered by two suites and a CI workflow that runs both. This
document records what is covered, what is deliberately not, and the results
of the runs that were actually performed rather than the ones that were
intended.

Everything below was run on 2026-09-14 on Linux 7.1.8 (CachyOS) / Python 3.12.13 /
Node 24.21.0, against commit `aaa154e` plus the Phase 6 changes.

---

## 1. The two suites

| Suite | What it drives | Where | Count |
|---|---|---|---|
| **API** — pytest + FastAPI `TestClient` | The HTTP API and the WebSocket signalling hub, in-process | `backend/tests/` | 173 |
| **End-to-end** — Playwright | A real browser against a real server and a production build of the frontend | `e2e/tests/` | 12 |

They are not redundant. The API suite can assert things a browser cannot see
(that admitting a lobby full of guests is one transaction, that a privileged
frame from a non-host is dropped rather than acted on). The browser suite
catches the class of bug that every in-process test misses — which this
project has already been bitten by once, in Phase 4, where a bug that no unit
test caught was only found in a real browser (see `PARLEY_PLAN.md` §12).

---

## 2. Running them

```bash
# API suite, SQLite (the default)
cd backend && pytest -q

# API suite, Postgres - the same tests, the production engine
cd backend
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/parley_test pytest -q

# End-to-end. Playwright starts the backend and the frontend itself.
cd e2e
npm ci
npx playwright install firefox
npx playwright test
```

The e2e harness needs no running server and no configuration: `playwright.config.ts`
boots a throwaway SQLite backend on **127.0.0.1:8111** and a production build of
the frontend on **127.0.0.1:3111**, both bound to loopback and both torn down
with the run. Ports are deliberately off the developer defaults (8100 / 3000)
so a test run cannot collide with — or worse, quietly point at — a dev stack
holding real data.

---

## 3. Results

### 3.1 API suite, SQLite

```
172 passed, 1 skipped in 40.73s
```

The skip is `test_stored_timestamps_come_back_aware`, skipped with the reason
`SQLite has no timestamptz`. It is not skipped on Postgres — see below.

### 3.2 API suite, Postgres 16

```
173 passed in 43.67s
```

Run against a throwaway local cluster (`initdb` + `pg_ctl` on port 55432, trust
auth, dropped afterwards). Every test passes on both engines, and the
timestamptz test that SQLite cannot express runs for real here.

**This run earned its place.** One test written during this phase —
`test_a_host_settings_frame_is_written_through_to_the_database` — passed on
SQLite and failed on Postgres. The cause was a race in the *test*, not the
app: the socket handler broadcasts new settings to the room **before**
persisting them, and the write goes through `run_in_threadpool`. Reading the
API the instant the broadcast frame arrived was a race that SQLite won purely
by being faster. The test now polls for the write with a bounded timeout,
which asserts the thing that is actually guaranteed. A SQLite-only CI would
have shipped that test green and flaky.

### 3.3 End-to-end, Firefox

```
12 passed (28.7s)
```

### 3.4 Per-file breakdown

| File | Tests | Covers |
|---|---:|---|
| `test_host_controls.py` | 25 | Host privileges over HTTP and the socket · **new in Phase 6** |
| `test_meetings.py` | 22 | Meeting lifecycle, join gates, host scoping |
| `test_users.py` | 17 | Contacts, profile, preferences · **new in Phase 6** |
| `test_auth.py` | 14 | Signup, OTP, login, token handling |
| `test_speakers.py` | 14 | Active-speaker ranking rules |
| `test_rate_limits.py` | 12 | The auth limiter · **new in Phase 6** |
| `test_observability.py` | 11 | `/healthz`, `/readyz`, request IDs, SMTP failure |
| `test_idempotency.py` | 10 | Replayed joins and OTP verifies |
| `test_media_plane.py` | 9 | Paging messages and the room cap, over the wire |
| `test_signalling_performance.py` | 9 | Broadcast isolation and session counts |
| `test_reconnect.py` | 7 | Heartbeats, socket eviction, drain |
| `test_schema.py` | 6 | Timezone-aware columns, indexes |
| `test_persistence.py` | 6 | Cross-session reads, ordering, constraints |
| `test_ice.py` | 6 | ICE config shape and the TURN placeholder flag |
| `test_ws.py` | 5 | Socket authentication |

---

## 4. What Phase 6 added

### 4.1 API — three files, 54 tests

Phase 6 started from 118 passing tests. The gaps it closed were chosen by
reading the router list against the test list, not by chasing a coverage
percentage.

- **`test_users.py` (17).** The `/api/contacts`, `/api/profile` and
  `/api/preferences` router had **no tests at all**. Now covered: that the
  directory never returns the caller to themselves, that presence flips to
  `in-meeting` and back, that a partial PATCH leaves unnamed fields alone,
  that preferences are per-account, and that none of it is reachable without
  a token.

- **`test_host_controls.py` (25).** Host privilege, on both doors it can be
  reached through: the HTTP settings PATCH and the live `mute-peer` /
  `remove-peer` / `mute-all` / `settings` / `end-meeting` / `admit` / `deny`
  frames. Every privileged action has a matching test in which a **non-host
  attempts the same thing and is ignored** — the point being that the
  privilege is enforced server-side rather than by the frontend hiding a
  button.

- **`test_rate_limits.py` (12).** The auth limiter had no tests. Now covered:
  the window slides, keys are independent, the login cap survives case and
  whitespace in the email, the limiter bites *before* the password check
  (otherwise it is decorative), and the OTP cap covers resend as well as
  request.

### 4.2 End-to-end — three flows, 12 tests

| Spec | Tests | Flow |
|---|---:|---|
| `signup-otp.spec.ts` | 3 | Signup → emailed OTP → dashboard |
| `create-join.spec.ts` | 3 | Host creates → guest follows the invite link → admitted |
| `host-controls.spec.ts` | 6 | Mute, remove, lock, settings broadcast, end for all |

Two properties of these specs are worth stating, because they are what make
them worth their runtime:

1. **The assertions are made on the other participant's screen.** A host
   control that only updated the host's own UI would pass a single-page test
   and be useless in a real meeting. The guest page is the witness.

2. **The guest goes *through* the waiting room, not around it.** The waiting
   room defaults to ON, so that is the path a real invite link takes. A test
   that turned it off first would be testing a configuration nobody ships.

---

## 5. How the browser suite is driven

Playwright drives **its own Firefox build** — a Gecko engine, the same family
as Zen, which is the browser this machine actually uses.

Zen itself cannot be automated. Playwright's Firefox support requires Gecko
patched with its `Juggler` protocol, which ships only in Playwright's own
build. Chromium is different — CDP is present in stock Chrome, so
`channel` / `executablePath` work there — but for Gecko there is no
equivalent escape hatch, and pointing Playwright at `/opt/zen-browser-bin`
fails to connect. Playwright's Firefox is the closest executable thing, and
it is the identical build locally and in CI.

Media is synthetic. The config sets `media.navigator.streams.fake`, so
`getUserMedia` resolves on a machine with no camera and the pre-join screen
reaches its ready state. Verified in-browser: `isSecureContext: true`,
tracks `["audio:Default Audio Device", "video:Default Video Device"]`.

**No email is sent, ever.** The e2e backend runs with empty SMTP credentials,
which forces `EMAIL_ENABLED=False`; the OTP then comes back in the response
body and is printed on the page. `signup-otp.spec.ts` reads the code off the
wire and asserts the page displays that same code, so a regression that
stopped surfacing it fails loudly here instead of silently locking every
other test out of its account.

---

## 6. CI

`.github/workflows/ci.yml`, on every pull request and every push to `main`:

| Job | What it proves |
|---|---|
| `api-sqlite` | The API suite passes. Fast; gates the e2e job. |
| `api-postgres` | The same suite passes against Postgres 16, the production engine. |
| `frontend-checks` | `tsc --noEmit` and `next lint` — catches a broken build before e2e spends minutes on it. |
| `e2e` | The three browser flows, Firefox, with the report uploaded as an artifact. |

Concurrency is set so a new push to a PR cancels the previous run: the old
answer is about a different commit.

---

## 7. What is deliberately not tested

Stated rather than left as a silent gap.

- **Real media flowing between peers.** The e2e specs prove signalling,
  admission and host control end-to-end in a browser, and that a local track
  is acquired and rendered. They do not assert that decoded video arrives
  over a peer connection. That property was measured directly in Phase 5 by
  ramping peer count against CPU and bitrate (`PARLEY_PLAN.md` §12), which is
  the right instrument for it; a pass/fail assertion in CI is not.

- **TURN relay behaviour.** Depends on a third-party service and on the
  network the runner happens to be on. Covered by `tools/turn_probe.py`,
  which is run deliberately rather than on every commit.

- **The multi-peer ceiling.** `ROOM_CAP = 10` is enforced and tested
  (`test_media_plane.py`), but the measurement behind that number is a Phase 5
  harness, not a CI job.

- **Email delivery.** Asserted to be *disabled* in tests. That real SMTP
  works is not a CI concern, and `test_observability.py` already covers the
  case that matters: signup survives SMTP being down.

- **Coverage percentage.** Not measured and not targeted. The gaps closed in
  this phase were picked by reading the router list against the test list.
