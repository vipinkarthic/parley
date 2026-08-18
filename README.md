# Parley

A video meeting product. Start an instant meeting, schedule one for later, join
by meeting ID or invite link, and run a live room with camera, mic, chat,
reactions, screen share, a waiting room and full host controls.

Media is peer-to-peer WebRTC; the server only relays signalling and app events.

![Dashboard](docs/screenshots/dashboard.png)

---

## Tech Stack

| Layer      | Technology                                                                            |
| ---------- | ------------------------------------------------------------------------------------- |
| Frontend   | **Next.js 14** (App Router, client-rendered SPA), **React 18**, **TypeScript**, **Tailwind CSS** |
| Backend    | **Python 3.12**, **FastAPI**, **SQLAlchemy 2.0**, **Pydantic v2**, **Uvicorn**        |
| Database   | **PostgreSQL** on **Neon** (pooled endpoint), **Alembic** migrations, hand-designed schema |
| Real-time  | **WebRTC** peer-to-peer mesh (`RTCPeerConnection`) + a **FastAPI WebSocket** signalling hub |
| Auth       | **JWT** (PyJWT) + **bcrypt** password hashing + email **OTP** over SMTP               |

The only libraries beyond the core stack are small, standard helpers (PyJWT,
bcrypt, python-dotenv, python-dateutil on the backend; nothing beyond React/Next
on the frontend - the API client uses the native `fetch`).

---

## Features
- **Dashboard** - navbar (Home / Meetings / Contacts / Whiteboards, search,
  settings, profile menu), quick-action tiles (New Meeting / Join / Schedule)
  and **Upcoming** + **Recent** meeting lists.
- **Instant meeting** - one click generates a unique 11-digit meeting ID and a
  shareable invite link, and drops you into the room as host.
- **Join meeting** - join by **meeting ID** *or* by pasting an **invite link**.
  A pre-join screen (device preview + name) validates the meeting exists first,
  with a clear "meeting not found" state otherwise.
- **Schedule meeting** - topic, description, date/time and duration. Stored in
  the DB, given a unique link, and listed under **Upcoming**.
- **Authentication** - email/password **login** and **OTP-verified signup**
  (a real 6-digit code is emailed over SMTP, with a dev fallback). Sessions
  are stateless **JWT Bearer** tokens; meetings are scoped to the signed-in user.
- **Guest join** - anyone with an invite link can join **without an account**;
  their name is automatically tagged **`(Guest)`** so they're easy to tell apart.
- **Responsive** - works on mobile, tablet and desktop.
- **Real-time meeting room** - genuine multi-peer **WebRTC** (people in different
  tabs/devices actually see and hear each other): live presence, mic/camera
  toggles, real-time chat, reactions and raise-hand, speaker/gallery views with
  pin, active-speaker highlight, in-meeting rename, and a meeting timer.
- **Screen share** - the sharer keeps broadcasting their camera *and* the
  screen; everyone sees the screen large with a camera filmstrip on the side.
- **Full host controls / Security menu** (at creation and live in-meeting):
  waiting room, lock meeting, mute-on-entry, join-before-host, and "allow
  participants to" share / unmute / start-video / rename / chat / react; plus
  **mute-all**, **mute/remove** a participant, **spotlight**, **lower-hand**,
  **ask-to-unmute** and **end for all**.
- **Time-gated scheduling** - before the start time non-hosts see a countdown;
  the host can start early and then admits people from the waiting room.
- **Passcode-protected joins** - embedded in invite links, required for ID-only
  joins, host bypasses. The passcode is never leaked to non-hosts.
- **Profile & settings** - edit display name, avatar colour and photo, a Personal
  Meeting ID (permanent room), change password, and preferences that drive the
  pre-join defaults (join muted, video-on-join, mirror, HD).

---

## Architecture

Three planes, with different scaling properties. Keeping them separate is what
makes the system easy to reason about.

```
   ┌──────────────┐                              ┌──────────────┐
   │  Browser A   │                              │  Browser B   │
   └──────┬───────┘                              └──────┬───────┘
          │  1. HTTPS  (JWT Bearer, stateless)          │
          ├─────────────────────┐  ┌────────────────────┤
          │                     ▼  ▼                    │
          │              ┌────────────────┐             │
          │              │    FastAPI     │             │
          │              │  ┌──────────┐  │             │
          │  2. WSS      │  │ REST API │  │             │
          ├──────────────┼─▶│ WS  hub  │◀─┼─────────────┤
          │  (signalling)│  └────┬─────┘  │             │
          │              └───────┼────────┘             │
          │                      ▼                      │
          │                 ┌─────────┐                 │
          │                 │   DB    │                 │
          │                 └─────────┘                 │
          │                                             │
          └─────────── 3. WebRTC: audio/video ──────────┘
                   direct, peer-to-peer, never via the server
```

