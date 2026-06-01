"""Create (or promote) an admin account from the command line.

Usage::

    python -m scripts.seed_admin --email admin@acme.com --password 'strong-pass'
    # or via env:
    ADMIN_EMAIL=admin@acme.com ADMIN_PASSWORD='strong-pass' python -m scripts.seed_admin

Idempotent: if the email already exists it is promoted to ``admin`` (and the
password is reset when one is provided). Use this when ``AUTH_ENFORCE=true`` and
you need a guaranteed superuser without open registration.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def seed(email: str, password: str) -> None:
    """Create or promote an admin account."""
    from core.memory import memory
    from core.security import hash_password

    email = email.lower().strip()
    existing = await memory.get_user_by_email(email)
    if existing:
        await memory.update_user(
            existing["id"], role="admin", password_hash=hash_password(password)
        )
        print(f"✓ Promoted existing account to admin: {email}")
    else:
        await memory.create_user(
            email=email,
            name="Administrator",
            role="admin",
            password_hash=hash_password(password),
            provider="local",
        )
        print(f"✓ Created admin account: {email}")


def main() -> None:
    """Parse args/env and run the seed."""
    parser = argparse.ArgumentParser(description="Create or promote an admin user.")
    parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD", ""))
    args = parser.parse_args()

    if not args.email or not args.password:
        parser.error("provide --email/--password or set ADMIN_EMAIL/ADMIN_PASSWORD")
    if len(args.password) < 8:
        parser.error("password must be at least 8 characters")

    asyncio.run(seed(args.email, args.password))


if __name__ == "__main__":
    main()
