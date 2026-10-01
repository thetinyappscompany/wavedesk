"""Platform-admin account recovery — run INSIDE the backend container.

Last-resort tooling for the platform owner when nobody can reach /admin: list
the accounts, grant the platform-admin flag, or set a new password. Needs only
a shell on the backend app (which already implies database access), so it adds
no privilege you didn't have — it just makes the safe version easy.

    cd /srv
    python -m scripts.admin_recover --list
    python -m scripts.admin_recover --grant you@company.com
    python -m scripts.admin_recover --set-password you@company.com
    python -m scripts.admin_recover --reset-link you@company.com

The password is TYPED AT THE PROMPT, never passed as an argument — arguments
land in shell history and `ps` output. Changing a password signs out every
existing session for that user, same as the self-serve reset flow.
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import User
from app.security import hash_password

MIN_PASSWORD_LENGTH = 8


def _find(db, email: str) -> User:
    user = db.execute(
        select(User).where(User.email == email.strip().lower())
    ).scalar_one_or_none()
    if user is None:
        sys.exit(f"No account with email {email!r}. Run --list to see what exists.")
    return user


def _kill_sessions(user_id: str) -> None:
    """Best-effort: a password change must not leave old sessions alive."""
    try:
        from app import sessions

        n = sessions.destroy_others(user_id, None)
        print(f"  signed out {n} existing session(s)")
    except Exception as err:  # noqa: BLE001 — Redis trouble must not block recovery
        print(f"  ! could not clear sessions ({type(err).__name__}) — change still applied")


def cmd_list(db) -> None:
    users = db.execute(select(User).order_by(User.created_at)).scalars().all()
    if not users:
        print("No accounts exist yet.")
        return
    print(f"\n{len(users)} account(s):\n")
    print(f"  {'email':<38} {'admin':<6} {'enabled':<8} created")
    for u in users:
        created = u.created_at.strftime("%Y-%m-%d") if u.created_at else "?"
        print(
            f"  {u.email:<38} {'YES' if u.is_platform_admin else '-':<6} "
            f"{'yes' if u.enabled else 'NO':<8} {created}"
        )
    admins = [u.email for u in users if u.is_platform_admin]
    print(f"\nPlatform admins: {', '.join(admins) if admins else 'NONE — use --grant'}\n")


def cmd_grant(db, email: str) -> None:
    user = _find(db, email)
    if user.is_platform_admin and user.enabled:
        print(f"{user.email} is already an enabled platform admin — nothing to do.")
        return
    user.is_platform_admin = True
    user.enabled = True
    db.commit()
    print(f"{user.email} is now a platform admin (and enabled). /admin is reachable.")


def _read_secret(prompt: str) -> str:
    """Hidden input on a terminal; plain stdin otherwise.

    getpass() reads /dev/tty, not stdin — under a non-interactive exec (no -t,
    or a piped heredoc) it blocks forever with no output at all. Detect that
    and read stdin instead so this tool can never hang on you.
    """
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    print(f"{prompt}(not a terminal — input will be visible)")
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return (line.splitlines() or [""])[0]


def cmd_set_password(db, email: str) -> None:
    user = _find(db, email)
    try:
        first = _read_secret(f"New password for {user.email}: ")
        second = _read_secret("Confirm: ")
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nAborted — no change made.")
    if first != second:
        sys.exit("Passwords do not match — no change made.")
    if len(first) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    user.password_hash = hash_password(first)
    user.enabled = True
    db.commit()
    print(f"Password updated for {user.email}.")
    _kill_sessions(str(user.id))
    print("Sign in at the SPA with the new password.")


def cmd_reset_link(db, email: str) -> None:
    """Issue a reset link instead of setting the password here. Needs the
    password-recovery release (the password_reset_tokens table)."""
    try:
        from app import passwords
    except ImportError:
        sys.exit("This build predates password recovery — use --set-password instead.")
    user = _find(db, email)
    token = passwords.issue(db, user, by_admin=True)
    db.commit()
    print(f"\nSingle-use link for {user.email} "
          f"(expires in {passwords.TOKEN_TTL_MINUTES} min):\n")
    print(f"  {passwords.reset_link(token)}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="show every account")
    group.add_argument("--grant", metavar="EMAIL", help="make this account a platform admin")
    group.add_argument("--set-password", metavar="EMAIL", help="set a new password (prompted)")
    group.add_argument("--reset-link", metavar="EMAIL", help="print a single-use reset link")
    args = parser.parse_args()

    db = get_sessionmaker()()
    try:
        if args.list:
            cmd_list(db)
        elif args.grant:
            cmd_grant(db, args.grant)
        elif args.set_password:
            cmd_set_password(db, args.set_password)
        elif args.reset_link:
            cmd_reset_link(db, args.reset_link)
    finally:
        db.close()


if __name__ == "__main__":
    main()