### Request / signalling flow for a join

1. **`POST /api/meetings/{number}/join`** (guests allowed, so invite links
   work). The server decides `is_host` and `admission` *from the database* -
   never from anything the client claims - writes a `participants` row, and
   returns a participant id plus a per-participant `ws_token`.
2. **`WS /ws/meetings/{number}?pid=…&token=…`**. The hub re-reads the meeting
   and participant from the DB and closes with **4003** if the token doesn't
   match that participant. This is the only thing that grants host powers on
   the socket, so they can't be spoofed.
3. **Admitted** peers get a `peers` snapshot and the room gets `peer-joined`.
   **Waiting** peers are parked in a lobby and hosts receive `waiting-list`.
4. Peers exchange **`offer` / `answer` / `ice`** messages addressed with a `to`
   field. The hub relays them verbatim; it never parses or terminates media.
5. An **`RTCPeerConnection` per pair** carries audio and video directly between
   browsers. Chat, reactions, raise-hand, screen-share state and every host
   control ride the same WebSocket.

### Why the planes matter

| Plane | State | Scaling |
| --- | --- | --- |
| HTTP / API | Stateless (JWT, no server sessions) | Horizontal for free; the DB connection count is the ceiling |
| Signalling (WS) | Room membership held in process | One instance. Thousands of near-idle sockets is not a problem; **cross-instance is not supported** |
| Media (WebRTC mesh) | None - server sees no media | Bounded by *client* upload and CPU, not by the server |

In a mesh each peer encodes and uploads N−1 copies of its own video, so cost
grows quadratically across the room while the server stays idle. That is the
real ceiling, and it is a client-side one. See **Known limits**.

---

## Project Structure

```
parley/
├── backend/                      # FastAPI + Postgres API
│   ├── app/
│   │   ├── main.py               # App entrypoint, CORS, request ids, health, SIGTERM drain
│   │   ├── config.py             # Env-driven config
│   │   ├── logging_setup.py      # Structured logs + the request-id context
│   │   ├── database.py           # Engine (pooled, pre-ping), session, declarative base
│   │   ├── dbtypes.py            # UtcDateTime: timezone-aware UTC columns
│   │   ├── models.py             # SQLAlchemy models (User, Meeting, Participant, PendingSignup)
│   │   ├── schemas.py            # Pydantic request/response schemas
│   │   ├── crud.py               # DB operations
│   │   ├── serializers.py        # ORM -> API DTO with computed fields
│   │   ├── security.py           # bcrypt + JWT + OTP hashing
│   │   ├── ratelimit.py          # In-memory rate limiter for auth endpoints
│   │   ├── emailer.py            # OTP email over SMTP (dev fallback)
│   │   ├── deps.py               # Auth dependencies (get_current_user)
│   │   ├── utils.py              # Meeting-number / passcode / invite-link generation
│   │   ├── seed.py               # Demo accounts + optional sample meetings
│   │   ├── ws.py                 # WebSocket signalling hub (WebRTC + presence + host controls)
│   │   └── routers/
│   │       ├── auth.py           # Signup (OTP), login, change password, current user
│   │       ├── meetings.py       # Meeting + participant + join endpoints
│   │       ├── ice.py            # STUN/TURN list for the browser
│   │       └── users.py          # Contacts, profile, preferences
│   ├── alembic/                  # Migration history (Alembic owns the schema)
│   ├── tests/                    # pytest; runs on SQLite or Postgres unchanged
│   ├── tools/turn_probe.py       # Verify a TURN account really allocates a relay
│   ├── requirements.txt
│   ├── Procfile                  # Backend start command (Render / Railway)
│   └── .env.example
│
├── frontend/                     # Next.js app (App Router)
│   └── src/
│       ├── app/
│       │   ├── page.tsx                  # Dashboard
│       │   ├── login/page.tsx            # Email/password login
│       │   ├── signup/page.tsx           # OTP-verified signup
│       │   ├── meetings/page.tsx         # Meetings (Upcoming / Previous)
│       │   ├── contacts/page.tsx         # Coming soon
│       │   ├── whiteboards/page.tsx      # Coming soon
│       │   ├── settings/page.tsx         # Profile & preferences
│       │   ├── j/[number]/page.tsx       # Invite-link redirect
│       │   └── meeting/[number]/page.tsx # Live meeting room + pre-join
│       ├── components/                   # Navbar, AuthShell, modals, meeting UI, tiles
│       └── lib/
│           ├── api.ts                    # Fetch-based API client (+ JWT, ICE config)
│           ├── auth.tsx                  # Auth context/provider
│           └── useMeeting.ts             # WebRTC mesh + signalling, with reconnect
│
├── docs/screenshots/             # README images
├── render.yaml                   # Render blueprint (builds from backend/)
└── README.md
```

