#!/usr/bin/env bash
#
# Ship Phases 2-5 to production, in the one order that is safe.
#
# The migration has to land before the code, because Phase 2 added
# participants.join_key and the new code reads it. Frontend and backend go
# together, because the frontend fetches GET /api/ice and sends an
# Idempotency-Key header; an old backend answers the first with a 404 (the
# hook degrades to STUN-only rather than breaking) and ignores the second,
# but the window should not exist.
#
# Everything here is reversible except the push. Each step announces itself,
# and any failure stops the run rather than continuing into a half-deploy.
#
# Usage:
#   PARLEY_PROD_DATABASE_URL="postgresql://...neon.../neondb?sslmode=require" \
#     scripts/deploy.sh --dry-run       # rehearse, change nothing
#
#   PARLEY_PROD_DATABASE_URL="..." scripts/deploy.sh
#
set -euo pipefail

BRANCH="phase4-media"
TARGET="main"
API="${PARLEY_API_URL:-https://zoom-clone-api-in8u.onrender.com}"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33mwarn\033[0m %s\n' "$*"; }
die()  { printf '  \033[31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
run()  {
  if (( DRY_RUN )); then printf '  would run: %s\n' "$*"; else eval "$@"; fi
}

bold "Parley deploy - Phases 2, 3, 4 and 5"
(( DRY_RUN )) && bold "(DRY RUN - nothing will be changed)"

# ---------------------------------------------------------------------------
step "1. Pre-flight"
# ---------------------------------------------------------------------------
[[ -n "${PARLEY_PROD_DATABASE_URL:-}" ]] \
  || die "PARLEY_PROD_DATABASE_URL is not set. Get the *pooled* production URI from Neon."

case "$PARLEY_PROD_DATABASE_URL" in
  *pooler*) ok "database URL looks like Neon's pooled endpoint" ;;
  *) warn "URL does not contain 'pooler' - Neon's pooled endpoint is the one to use" ;;
esac

# The single most expensive mistake available here is running the test suite
# against production: its fixtures drop every table. Phase 1 lost a Neon
# branch's schema exactly this way.
if [[ "${TEST_DATABASE_URL:-}" == *"$PARLEY_PROD_DATABASE_URL"* ]]; then
  die "TEST_DATABASE_URL points at production. Unset it before deploying."
fi
[[ "${PARLEY_TEST_ALLOW_REMOTE:-}" == "1" ]] \
  && die "PARLEY_TEST_ALLOW_REMOTE=1 is set. Unset it - it is what lets the suite drop a remote schema."
ok "no test variable is aimed at production"

[[ -z "$(git status --porcelain)" ]] || die "working tree is dirty - commit or stash first"
ok "working tree is clean"

# `git checkout main` cannot work from a linked worktree while main is
# checked out in the primary one - git refuses, correctly. Catch it here with
# a useful sentence rather than four steps later with git's.
if [[ -f .git ]]; then
  PRIMARY="$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')"
  die "this is a linked worktree. Run the deploy from the primary checkout:
         cd $PRIMARY && scripts/deploy.sh"
fi
ok "running from the primary checkout"

git rev-parse --verify "$BRANCH" >/dev/null 2>&1 || die "branch $BRANCH not found"
BASE="$(git merge-base "$TARGET" "$BRANCH")"
if [[ "$BASE" != "$(git rev-parse "$TARGET")" ]]; then
  die "$BRANCH is not a fast-forward of $TARGET. Rebase or merge by hand, deliberately."
fi
ok "$BRANCH fast-forwards $TARGET ($(git rev-list --count "$TARGET..$BRANCH") commits)"

# ---------------------------------------------------------------------------
step "2. Tests, against SQLite (never against production)"
# ---------------------------------------------------------------------------
if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
  PY="$VIRTUAL_ENV/bin/python"
elif [[ -x backend/.venv/bin/python ]]; then
  PY="$PWD/backend/.venv/bin/python"
elif [[ -x .venv/bin/python ]]; then
  PY="$PWD/.venv/bin/python"
else
  PY="$(command -v python3 || true)"
fi
[[ -n "$PY" ]] || die "no python found"

