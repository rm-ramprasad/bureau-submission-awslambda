"""App users: who may use the app once signed in through the company identity provider (Cognito SSO).

Passwords, MFA and leavers' accounts are managed by the company identity provider. This table only says who may use
the app (active flag) and who is an administrator, matched on the e-mail address of the signed-in identity.
Managed with this module's command line (locally, or on AWS through the jobs Lambda, see RUNBOOK.md):

  python -m submissions.users add <username> --email asha.k@company.in --name "Asha K" [--admin]
  python -m submissions.users email <username> <e-mail>
  python -m submissions.users disable <username> | enable <username> | list
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Engine, String, Table, select, update
from sqlalchemy.exc import IntegrityError

from submissions.db import metadata, utcnow

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,50}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

app_user = Table(                                       # migrations 010, 011
    "app_user", metadata,
    Column("username", String(50), primary_key=True),
    Column("display_name", String(100), nullable=False),
    Column("email", String(254), unique=True),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("is_admin", Boolean, nullable=False, default=False),
    Column("last_login_at", DateTime),
    Column("created_at", DateTime, nullable=False),
)


class UserError(ValueError):
    """Shown to the user."""


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    email: str | None
    is_active: bool
    is_admin: bool
    last_login_at: datetime | None
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> "User":
        m = dict(row._mapping)
        m["is_active"], m["is_admin"] = bool(m["is_active"]), bool(m["is_admin"])
        return cls(**m)


def normalise_email(email: str | None) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise UserError(f"Not a valid e-mail address: {email!r}")
    return email


class UserRepository:
    def __init__(self, engine: Engine, clock: Callable[[], datetime] = utcnow):
        self.engine = engine
        self.clock = clock

    def add(self, username: str, display_name: str, email: str, is_admin: bool = False) -> User:
        username = (username or "").strip().lower()
        if not USERNAME_RE.match(username):
            raise UserError("Username: 3-50 characters, a-z, 0-9, dot, dash or underscore")
        if not (display_name or "").strip():
            raise UserError("Enter the user's name")
        email = normalise_email(email)
        if self.find(username):
            raise UserError(f"User {username} already exists")
        if self.find_by_email(email):
            raise UserError(f"{email} already belongs to another user")
        with self.engine.begin() as conn:
            conn.execute(app_user.insert().values(username=username, display_name=display_name.strip()[:100],
                                                  email=email, is_active=True, is_admin=is_admin,
                                                  created_at=self.clock()))
        return self.find(username)

    def find(self, username: str) -> User | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(app_user).where(app_user.c.username == (username or "").strip().lower())).first()
        return User.from_row(row) if row else None

    def find_by_email(self, email: str | None) -> User | None:
        if not email:
            return None
        with self.engine.connect() as conn:
            row = conn.execute(select(app_user).where(app_user.c.email == email.strip().lower())).first()
        return User.from_row(row) if row else None

    def list(self) -> list[User]:
        with self.engine.connect() as conn:
            return [User.from_row(r) for r in conn.execute(select(app_user).order_by(app_user.c.username))]

    def set_email(self, username: str, email: str) -> None:
        email = normalise_email(email)
        try:
            with self.engine.begin() as conn:
                if conn.execute(update(app_user).where(app_user.c.username == (username or "").lower())
                                .values(email=email)).rowcount == 0:
                    raise UserError(f"No user {username}")
        except IntegrityError:
            raise UserError(f"{email} already belongs to another user") from None

    def set_active(self, username: str, active: bool) -> None:
        with self.engine.begin() as conn:
            if conn.execute(update(app_user).where(app_user.c.username == (username or "").lower())
                            .values(is_active=active)).rowcount == 0:
                raise UserError(f"No user {username}")

    def record_login(self, username: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(app_user).where(app_user.c.username == username).values(last_login_at=self.clock()))


# ---------------------------------------------------------------- command line
def main(argv: list[str] | None = None, engine: Engine | None = None, actor: str = "admin-cli") -> int:
    from submissions.ops import audit

    ap = argparse.ArgumentParser(prog="python -m submissions.users", description="Manage app users (SSO)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("username")
    add.add_argument("--email", required=True, help="the user's company e-mail (as the identity provider sends it)")
    add.add_argument("--name", required=True)
    add.add_argument("--admin", action="store_true")
    em = sub.add_parser("email")
    em.add_argument("username")
    em.add_argument("email")
    for name in ("disable", "enable"):
        sub.add_parser(name).add_argument("username")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    if engine is None:
        from submissions.config import Settings
        from submissions.db import make_engine
        engine = make_engine(Settings.from_env().database_url)
    repo = UserRepository(engine)
    try:
        if args.cmd == "list":
            for u in repo.list():
                state = "active" if u.is_active else "disabled"
                print(f"{u.username:20} {u.display_name:30} {u.email or '(no e-mail)':35} {state:8} "
                      f"{'admin' if u.is_admin else '':5} last login {u.last_login_at or '-'}")
            return 0
        if args.cmd == "add":
            repo.add(args.username, args.name, args.email, args.admin)
            audit.record(engine, actor, "USER_ADDED", target=args.username.lower(), email=args.email.lower(),
                         admin=args.admin)
        elif args.cmd == "email":
            repo.set_email(args.username, args.email)
            audit.record(engine, actor, "USER_EMAIL_CHANGED", target=args.username.lower(), email=args.email.lower())
        else:
            repo.set_active(args.username, args.cmd == "enable")
            audit.record(engine, actor, f"USER_{args.cmd.upper()}D", target=args.username.lower())
        print(f"{args.cmd}: {args.username.lower()} done")
        return 0
    except UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