---

## Database Schema

PostgreSQL, four tables, managed by Alembic. `users` host `meetings`; each
meeting has many `participants`; `pending_signups` is transient state during
OTP signup.

Every timestamp column is `timestamptz` and every value written is UTC.
Indexes cover what is actually filtered and ordered: `participants.meeting_id`,
`meetings.host_id`, `meetings.start_time`, plus the unique `meetings.meeting_number`
and `users.email`.

```
users 1 ── * meetings 1 ── * participants
                                   │
                          participants.user_id ─┐ (nullable, points back to users;
                                                └─ null = anonymous guest)
```

**`users`** - registered accounts (created only after OTP verification).

| Column                | Type        | Notes                                             |
| --------------------- | ----------- | ------------------------------------------------- |
| `id`                  | int PK      |                                                   |
| `name`                | str(120)    |                                                   |
| `email`               | str(200)    | unique                                            |
| `password_hash`       | str(200)    | bcrypt                                            |
| `is_verified`         | bool        | set once the email OTP is confirmed               |
| `avatar_color`        | str(9)      | hex colour for the initials avatar                |
| `avatar_url`          | text, null  | uploaded profile photo (data-URL), optional       |
| `pmi`                 | str(11)     | Personal Meeting ID - the user's permanent room   |
| `created_at`          | datetime    |                                                   |
| `pref_video_on_join`  | bool        | \                                                 |
| `pref_join_muted`     | bool        |  \  saved preferences that drive the              |
| `pref_mirror_video`   | bool        |  /  pre-join defaults                              |
| `pref_hd_video`       | bool        | /                                                 |
| `pref_notifications`  | bool        |                                                   |

**`meetings`** - instant or scheduled meetings, owned by a host.

| Column               | Type       | Notes                                              |
| -------------------- | ---------- | -------------------------------------------------- |
| `id`                 | str(36) PK | uuid4 hex                                          |
| `meeting_number`     | str(11)    | unique, indexed - the 11-digit meeting ID          |
| `topic`              | str(200)   |                                                    |
| `description`        | text, null |                                                    |
| `passcode`           | str(10)    | required to join (host bypasses)                   |
| `host_id`            | FK users   | the owner/host                                     |
| `meeting_type`       | str(20)    | `instant` \| `scheduled`                           |
| `status`             | str(20)    | `scheduled` \| `active` \| `ended`                 |
| `waiting_room`       | bool       | \                                                  |
| `locked`             | bool       |  \                                                 |
| `mute_on_entry`      | bool       |   host-controlled settings / permissions           |
| `join_before_host`   | bool       |   (`allow_*` gate what non-hosts may do;            |
| `allow_screen_share` | bool       |    host always bypasses them)                      |
| `allow_unmute`       | bool       |  /                                                 |
| `allow_video`        | bool       | /                                                  |
| `allow_rename`       | bool       |                                                    |
| `allow_chat`         | bool       |                                                    |
| `allow_reactions`    | bool       |                                                    |
| `start_time`         | datetime, null | set for scheduled meetings                     |
| `duration`           | int        | minutes                                            |
| `created_at`         | datetime   |                                                    |

**`participants`** - join records per meeting (`ON DELETE CASCADE`).

| Column         | Type          | Notes                                                    |
| -------------- | ------------- | -------------------------------------------------------- |
| `id`           | int PK        |                                                          |
| `meeting_id`   | FK meetings   | cascade delete                                           |
| `user_id`      | FK users,null | null = anonymous guest (drives "one active meeting")     |
| `display_name` | str(120)      | guests get a `(Guest)` suffix                            |
| `is_host`      | bool          | decided server-side from the DB, never trusted from client |
| `is_muted`     | bool          |                                                          |
| `is_video_on`  | bool          |                                                          |
| `is_active`    | bool          | false = left/removed                                     |
| `admission`    | str(12)       | `admitted` \| `waiting` \| `denied`                      |
| `ws_token`     | str(40)       | per-participant secret; the WebSocket must present it    |
| `joined_at`    | datetime      |                                                          |