# A python without alembic gets as far as the migration step and dies there,
# which is the worst possible place to find out. Check now.
"$PY" -c "import alembic, sqlalchemy" 2>/dev/null \
  || die "$PY cannot import alembic/sqlalchemy.
         Use the backend virtualenv:  source backend/.venv/bin/activate"
ok "python: $PY"

if (( DRY_RUN )); then
  printf '  would run: pytest in backend/\n'
else
  ( cd backend && env -u PARLEY_TEST_ALLOW_REMOTE \
      TEST_DATABASE_URL="sqlite:///$(mktemp -u /tmp/parley_deploy_XXXX.db)" \
      "$PY" -m pytest -q ) || die "tests failed - not deploying"
fi
ok "tests green"

# ---------------------------------------------------------------------------
step "3. Migrate production"
# ---------------------------------------------------------------------------
echo "  current revision on production:"
if (( DRY_RUN )); then
  printf '    would run: alembic current\n'
else
  ( cd backend && DATABASE_URL="$PARLEY_PROD_DATABASE_URL" \
      "$PY" -m alembic current 2>&1 | sed 's/^/    /' )
fi

if (( ! DRY_RUN )); then
  echo
  read -r -p "  Apply migrations to PRODUCTION? type 'migrate' to continue: " reply
  [[ "$reply" == "migrate" ]] || die "aborted at the migration step (nothing changed)"
fi

if (( DRY_RUN )); then
  printf '  would run: alembic upgrade head\n'
else
  ( cd backend && DATABASE_URL="$PARLEY_PROD_DATABASE_URL" \
      "$PY" -m alembic upgrade head ) || die "migration failed - nothing has been pushed"
fi
ok "production schema is at head"
echo "  rollback if needed:  cd backend && DATABASE_URL=\"\$PARLEY_PROD_DATABASE_URL\" $PY -m alembic downgrade -1"

# ---------------------------------------------------------------------------
step "4. Merge and push"
# ---------------------------------------------------------------------------
if (( ! DRY_RUN )); then
  echo "  about to fast-forward $TARGET to $BRANCH and push to origin."
  read -r -p "  type 'ship' to continue: " reply
  [[ "$reply" == "ship" ]] || die "aborted before the merge (the migration HAS been applied; \
re-running this script will skip it as already-at-head)"
fi

run "git checkout $TARGET"
run "git merge --ff-only $BRANCH"
run "git push origin $TARGET"
ok "pushed - Render and Vercel will now build"

# ---------------------------------------------------------------------------
step "5. Wait for the deploy to land"
# ---------------------------------------------------------------------------
# /healthz is the signal: it does not exist before Phase 2, so a 200 means
# the new code is actually serving rather than the old one still being up.
if (( DRY_RUN )); then
  printf '  would poll %s/healthz until it returns 200\n' "$API"
else
  echo "  polling $API/healthz (404 until the new code is live)..."
  for i in $(seq 1 60); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$API/healthz" || true)"
    printf '    [%02d] %s\n' "$i" "$code"
    [[ "$code" == "200" ]] && { ok "/healthz is 200 - Phase 2+ is live"; break; }
    sleep 15
  done
  [[ "${code:-}" == "200" ]] || warn "/healthz never returned 200 - check Render's build log"

  echo "  checking the rest:"
  for p in / /readyz /api/ice; do
    printf '    %-10s -> %s\n' "$p" \
      "$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 "$API$p" || echo '---')"
  done
fi

# ---------------------------------------------------------------------------
step "Done"
# ---------------------------------------------------------------------------
cat <<'NOTE'
  Still yours to do, and none of it is scriptable:

  - TURN. Sign up at metered.ca, verify with
      cd backend && python tools/turn_probe.py <host> <port> <user> <cred>
    (exit 0 means a relay actually allocated), then set TURN_URLS,
    TURN_USERNAME and TURN_CREDENTIAL in Render. No rebuild needed.
    Until this is done, peers behind symmetric NAT cannot connect at all.

  - Do NOT sync render.yaml in Render's dashboard. It names 'parley-api';
    the live service is 'zoom-clone-api-in8u'. Syncing creates a SECOND
    service with a new URL and no environment variables.

  - Rotate the Neon API key if it was ever pasted into a chat.
NOTE
