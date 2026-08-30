# Parley

A video meeting application: instant or scheduled meetings, joined by meeting ID
or invite link, with camera, mic, chat, reactions, screen share, a waiting room
and host controls. Media is peer-to-peer WebRTC; the server relays signalling and
application events and never touches media.

![Dashboard](docs/screenshots/dashboard.png)

Other screens: [in a meeting](docs/screenshots/meeting.png),
[prejoin](docs/screenshots/prejoin.png), [scheduling](docs/screenshots/schedule.png),
[signup](docs/screenshots/signup.png), [verification](docs/screenshots/signup-otp.png).
`backend/tools/screenshots.py` regenerates them at 1440x900 in headless Chrome.

## Stack

| Layer     | Technology |
| --------- | ---------- |
| Frontend  | Next.js 15 (App Router, client-rendered), React 18, TypeScript, Tailwind CSS |
| Backend   | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2, Uvicorn |
| Database  | PostgreSQL (Neon pooled endpoint), Alembic migrations |
| Real-time | WebRTC mesh (`RTCPeerConnection`) plus a FastAPI WebSocket signalling hub |
| Auth      | JWT (PyJWT), bcrypt password hashing, email OTP over SMTP |

Outside the core stack the backend uses only PyJWT, bcrypt and python-dotenv, and
the frontend nothing beyond React and Next; the API client uses `fetch`.

## What it does

- Dashboard with search, settings, profile menu, and Upcoming and Recent lists.
- Instant meetings generate an 11-digit meeting ID and an invite link. Scheduled
  ones take a topic, description, start time and duration, and show non-hosts a
  countdown until the host starts.
- Join by meeting ID or invite link, behind a prejoin screen with device preview.
- Email and password login, OTP-verified signup, stateless JWT bearer sessions.
- Invite links work without an account. Guest names get a `(Guest)` suffix, and
  guests are exempt from the one-active-meeting rule.
- The room carries presence, mic and camera toggles, chat, reactions, raise-hand,
  speaker and gallery views with pin, active-speaker highlight, rename and a timer.
- Screen share sends camera and screen together, screen large with a filmstrip.
- Host controls are waiting room, lock, mute on entry, join before host, and gates
  for share, unmute, video, rename, chat and reactions. Live actions are mute all,
  mute or remove, spotlight, lower hand, ask to unmute, and end for all.
- Passcodes ride in invite links, are required for ID-only joins, bypassed by the
  host, and never exposed to non-hosts.
- New Meeting reuses an existing active instant room, and a signed-in account
  cannot be in two meetings at once.
- Profile settings cover display name, avatar colour and photo, Personal Meeting
  ID, password change, and preferences that set prejoin defaults.

## Architecture

Three planes with different scaling properties.

```
Browser A <-------- 3. WebRTC audio and video, direct -------> Browser B
    |                                                              |
    +---- 1. HTTPS (JWT bearer, stateless) ---> FastAPI REST <------+
    |                                                              |
    +---- 2. WSS (signalling) ---> WS hub ---> DB <-----------------+
```

The hub is `backend/app/ws.py` and active-speaker ranking is
`backend/app/speakers.py`. Scripts under `backend/tools/` are operational and
none are imported by the app.

### Join flow

1. `POST /api/meetings/{number}/join`, guests permitted so invite links work.
   The server derives `is_host` and `admission` from the database, not from
   client input, writes a `participants` row, and returns a participant id and
   a per-participant `ws_token`.
2. `WS /ws/meetings/{number}?pid=...&token=...`. The hub re-reads the meeting
   and participant from the database and closes with code `4003` if the token
   does not match. This is the only grant of host privileges on the socket.
3. Admitted peers get a `peers` snapshot and the room gets `peer-joined`. Waiting
   peers are held in a lobby and hosts get `waiting-list`.
4. Peers exchange `offer`, `answer` and `ice` messages addressed with a `to` field.
   The hub relays them verbatim and never parses or terminates media.
5. One `RTCPeerConnection` per pair carries audio and video. Chat, reactions,
   raise-hand, screen-share state and host controls share the same WebSocket.

### Scaling properties

| Plane | State | Scaling |
| --- | --- | --- |
| HTTP API | Stateless (JWT, no server sessions) | Horizontal; database connection count is the ceiling |
| Signalling (WS) | Room membership held in process | Single instance; cross-instance is not supported |
| Media (WebRTC mesh) | None; the server sees no media | Bounded by client uplink and CPU |