**`pending_signups`** - an unverified signup awaiting its OTP. Holds the name,
bcrypt password hash, the SHA-256 hashed OTP (`code_hash`), an `expires_at` and
an `attempts` counter. On successful verification it becomes a real `users` row
and is deleted.

---

## Getting Started (Local)

**Prerequisites:** Node.js 18+ and Python 3.10+.

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env          # dev-mode OTP works with no further edits

# Point DATABASE_URL at a Postgres database, then create the schema.
# A free Neon dev branch is the closest thing to what runs in production.
alembic upgrade head

uvicorn app.main:app --reload --port 8000
```

API runs at `http://localhost:8000` (interactive docs at `/docs`).

**Alembic owns the schema.** The app does not create tables on startup - it
checks they exist and refuses to boot with a clear message if they do not, so a
failed migration cannot quietly turn into a half-built database.

| Command | Purpose |
| ------- | ------- |
| `alembic upgrade head` | Apply migrations |
| `alembic current` | Show the applied revision |
| `alembic check` | Confirm the models and migrations still agree |
| `alembic downgrade base` | Roll back to an empty database (**destroys data**) |

Leaving `DATABASE_URL` blank falls back to a local SQLite file. That path
exists so the test suite runs offline; production refuses to start without a
real `DATABASE_URL` rather than silently writing to a disk that is wiped on
every deploy.

### Tests

```bash
pip install -r requirements-dev.txt
pytest                                          # SQLite, offline
TEST_DATABASE_URL=postgresql://... pytest       # against real Postgres
```

The suite builds its schema by running the migrations, so a green run also
proves `alembic upgrade head` works from an empty database.

**Seeded demo accounts** are created automatically on startup so you can log in
right away (no OTP needed) - all share the password **`demo1234`**:

| Name       | Email              | Password   |
| ---------- | ------------------ | ---------- |
| Demo One   | `demo1@parley.app` | `demo1234` |
| Demo Two   | `demo2@parley.app` | `demo1234` |
| Demo Three | `demo3@parley.app` | `demo1234` |

Log into two of them in separate windows to test a real multi-peer meeting. You
can also create your own account via signup. (Set `SEED_SAMPLE_DATA=true` to also
seed a few sample meetings hosted by the first demo account.)

> **Dev-mode OTP (default):** with no `SMTP_USER`/`SMTP_PASS` set, the signup
> code is shown in the signup UI and printed to the backend console - no email
> setup needed. See *Authentication & Email* to send real emails.

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local     # already points at http://localhost:8000
npm run dev
```

Open **http://localhost:3000**. Sign up (enter the OTP shown in dev mode), and
you're in.

> **Test a real multi-peer meeting:** sign in and start a meeting in one window,
> then open the invite link in a second (incognito) window and join as a
> **guest** - you'll see two live tiles, chat, reactions and host controls.

> **Camera/mic:** the room asks for camera & microphone permission. If denied,
> it falls back to an avatar tile and every other control still works.

---

## Environment Variables

**Backend** (`backend/.env`)

| Variable           | Default                              | Purpose                                          |
| ------------------ | ------------------------------------ | ------------------------------------------------ |
| `APP_ENV`          | `development` (`production` if `RENDER` is set) | Production refuses to boot without a real `JWT_SECRET` or `DATABASE_URL` |
| `DATABASE_URL`     | *(SQLite file locally; **required** in production)* | Postgres connection string - use Neon's **pooled** endpoint |
| `DB_POOL_SIZE`     | `5`                                  | SQLAlchemy pool size                             |
| `DB_MAX_OVERFLOW`  | `5`                                  | Connections allowed above the pool size          |
| `DB_POOL_RECYCLE`  | `280`                                | Recycle connections before Neon's idle timeout   |
| `FRONTEND_URL`     | `http://localhost:3000`              | Used to build invite links                       |
| `CORS_ORIGINS`     | `http://localhost:3000,...`          | Allowed CORS origins                             |
| `SEED_SAMPLE_DATA` | `false`                              | `true` seeds a few sample meetings for the first user |
| `JWT_SECRET`       | *(dev default locally; **required** in production)* | Secret for signing JWTs         |
| `JWT_EXPIRE_HOURS` | `168`                                | Token lifetime (7 days)                          |
| `SMTP_USER`        | *(empty)*                            | Sending mailbox for OTP email                    |
| `SMTP_PASS`        | *(empty)*                            | SMTP password / Gmail **App Password**           |
| `SMTP_FROM_NAME`   | `Parley`                             | Display name on OTP emails                       |
| `SMTP_TIMEOUT`     | `15`                                 | SMTP socket timeout (seconds)                    |
| `OTP_TTL_MINUTES`  | `10`                                 | OTP validity window                              |
| `STUN_URLS`        | two Google STUN servers              | Comma-separated STUN URLs served by `GET /api/ice` |
| `TURN_URLS`        | Open Relay (`:80`, `:443`, `turns:`) | Comma-separated TURN URLs - the relay path        |
| `TURN_USERNAME`    | `openrelayproject`                   | TURN username; replace for a dedicated account   |
| `TURN_CREDENTIAL`  | `openrelayproject`                   | TURN credential; replace for a dedicated account  |
| `ICE_CANDIDATE_POOL_SIZE` | `2`                           | Candidates pre-gathered per peer connection      |
| `LOG_FORMAT`       | `json` in production, else `text`    | `json` emits one object per line                 |
| `LOG_LEVEL`        | `INFO`                               | Root log level                                   |

