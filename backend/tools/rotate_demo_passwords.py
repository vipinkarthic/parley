"""Rotate the seeded demo account passwords.

Gating the seeder stops new rows; rows an earlier boot wrote keep the
published password until this runs. Rotates rather than deletes, so the demo
login survives.

    DATABASE_URL="..." python tools/rotate_demo_passwords.py [--dry-run]

Prints the new password once. Put it in DEMO_PASSWORD on Render.
"""
import argparse
import os
import secrets
import string
import sys

import bcrypt
from sqlalchemy import create_engine, text

DEMO_EMAILS = ("demo1@parley.app", "demo2@parley.app", "demo3@parley.app")

# Unambiguous, because this gets typed by hand rather than pasted.
ALPHABET = "".join(
    c for c in string.ascii_letters + string.digits if c not in "O0Il1"
)


def generate_password(length: int = 20) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def normalise(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--password-file")
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is unset. Pass the production connection string.")
        return 2

    if args.password_file:
        password = open(args.password_file).read().strip()
        if not password:
            print("--password-file is empty")
            return 2
    else:
        password = generate_password()

    engine = create_engine(normalise(url))
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, email, name FROM users WHERE email = ANY(:emails) "
                "ORDER BY id"
            ),
            {"emails": list(DEMO_EMAILS)},
        ).all()

        if not rows:
            print("No demo accounts found. Nothing to rotate.")
            return 0

        print(f"Found {len(rows)} demo account(s):")
        for row in rows:
            hosted = conn.execute(
                text("SELECT count(*) FROM meetings WHERE host_id = :uid"),
                {"uid": row.id},
            ).scalar_one()
            print(f"  id={row.id:<4} {row.email:<22} hosts {hosted} meeting(s)")

        if args.dry_run:
            print("\nDry run. Nothing was changed.")
            return 0

        # Only present after migration b1c4e7a90d31.
        has_stamp = bool(
            conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns WHERE "
                    "table_name = 'users' AND column_name = 'password_changed_at'"
                )
            ).first()
        )
        statement = (
            "UPDATE users SET password_hash = :h, password_changed_at = NOW() "
            "WHERE id = :uid"
            if has_stamp
            else "UPDATE users SET password_hash = :h WHERE id = :uid"
        )
        if has_stamp:
            print("\npassword_changed_at present, so existing tokens are revoked too.")

        # One hash per row, so equal passwords do not store equal values.
        for row in rows:
            digest = bcrypt.hashpw(
                password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")
            conn.execute(text(statement), {"h": digest, "uid": row.id})

    print(f"\nRotated {len(rows)} account(s).")
    print(f"\n    new demo password:  {password}\n")
    print("Set DEMO_PASSWORD to this value on Render, then confirm the old one")
    print("is refused and this one is accepted before relying on it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