Each peer encodes and uploads N-1 copies of its own video, so client cost grows
with the square of room size while the server stays idle. See [Limits](#limits).

## Database schema

PostgreSQL, four tables, managed by Alembic. All timestamp columns are
`timestamptz` and all values are written in UTC. Indexes cover
`participants.meeting_id`, `meetings.host_id`, `meetings.start_time`, and the
unique `meetings.meeting_number` and `users.email`.

`users`, created only after OTP verification:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | int PK | |
| `name` | str(120) | |
| `email` | str(200) | unique |
| `password_hash` | str(200) | bcrypt |
| `is_verified` | bool | set once the email OTP is confirmed |
| `avatar_color` | str(9) | hex colour for the initials avatar |
| `avatar_url` | text, null | uploaded photo as a data URL |
| `pmi` | str(11) | Personal Meeting ID, a permanent room |
| `created_at` | datetime | |
| `pref_video_on_join`, `pref_join_muted`, `pref_mirror_video`, `pref_hd_video`, `pref_notifications` | bool | prejoin defaults |

`meetings`:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | str(36) PK | uuid4 hex |
| `meeting_number` | str(11) | unique, indexed |
| `topic` | str(200) | |
| `description` | text, null | |
| `passcode` | str(10) | required to join; host bypasses |
| `host_id` | FK users | |
| `meeting_type` | str(20) | `instant` or `scheduled` |
| `status` | str(20) | `scheduled`, `active` or `ended` |
| `waiting_room`, `locked`, `mute_on_entry`, `join_before_host` | bool | host settings |
| `allow_screen_share`, `allow_unmute`, `allow_video`, `allow_rename`, `allow_chat`, `allow_reactions` | bool | non-host permissions; host bypasses |
| `start_time` | datetime, null | scheduled meetings only |
| `duration` | int | minutes |
| `created_at` | datetime | |

`participants`, with `ON DELETE CASCADE`:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | int PK | |
| `meeting_id` | FK meetings | cascade delete |
| `user_id` | FK users, null | null means anonymous guest |
| `display_name` | str(120) | guests get a `(Guest)` suffix |
| `is_host` | bool | decided server-side, never trusted from the client |
| `is_muted`, `is_video_on` | bool | |
| `is_active` | bool | false means left or removed |
| `admission` | str(12) | `admitted`, `waiting` or `denied` |
| `ws_token` | str(40) | per-participant secret required by the WebSocket |
| `joined_at` | datetime | |

`pending_signups` holds an unverified signup: name, bcrypt password hash,
SHA-256 hashed OTP (`code_hash`), `expires_at` and an `attempts` counter. On
verification it becomes a `users` row and is deleted.

## Local setup

Requires Node.js 18+ and Python 3.12. `render.yaml` pins 3.12.6; 3.10+ runs.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env               # development OTP works with no further edits
alembic upgrade head               # point DATABASE_URL at Postgres first
uvicorn app.main:app --reload --port 8000
```

The API serves on `http://localhost:8000`, with interactive docs at `/docs`.

Alembic owns the schema. The app verifies its tables exist at startup and refuses
to boot otherwise, so a failed migration cannot leave a half-built database.

| Command | Purpose |
| --- | --- |
| `alembic upgrade head` | Apply migrations |
| `alembic current` | Show the applied revision |
| `alembic check` | Verify models and migrations agree |
| `alembic downgrade base` | Roll back to an empty database (destroys data) |

Leaving `DATABASE_URL` unset falls back to local SQLite so the tests run offline.
Production refuses to start without a real `DATABASE_URL`.

```bash
cd frontend
npm install
cp .env.example .env.local         # already points at http://localhost:8000
npm run dev
```

Open `http://localhost:3000`. For a multi-peer meeting, start one in a window and
open the invite link in a second incognito window as a guest. If camera or
microphone permission is denied, the room falls back to an avatar tile.

Demo logins are opt in. Set `SEED_DEMO_ACCOUNTS=true` and a `DEMO_PASSWORD` to
seed `demo1@parley.app`, `demo2@parley.app` and `demo3@parley.app`, which skip the
OTP flow. `DEMO_PASSWORD` has no default and the app refuses to boot if the flag is
set without it. `SEED_SAMPLE_DATA=true` seeds sample meetings. With no `SMTP_USER`
or `SMTP_PASS` the signup code appears in the UI and the backend console; in
production that path is refused and signup returns 503.

### Tests

```bash
cd backend && pip install -r requirements-dev.txt
pytest                                       # 191 tests, SQLite, offline
TEST_DATABASE_URL=postgresql://... pytest    # same suite against Postgres

cd e2e && npm ci && npx playwright install firefox
npx playwright test                          # 12 tests, no running server needed
```

The API suite builds its schema from migrations, not `create_all()`, so a green
run also proves `alembic upgrade head` works from empty. Running it on SQLite and
then Postgres doubles as a cutover check. It drops every table before and after,
and refuses a remote database unless `PARLEY_TEST_ALLOW_REMOTE=1` is set.
Playwright starts its own SQLite backend and a production frontend build on
loopback ports, with synthetic media and no email sent. CI runs both suites plus
the frontend type-check and lint on every pull request:
[`.github/workflows/ci.yml`](.github/workflows/ci.yml). Coverage notes:
[`docs/TESTING.md`](docs/TESTING.md).

## Environment variables

Backend, in `backend/.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` (`production` when `RENDER` is set) | Production requires a real `JWT_SECRET` and `DATABASE_URL` |
| `DATABASE_URL` | SQLite file locally; required in production | Postgres connection string; use Neon's pooled endpoint |
| `DB_POOL_SIZE` | `5` | SQLAlchemy pool size |
| `DB_MAX_OVERFLOW` | `5` | Connections above the pool size |
| `DB_POOL_RECYCLE` | `280` | Recycle before Neon's idle timeout |
| `FRONTEND_URL` | `http://localhost:3000` | Used to build invite links |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Allowed CORS origins |
| `SEED_SAMPLE_DATA` | `false` | Seed sample meetings for the first user |
| `SEED_DEMO_ACCOUNTS` | `false` | Seed the three demo logins, which skip OTP |
| `DEMO_PASSWORD` | empty | Required when `SEED_DEMO_ACCOUNTS` is on; no default |
| `CORS_ORIGIN_REGEX` | unset | Optional regex for preview deployments; anchor it to your own project |
| `JWT_SECRET` | dev default locally; required in production | JWT signing secret, at least 32 characters in production |
| `JWT_EXPIRE_HOURS` | `12` | Token lifetime. A password change retires tokens issued before it |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server for OTP email |
| `SMTP_PORT` | `587` | SMTP port (STARTTLS) |
| `SMTP_USER` | empty | Sending mailbox |
| `SMTP_PASS` | empty | SMTP password, or a Gmail app password |
| `SMTP_FROM_NAME` | `Parley` | Display name on OTP email |
| `SMTP_TIMEOUT` | `15` | SMTP socket timeout in seconds |
| `OTP_TTL_MINUTES` | `10` | OTP validity window |
| `OTP_MAX_ATTEMPTS` | `5` | Wrong codes before the pending signup is discarded |
| `ROOM_CAP` | `10` | Participant cap, enforced on the join endpoint and the socket |
| `VIDEO_BUDGET` | `5` | Remote cameras a client subscribes to at once |
| `STUN_URLS` | two Google STUN servers | Comma-separated, served by `GET /api/ice` |
| `TURN_URLS` | Open Relay (`:80`, `:443`, `turns:`) | Comma-separated TURN URLs |
| `TURN_USERNAME` | `openrelayproject` | Replace for a dedicated account |
| `TURN_CREDENTIAL` | `openrelayproject` | Replace for a dedicated account |
| `ICE_CANDIDATE_POOL_SIZE` | `2` | Candidates pre-gathered per peer connection |
| `LOG_FORMAT` | `json` in production, else `text` | `json` emits one object per line |
| `LOG_LEVEL` | `INFO` | Root log level |

Frontend, in `frontend/.env.local`: `NEXT_PUBLIC_API_BASE`, default
`http://localhost:8000`.

Real email requires both `SMTP_USER` and `SMTP_PASS`. With either missing the
app stays in development OTP mode instead of failing at send time. For Gmail,
`SMTP_PASS` is an app password from Google Account, Security, 2-Step
Verification, App Passwords.

The TURN defaults point at Open Relay's public endpoint. It is verified
non-functional, described under [Limits](#limits), and the backend warns at
boot. These are not secrets: the ICE list is served to the browser by design.

## API reference

Base URL `http://localhost:8000`, interactive docs at `/docs`. All `/api/*`
routes require a bearer token except `GET /api/meetings/{number}` and
`POST /api/meetings/{number}/join`, which permit guests. In-meeting participant
controls run over the authenticated WebSocket, not REST.

Every response carries an `X-Request-ID`, echoing an inbound one if present.
`POST /api/meetings/{number}/join` accepts an `Idempotency-Key` header:
replaying a key returns the participant created by the first call.

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/` | Liveness; the deployed health check target |
| `GET` | `/healthz` | Liveness; never touches the database |
| `GET` | `/readyz` | Readiness including a database probe; 503 if down |
| `GET` | `/api/ice` | STUN is public. TURN needs a signed-in user or a valid participant `pid` and `token` |
| `POST` | `/auth/signup/request-otp` | Start signup and email a 6-digit OTP |
| `POST` | `/auth/signup/resend-otp` | Resend the signup OTP |
| `POST` | `/auth/signup/verify` | Verify the OTP, create the account, return a token |
| `POST` | `/auth/login` | Email and password login |
| `GET` | `/auth/me` | Current authenticated user |
| `POST` | `/auth/change-password` | Change password |
| `GET` | `/api/meetings/upcoming` | Scheduled, not-yet-ended meetings |
| `GET` | `/api/meetings/recent` | Past meetings |
| `GET` | `/api/meetings` | All your meetings |
| `POST` | `/api/meetings/instant` | Create or reuse your instant meeting |
| `POST` | `/api/meetings/personal` | Your Personal Meeting Room |
| `POST` | `/api/meetings/schedule` | Create a scheduled meeting |
| `GET` | `/api/meetings/{number}` | Validate or fetch a meeting (guest-visible) |
| `PATCH` | `/api/meetings/{number}` | Edit a scheduled meeting (host) |
| `DELETE` | `/api/meetings/{number}` | Delete a meeting (host) |
| `PATCH` | `/api/meetings/{number}/settings` | Update host settings (host) |
| `POST` | `/api/meetings/{number}/end` | End a meeting (host) |
| `POST` | `/api/meetings/{number}/join` | Join; guests allowed, honours `Idempotency-Key` |
| `GET` | `/api/contacts` | Registered users, without email addresses |
| `PATCH` | `/api/profile` | Update name, avatar colour or photo |
| `GET` | `/api/preferences` | Read preferences |
| `PATCH` | `/api/preferences` | Update preferences |
| `WS` | `/ws/meetings/{number}` | Signalling, presence, chat, reactions, host controls |

## Limits

### Room size

Uplink and CPU grow with the square of the room, and participants pay that cost.
Raising the ceiling properly requires an SFU. Two mitigations ship.

Active-speaker paging: each client subscribes to the top 5 by rank plus anyone
pinned, spotlighted or screensharing, and asks the rest to stop sending video.
Senders comply with `replaceTrack(null)`, which needs no renegotiation. Ranking
is server-side with hysteresis so all clients derive the same set. A sender only
saves uplink once every receiver has dropped it, so one pin keeps one encode alive.

Encoder caps: `maxBitrate`, `scaleResolutionDownBy` and `maxFramerate` step down
as receiver count grows, from 1.2 Mbps at full resolution and 30 fps with one
receiver to 200 kbps at a third resolution and half framerate past six. H.264 is
preferred so hardware encoders can be used.

`ROOM_CAP` is 10, enforced on the join endpoint and the WebSocket. Ramped 2 to 12
headless Chrome peers on a 20-core i7-12700H, via `backend/tools/loadtest.py`:

| peers | uplink/peer | downlink/peer | sent video | outbound streams | CPU per peer | quality limited by |
|---|---|---|---|---|---|---|
| 2 | 343 kbps | 343 kbps | 480p @ 19.5 fps | 2 | 25% of a core | none |
| 4 | 738 kbps | 738 kbps | 320p @ 19.9 fps | 12 | 42% | none |
| 6 | 845 kbps | 845 kbps | 240p @ 19.7 fps | 30 | 53% | none |
| 8 | 500 kbps | 500 kbps | 178p @ 13.2 fps | 49 | 60% | none |
| 10 | 490 kbps | 456 kbps | 173p @ 13.4 fps | 81 | 83% | none |
| 12 | 486 kbps | 486 kbps | 166p @ 14.0 fps | 99 | 98% | bandwidth, 2 of 132 |

Unpaged, uplink grows linearly: 845 kbps at 6 peers extrapolates to roughly
1.9 Mbps at 12. It flattens at eight instead (500, 490, 486 kbps), because past the
video budget each new participant adds a subscriber, not another encode. Stream
counts agree: 49 where an unpaged mesh would carry 56, 99 where it would carry 132.
The 480p to 320p to 240p to 170p staircase is the encoder tiers tracking receiver
count; `qualityLimitationReason` stays `none` through 12 peers, where 2 of 132
streams report `bandwidth`. The cap is 10 because ten is the last rung with
headroom on both binding constraints, 83% of one core against 98% and no stream at
a bandwidth limit. Video at the cap is roughly 180p.

All clients select the same top-K from the same ranking, so load concentrates and
a sender's cost depends on how often they are ranked. Every peer in this harness
runs on one machine: bitrate transfers directly, CPU does not, since a real
participant pays for one encode set and N-1 decodes while the test machine pays
for all N of both. Treat CPU as an upper bound.

### Other limits

- TURN needs an account. The relay path is wired (`GET /api/ice`, credential
  rotation without a rebuild, ICE restart on failure) but the default relay does
  not work. Open Relay's public endpoint answers a 401 challenge then refuses every
  allocation with `400`, identically for its own documented credentials, a wrong
  password and a nonexistent user, and its `:443` TLS certificate does not match
  its hostname. Until `TURN_URLS`, `TURN_USERNAME` and `TURN_CREDENTIAL` point at a
  real account, peers behind symmetric NAT or a restrictive firewall cannot
  connect. The backend warns at boot while this holds.
- Signalling room membership lives in process, so two instances would not see each
  other's rooms. A redeploy ends every meeting on the instance. Clients reconnect;
  state does not move.
- Reconnect rebuilds media: peer connections are torn down and rebuilt, costing a
  second or two of video.
- A half-open socket is detected by an unanswered 20s ping, so recovery starts that
  late at worst. A tab regaining focus or the network returning cuts the wait short.
- OTP delivery is fire-and-forget. An SMTP outage does not fail signup, but a
  delivery failure is only logged, and the recourse is the resend button.
- The hosted backend spins down after about 15 minutes idle, and a cold start
  measured 15.4 seconds. A keepalive pings `/healthz` every ten minutes between
  09:00 and 21:00 IST. Render allows 750 instance-hours a month against a roughly
  730-hour month, so continuous pinging would consume the allowance.
- The auth rate limiter is an in-memory fixed window, so it resets on restart and
  is not shared across instances.
- Broadcasts fan out concurrently, so one slow receiver does not delay others, but
  its send is still awaited and there is no bounded queue or eviction.

### Signalling-plane measurements

From `backend/tools/bench_signalling.py`. Broadcast fan-out with 12 receivers and
sends delayed 25 ms, measuring what receivers that are not slow must wait; then
event-loop blocking as ping/pong latency on an idle socket while another socket
sends persisted messages against a remote Postgres.

| slow receivers | before | after | event loop | before | after |
|---|---|---|---|---|---|
| 1 | 25.2 ms | 0.08 ms | one persisted rename | 453 ms | 0.44 ms |
| 3 | 75.5 ms | 0.09 ms | 60-write burst (max) | 27.6 s | 0.71 ms |
| 6 | 151.0 ms | 0.09 ms | | | |

With every receiver healthy, end-to-end p50 over real sockets moves from 0.61 ms
to 0.50 ms.

### Reproducing the measurements

The ramp launches up to N headless Chrome instances with synthetic cameras and
will saturate the machine it runs on.

```bash
# with the backend and frontend running locally
cd backend
python tools/loadtest.py --web http://127.0.0.1:3000 \
                        --api http://127.0.0.1:8000 \
                        --ramp 2,4,6,8,10,12 --hold 20 --json ramp.json
```

It creates a meeting through the real API, drives each browser through the real
prejoin screen, and reports uplink, downlink, sent resolution and framerate,
outbound stream count and CPU per rung. Saturation shows up as resolution and
framerate falling while `qualityLimitationReason` turns to `cpu` or `bandwidth`.
This is how `ROOM_CAP` was set; expect a lower number on weaker hardware.

`tools/verify_paging.py` wraps `RTCPeerConnection`, `setLocalDescription`,
`setRemoteDescription`, `RTCRtpSender.replaceTrack` and `WebSocket` before any
application script runs, then checks that clients agree on the ranking, tracks are
dropped, swaps happen with zero SDP exchange, and no transceiver direction flips.

## Deployment

Frontend on Vercel: import the repo, set Root Directory to `frontend`, add
`NEXT_PUBLIC_API_BASE` pointing at the backend URL, deploy.

Backend on Render or Railway: new web service, Root Directory `backend`, build
`pip install -r requirements.txt`, start
`alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`, which
`Procfile` and `render.yaml` both carry. The migration step is required. Set
`FRONTEND_URL`, `CORS_ORIGINS`, a strong `JWT_SECRET`, and `SMTP_USER` and
`SMTP_PASS` for real email. The frontend derives the signalling URL from
`NEXT_PUBLIC_API_BASE`, mapping `https` to `wss`.

`render.yaml` sets `healthCheckPath: /`. Both `/` and `/healthz` are liveness-only
and neither touches the database. Do not point the check at `/readyz`: it probes
the database, so a blip would take the API down, and Neon sleeps after about 5
minutes idle, so a database-touching check would hold it awake. The keepalive
targets `/healthz` for the same reason.