Real email needs **both** `SMTP_USER` and `SMTP_PASS`; with either missing the
app stays in dev-mode OTP rather than failing at send time.

The TURN defaults are Open Relay's public endpoint, kept as a **placeholder**
that documents the shape and keeps the relay code path exercised. It is
verified non-functional (see Known limits), and the backend warns about it at
boot - point these at a real account to actually get a relay. They are not
secrets either way: the ICE list is served to the browser by design, and
anything the browser holds is extractable.

**Frontend** (`frontend/.env.local`)

| Variable               | Default                 | Purpose          |
| ---------------------- | ----------------------- | ---------------- |
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8000` | Backend base URL |

---

## Authentication & Email

- **Login** is email + password; **signup** verifies email ownership with a
  6-digit **OTP** before creating the account. Passwords are **bcrypt** hashed;
  sessions are stateless **JWTs** sent as `Authorization: Bearer <token>` (so it
  works across a Vercel/Render cross-domain split without cookies).
- **Dev mode (default):** no SMTP credentials set - the OTP is shown in the
  signup UI and logged to the console. Zero setup.
- **Real email (Gmail SMTP):** set `SMTP_USER` to the sending mailbox and
  `SMTP_PASS` to a Gmail **App Password** (Google Account -> Security -> 2-Step
  Verification -> App Passwords, a 16-char code). OTPs are then delivered to the
  signup email.
- Login and OTP-request endpoints are **rate-limited** (per email) to slow
  brute-force and email-bombing.

---

## API Reference

Base URL `http://localhost:8000`; interactive docs at `/docs`. All `/api/*`
routes require a Bearer token except `GET /api/meetings/{number}` and
`POST /api/meetings/{number}/join`, which allow guests so invite links work.
In-meeting participant controls (mute/remove/spotlight/...) run over the
authenticated WebSocket, not REST.

Every response carries an `X-Request-ID`, echoing an inbound one if present so
a trace survives a proxy. `POST /api/meetings/{number}/join` accepts an
`Idempotency-Key` header: replaying a key returns the participant the first
call created rather than a second one, which is what makes a retry after a
lost response safe.

