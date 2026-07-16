"""Plan gating + trial auto-provisioning.

Entitlements activate ONLY from verified billing webhooks (non-negotiable #3)
— has_feature reads the Subscription row, never guesses."""

from sqlalchemy import select

from app.models import Subscription


def ensure_subscription(db, workspace_id) -> Subscription:
    """Trial auto-provision — every workspace gets a trialing subscription."""
    sub = db.execute(
        select(Subscription).where(Subscription.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if sub is None:
        sub = Subscription(workspace_id=workspace_id)
        db.add(sub)
        db.flush()
    return sub


def has_feature(db, workspace_id, feature: str) -> bool:
    sub = db.execute(
        select(Subscription).where(Subscription.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if sub is None or sub.status in ("suspended", "cancelled"):
        return False
    return bool((sub.addons or {}).get(feature))
