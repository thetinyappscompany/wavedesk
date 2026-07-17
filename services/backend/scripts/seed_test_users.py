"""Dev/staging seed — a QA workspace with Owner (platform admin), Admin, and
Agent accounts, so you have known logins for manual testing. Prints the
credentials ONCE (passwords are generated, never stored in the repo).

    cd services/backend
    WD_ALLOW_SEED=1 python -m scripts.seed_test_users

DEV/STAGING ONLY. It sets known passwords, so it refuses to run unless
WD_ALLOW_SEED=1 is set explicitly — never point it at a production DB. Re-running
is safe: existing accounts are reused and their passwords are RESET to fresh
generated values (so the printed credentials always work).
"""

import os
import secrets
import sys

from sqlalchemy import select

from app.db import get_sessionmaker
from app.gating import ensure_subscription
from app.models import User, Workspace, WorkspaceMember
from app.security import hash_password

WORKSPACE_NAME = "QA Workspace"

# (email, display name, role, is_platform_admin)
ACCOUNTS = [
    ("owner@wavedesk.test", "QA Owner", "Owner", True),
    ("admin@wavedesk.test", "QA Admin", "Admin", False),
    ("agent@wavedesk.test", "QA Agent", "Agent", False),
]


def _upsert_user(db, email: str, name: str, is_admin: bool) -> tuple[User, str]:
    password = secrets.token_urlsafe(12)  # ~16 chars, strong
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(email=email, first_name=name, password_hash=hash_password(password),
                    is_platform_admin=is_admin)
        db.add(user)
    else:
        user.password_hash = hash_password(password)  # reset so printed creds work
        user.first_name = name
        user.is_platform_admin = is_admin
    db.flush()
    return user, password


def main() -> None:
    if os.environ.get("WD_ALLOW_SEED") != "1":
        sys.exit(
            "Refusing to seed known-password accounts. This is a DEV/STAGING tool.\n"
            "Set WD_ALLOW_SEED=1 to confirm, and make sure WD_DATABASE_URL is NOT prod."
        )

    db = get_sessionmaker()()
    creds: list[tuple[str, str, str, bool]] = []
    try:
        ws = db.execute(
            select(Workspace).where(Workspace.name == WORKSPACE_NAME)
        ).scalar_one_or_none()
        if ws is None:
            ws = Workspace(name=WORKSPACE_NAME)
            db.add(ws)
            db.flush()
        ws_id = ws.id

        for email, name, role, is_admin in ACCOUNTS:
            user, password = _upsert_user(db, email, name, is_admin)
            member = db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == ws_id,
                    WorkspaceMember.user_id == user.id,
                )
            ).scalar_one_or_none()
            if member is None:
                db.add(WorkspaceMember(workspace_id=ws_id, user_id=user.id, role=role))
            else:
                member.role = role
            creds.append((email, password, role, is_admin))

        ensure_subscription(db, ws_id)  # trial auto-provision, same as onboarding
        db.commit()
    finally:
        db.close()

    print("\n=== WaveDesk QA seed — credentials (shown once) ===")
    print(f"Workspace: {WORKSPACE_NAME}  (id {ws_id})")
    for email, password, role, is_admin in creds:
        tag = "   ← platform admin (/admin)" if is_admin else ""
        print(f"  {role:<6}  {email:<22}  {password}{tag}")
    print("\nLog in at the SPA login page with any of the above.\n")


if __name__ == "__main__":
    main()