| Method   | Endpoint                              | Description                                  |
| -------- | ------------------------------------- | -------------------------------------------- |
| `GET`    | `/`                                   | Liveness (the deployed health check target)  |
| `GET`    | `/healthz`                            | Liveness - **never touches the database**    |
| `GET`    | `/readyz`                             | Readiness incl. a database probe; 503 if down |
| `GET`    | `/api/ice`                            | STUN/TURN list for `new RTCPeerConnection`   |
| `POST`   | `/auth/signup/request-otp`            | Start signup: email a 6-digit OTP            |
| `POST`   | `/auth/signup/resend-otp`             | Resend the signup OTP                        |
| `POST`   | `/auth/signup/verify`                 | Verify OTP -> create account + token         |
| `POST`   | `/auth/login`                         | Email/password login -> token                |
| `GET`    | `/auth/me`                            | Current authenticated user                   |
| `POST`   | `/auth/change-password`               | Change password (auth)                       |
| `GET`    | `/api/meetings/upcoming`              | Your scheduled, not-yet-ended meetings       |
| `GET`    | `/api/meetings/recent`                | Your past (ended) meetings                   |
| `GET`    | `/api/meetings`                       | All your meetings                            |
| `POST`   | `/api/meetings/instant`               | Create/reuse your instant meeting            |
| `POST`   | `/api/meetings/personal`              | Your Personal Meeting Room (PMI)             |
| `POST`   | `/api/meetings/schedule`              | Create a scheduled meeting                   |
| `GET`    | `/api/meetings/{number}`              | Validate / fetch a meeting (guest-visible)   |
| `PATCH`  | `/api/meetings/{number}`              | Edit a scheduled meeting (host)              |
| `DELETE` | `/api/meetings/{number}`              | Delete a meeting (host)                      |
| `PATCH`  | `/api/meetings/{number}/settings`     | Update host settings/permissions (host)      |
| `POST`   | `/api/meetings/{number}/end`          | End a meeting (host)                         |
| `POST`   | `/api/meetings/{number}/join`         | Join (guests allowed; honours `Idempotency-Key`) |
| `GET`    | `/api/contacts`                       | Registered users (for the future directory)  |
| `PATCH`  | `/api/profile`                        | Update name / avatar colour / photo          |
| `GET`    | `/api/preferences`                    | Read saved preferences                       |
| `PATCH`  | `/api/preferences`                    | Update preferences                           |
| `WS`     | `/ws/meetings/{number}`               | Signalling + presence/chat/reactions/host controls |

---

## Known limits

Deliberate, and stated rather than papered over.

### Room size, and what is actually known about it

The mesh is the binding constraint. Every peer uploads a separate encode of
its own camera to every other peer, so upstream bandwidth and CPU grow with
the square of the room, and all of that cost is paid by the participants -
the server relays signalling and touches no media at all. Small groups are
the design target, and that is a choice rather than an accident: the correct
fix for a higher ceiling is an SFU, which is a week of work, a VM with a UDP
port range, and a bill.

Two things raise the ceiling without one, and both ship:

- **Active-speaker paging.** Each client subscribes to `top-5 by rank ∪
  pinned ∪ spotlight ∪ anyone screensharing` and asks everyone else to stop
  sending it video. Senders comply with `replaceTrack(null)`, which needs no
  renegotiation. The ranking is computed **on the server**, with hysteresis,
  so every client derives the same set and tracks do not thrash.
  *The limit of this, stated plainly:* a sender only saves upstream when
  **every** receiver has dropped it, so one person pinning you keeps one
  encode and one upload alive.
- **Encoder caps.** `maxBitrate`, `scaleResolutionDownBy` and `maxFramerate`
  step down as the number of peers receiving your camera grows - 1.2 Mbps at
  one receiver, 200 kbps and quarter framerate past six - with H.264
  preferred so a hardware encoder can do the work.

**The room cap is 10, and it is measured.** It is enforced server-side on
both the join endpoint and the websocket, so it is a real limit rather than
an intention.

Ramped 2 → 12 real headless Chrome peers on a 20-core i7-12700H
(`backend/tools/loadtest.py`, 2026-09-11):

| peers | uplink/peer | downlink/peer | sent video | outbound streams | CPU per peer | quality limited by |
|---|---|---|---|---|---|---|
| 2 | 343 kbps | 343 kbps | 480p @ 19.5 fps | 2 | 25% of a core | none |
| 4 | 738 kbps | 738 kbps | 320p @ 19.9 fps | 12 | 42% | none |
| 6 | 845 kbps | 845 kbps | 240p @ 19.7 fps | 30 | 53% | none |
| 8 | 500 kbps | 500 kbps | 178p @ 13.2 fps | 49 | 60% | none |
| 10 | 490 kbps | 456 kbps | 173p @ 13.4 fps | 81 | 83% | none |
| 12 | 486 kbps | 486 kbps | 166p @ 14.0 fps | 99 | 98% | bandwidth, 2 of 132 |

**The uplink column is the result.** In an unpaged mesh a participant's
upload grows linearly with the room: at 6 peers it was already 845 kbps and
on that trend 12 peers would be roughly 1.9 Mbps. Instead it *stops growing*
at eight — 500, 490, 486 kbps — because past the video budget each
additional participant adds a subscriber to someone else, not another
encode to everybody. Stream counts say the same thing: 49 where an unpaged
mesh would carry 56, and 99 where it would carry 132.

**Video degrades by design, and it is not the same thing as collapse.** The
480p → 320p → 240p → 170p staircase is the encoder tiers doing exactly what
they are configured to do as the number of receivers grows.
`qualityLimitationReason` stays `none` all the way to 12 peers, where two of
132 streams finally report `bandwidth` — so the encoders are obeying a cap,
not failing to meet one.

