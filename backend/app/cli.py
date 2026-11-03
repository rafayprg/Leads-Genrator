"""Command line helpers. Run from the backend folder: .venv\\Scripts\\python -m app.cli --help"""
from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from sqlalchemy import delete, func, select

from .db import SessionLocal
from .ingest import leadgen_import
from .models import User, UserSession
from .security import hash_password, log, password_problem


def reset_password(email: str, ask=getpass.getpass) -> str:
    """Set a new password typed at the prompt (never shown, never an argument) and log the user out everywhere."""
    with SessionLocal() as session:
        user = session.scalars(select(User).where(func.lower(User.email) == email.strip().lower())).first()
        if user is None:
            return f"No account with email {email}"
        new = ask(f"New password for {user.email}: ")
        if new != ask("Type it again: "):
            return "The two passwords do not match; nothing changed"
        if problem := password_problem(new):
            return f"{problem}; nothing changed"
        user.password_hash = hash_password(new)
        session.execute(delete(UserSession).where(UserSession.user_id == user.id))
        log(session, "cli", "password_reset", user.email)
        return f"Password changed for {user.email}. Old logins were signed out."


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import-leadgen", help="copy leads from the old leadgen tool (its database is not changed)")
    p.add_argument("--db", type=Path, default=leadgen_import.DEFAULT_DB)
    p.add_argument("--include-dropped", action="store_true", help="also import leads the old tool filtered out")
    r = sub.add_parser("reset-password", help="set a new password for an account (asks for it, nothing is echoed)")
    r.add_argument("email")
    a = ap.parse_args(argv)

    if a.cmd == "reset-password":
        print(reset_password(a.email))
        return

    if a.cmd == "import-leadgen":
        with SessionLocal() as session:
            r = leadgen_import.run(session, a.db, a.include_dropped)
        print(f"read {r.read} old leads: {r.new} new, {r.updated} already here, "
              f"{r.skipped_dropped} dropped ones left out, {r.skipped_invalid} unusable")


if __name__ == "__main__":
    main()