**Why 10 and not 12.** Ten is the last rung with headroom on both
constraints that actually bind: a participant needs 83% of one CPU core
rather than 98%, and no stream has hit a bandwidth limit yet. Twelve works,
and works better than the plan assumed it would, but leaves a participant
nothing spare. **Video at the cap is about 180p** — that is small, and it is
the honest price of a mesh at that size.

**A property of active-speaker paging worth knowing.** Clients all derive
their subscriptions from the same server ranking, so they all pick the *same*
top-K. Load therefore concentrates rather than spreads: the few people being
listened to fan out to the whole room, and everyone else sends nothing. That
is the correct behaviour and it is what makes the saving large, but it means
a sender's cost depends on how interesting they are, not on room size alone.

One caveat that applies to any number this harness produces: every peer runs
on one machine. Bitrate figures transfer directly, because a peer's uplink
does not depend on where the other peers are. **CPU figures do not** - a real
participant pays for one encode set and N-1 decodes, while the test machine
pays for all N of both, so its total CPU is an upper bound rather than a
per-participant reading.
- **TURN needs an account before it does anything.** The relay path is fully
  wired - `GET /api/ice`, credential rotation without a rebuild, ICE restart on
  failure - but the default relay it points at does not work. Open Relay's
  public endpoint was measured on 2026-09-10 to answer a 401 challenge and then
  refuse every allocation with `400`, identically for its own documented
  credentials, a wrong password and a nonexistent user; its `:443` TLS
  certificate does not match its hostname either. **So until `TURN_URLS`,
  `TURN_USERNAME` and `TURN_CREDENTIAL` are set to a real account, peers behind
  symmetric NAT or a restrictive firewall still cannot connect.** The backend
  logs a warning at boot while that is the case. Note also that relayed media
  costs latency and someone's bandwidth, so it is the fallback path, not the
  normal one.
- **Single backend instance.** Room membership for signalling lives in process,
  so two instances would not see each other's rooms. Intentional at this scale -
  a meeting is a few hundred messages - but it means the backend does not scale
  horizontally today. A redeploy therefore ends every meeting on the instance;
  what makes that survivable is that clients reconnect, not that state moves.
- **Reconnect rebuilds media.** A dropped socket now resumes into room state
  with backoff, but peer connections are torn down and rebuilt rather than
  preserved, so a reconnect costs a second or two of video. Deliberate:
  signalling carries renegotiation, so a peer connection outliving its socket
  is unmanageable, and the far end may have rebuilt on a different schedule.
- **Heartbeat detection is not instant.** A half-open socket - what a slept
  laptop leaves behind - is detected by an unanswered 20s ping, so worst case
  is roughly that before recovery starts. A tab regaining focus or the network
  coming back short-circuits the wait.
- **OTP delivery is fire-and-forget.** Signup no longer waits on SMTP and an
  outage no longer fails signup, but the flip side is that a delivery failure
  cannot be reported in the response. It is logged, and the user's recourse is
  the resend button.
- **Free-tier cold starts.** The hosted backend spins down after ~15 minutes
  idle, and a cold start measured 15.4 seconds. A keepalive on a machine that
  is always up pings `/healthz` every ten minutes between 09:00 and 21:00 IST,
  which is a quota decision: Render allows 750 instance-hours a month against a
  ~730-hour month, so round-the-clock pinging would consume the whole
  allowance. Outside that window the first request still pays for the cold
  start.
- **Rate limiting is per-process.** The auth limiter is an in-memory
  fixed window, so it resets on restart and would not be shared across
  instances. It meaningfully slows brute force at one instance, which is what
  there is.
- **Slow consumers are unbounded.** Broadcasts fan out concurrently, so one
  slow receiver no longer delays the others - but its own send is still
  awaited and there is no bounded queue and no eviction. A peer that never
  drains still accumulates. Not a problem at this room size, and named here
  rather than engineered around.

### Signalling-plane numbers, measured

These are measured, with a command behind each one
(`backend/tools/bench_signalling.py`).

**Broadcast fan-out** - 12 receivers, sends artificially delayed 25 ms, showing
what the receivers who are *not* slow have to wait:

| slow receivers | before | after |
|---|---|---|
| 1 | 25.2 ms | 0.08 ms |
| 3 | 75.5 ms | 0.09 ms |
| 6 | 151.0 ms | 0.09 ms |

With every receiver healthy the difference is small and honest: end to end
over real sockets, 0.61 ms → 0.50 ms p50. Concurrency buys nothing when
nobody is slow.

**Event-loop blocking** - ping/pong latency on a socket doing nothing, while
another socket sends messages that persist, against a real remote Postgres:

| | before | after |
|---|---|---|
| behind one persisted rename | 453 ms | 0.44 ms |
| during a 60-write burst (max) | 27.6 s | 0.71 ms |

**Cold start** - the hosted backend measured 15.4 s from spun-down on
2026-09-10. That is what the keepalive exists for.

### Measuring it yourself

The media-plane ramp is a real load test: it launches up to N headless
Chrome instances with synthetic cameras and will saturate the machine it
runs on, so run it somewhere you do not mind being busy.

```bash
# with the backend and frontend running locally
cd backend
python tools/loadtest.py --web http://127.0.0.1:3000 \
                         --api http://127.0.0.1:8000 \
                         --ramp 2,4,6,8,10,12 --hold 20 \
                         --json ramp.json
```

It creates a meeting through the real API, drives each browser through the
real prejoin screen, and reports uplink, downlink, sent resolution and
framerate, outbound stream count, and CPU per rung. Collapse shows up as
resolution and framerate falling while `qualityLimitationReason` turns to
`cpu` or `bandwidth` - a mesh under strain does not stop, it quietly sends
160x120 at 4 fps. That is how `ROOM_CAP` was set; re-run it on weaker
hardware and expect a lower number.

`tools/verify_paging.py` is the functional companion. It wraps
`RTCPeerConnection`, `setLocalDescription`, `setRemoteDescription`,
`RTCRtpSender.replaceTrack` and `WebSocket` before any application script
runs, then checks that every client agrees on the ranking, that tracks are
actually dropped, that swaps happen with **zero** SDP exchange, and that no
transceiver direction is ever flipped.

---

## Design notes

- **Accounts vs guests** - the dashboard, meetings and settings are gated behind
  login. Invite links work for people **without** an account: they join straight
  from the pre-join screen and are tagged `(Guest)`.
- **Host model** - the meeting's creator is the host and bypasses the passcode.
  Host status is server-decided and enforced over an authenticated WebSocket, so
  it can't be spoofed. Participants are marked inactive on disconnect.
- **One active meeting per account** - "New Meeting" reuses your existing active
  instant room instead of creating duplicates, and a signed-in account can't be
  in two meetings at once. Guests aren't restricted.
- **Security** - all state-changing endpoints require auth; the passcode is never
  leaked to non-hosts (not even via the invite link); OTPs, passcodes and meeting
  numbers use a cryptographic RNG; and auth endpoints are rate-limited.
- **No Google OAuth** - email/password + OTP keeps the system self-contained
  with no external OAuth credentials.

---

## Deployment

**Frontend -> Vercel:** import the repo, set **Root Directory** to `frontend`,
add `NEXT_PUBLIC_API_BASE` = your backend URL, deploy.

**Backend -> Render / Railway:** new Web Service, **Root Directory** `backend`,
build `pip install -r requirements.txt`, start
`uvicorn app.main:app --host 0.0.0.0 --port $PORT` (a `Procfile` and
`render.yaml` are included). Set `FRONTEND_URL`, `CORS_ORIGINS`, a strong
`JWT_SECRET`, and `SMTP_USER` + `SMTP_PASS` for real email. The frontend derives
the signalling URL from `NEXT_PUBLIC_API_BASE` (`https` -> `wss`), so an HTTPS
backend works out of the box.

Alembic owns the schema, so migrations have to run before the server does -
`render.yaml`'s start command is `alembic upgrade head && uvicorn ...`. The app
checks its tables exist and refuses to boot with a message naming the fix,
rather than creating them itself and letting the live schema drift away from
the migration history.

**Health checks.** Point the platform's check at `/healthz`, which is liveness
only. `/readyz` also probes the database and is the wrong target for a health
check on a free-tier Postgres: a database blip would fail the check and take
the API down with it.

**Keeping a free instance warm.** A free web service spins down after ~15
minutes idle; a cold start here measured 15.4 seconds. `rte`'s `parley-ping`
server on `tle-machine` pings `/healthz` every ten minutes between 09:00 and
21:00 IST. The window is a quota decision - Render allows 750 instance-hours a
month and a month is ~730 hours, so pinging around the clock would spend the
whole allowance on one service. It targets `/healthz` specifically because
Neon meters compute-hours and sleeps after ~5 minutes idle, so a ping that
opened a database connection would burn the database's allowance to keep the
web service's warm.
