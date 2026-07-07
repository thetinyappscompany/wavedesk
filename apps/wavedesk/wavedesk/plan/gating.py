"""Quota + feature gating (master doc §3.2) — built once, used by every later feature.

Reads WD Plan limits/features JSON through the workspace's WD Subscription.
Client-facing surface is plan_context() ONLY — and it must never leak anything
from WD AI Pricing Config (leak test enforces).
"""

import json
from collections.abc import Callable
from functools import wraps

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

ENTITLED_STATUSES = ("trialing", "active")

# Error codes the frontend switches on (upgrade CTA rendering).
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
FEATURE_NOT_AVAILABLE = "FEATURE_NOT_AVAILABLE"

SOFT_LIMIT_RATIO = 0.8


class QuotaExceededError(frappe.ValidationError):
    pass


class FeatureNotAvailableError(frappe.PermissionError):
    pass


def get_subscription(workspace: str) -> dict | None:
    """The workspace's entitling subscription (trialing/active), or None."""
    rows = frappe.get_all(
        "WD Subscription",
        filters={"workspace": workspace, "status": ("in", ENTITLED_STATUSES)},
        fields=["name", "plan", "status", "current_period_end", "addons"],
        order_by="creation desc",
        limit=1,
    )
    return rows[0] if rows else None


def _parse(value) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(value)


def get_limits(workspace: str) -> dict:
    sub = get_subscription(workspace)
    if not sub:
        return {}
    return _parse(frappe.db.get_value("WD Plan", sub["plan"], "limits"))


def get_addons(workspace: str) -> dict:
    sub = get_subscription(workspace)
    return _parse(sub["addons"]) if sub else {}


# --- usage counters — extendable map (add a counter when adding a quota) -------

def _count_numbers(workspace: str) -> int:
    return frappe.db.count("WD WhatsApp Number", {"workspace": workspace})


def _count_agents(workspace: str) -> int:
    member = frappe.qb.DocType("WD Workspace Member")
    rows = (
        frappe.qb.from_(member)
        .select(member.name)
        .where((member.parent == workspace) & (member.parenttype == "WD Workspace"))
    ).run()
    return len(rows)


RESOURCE_COUNTERS: dict[str, Callable[[str], int]] = {
    "numbers": _count_numbers,
    "agents": _count_agents,
}


def get_usage(workspace: str, resource: str) -> int:
    counter = RESOURCE_COUNTERS.get(resource)
    if counter is None:
        frappe.throw(_(f"Unknown quota resource: {resource}"))
    return counter(workspace)


def check_quota(workspace: str, resource: str, increment: int = 1) -> None:
    """Raise QuotaExceededError (with upgrade-CTA code) if the action would breach
    the plan cap; fire the soft-limit notification at ≥80%."""
    counter = RESOURCE_COUNTERS.get(resource)
    if counter is None:
        frappe.throw(_(f"Unknown quota resource: {resource}"))
    limits = get_limits(workspace)
    limit = limits.get(resource)
    if limit in (None, ""):
        return  # not limited on this plan
    usage = counter(workspace)
    projected = usage + increment
    if projected > int(limit):
        frappe.throw(
            _(
                f"Plan limit reached for {resource} ({usage}/{limit}). "
                f"Upgrade your plan or purchase an add-on."
            ),
            QuotaExceededError,
            title=QUOTA_EXCEEDED,
        )
    if projected >= SOFT_LIMIT_RATIO * int(limit):
        _notify_soft_limit(workspace, resource, projected, int(limit))


def _notify_soft_limit(workspace: str, resource: str, usage: int, limit: int) -> None:
    """Notification hook placeholder — in-app + email wiring lands in Phase 1."""
    frappe.logger("wavedesk.plan").info(
        {
            "event": "quota_soft_limit",
            "workspace": workspace,
            "resource": resource,
            "usage": usage,
            "limit": limit,
        }
    )


# --- features -------------------------------------------------------------------

def has_feature(workspace: str, flag: str) -> bool:
    """Server-side feature gate. ai_addon honours the time-boxed trial preview."""
    sub = get_subscription(workspace)
    if not sub:
        return False
    features = _parse(frappe.db.get_value("WD Plan", sub["plan"], "features"))
    addons = _parse(sub["addons"])
    if addons.get(flag) or features.get(flag) is True:
        return True
    if flag == "ai_addon":
        trial_until = addons.get("ai_addon_trial_until")
        if trial_until and get_datetime(trial_until) >= now_datetime():
            return True
    return False


def requires_feature(flag: str) -> Callable:
    """Decorator for whitelisted methods: 402-style block without the feature."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from wavedesk.tenancy import get_active_workspace

            workspace = get_active_workspace()
            if not has_feature(workspace, flag):
                frappe.throw(
                    _(f"This feature requires the {flag} add-on."),
                    FeatureNotAvailableError,
                    title=FEATURE_NOT_AVAILABLE,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# --- client-facing context (leak-tested) ------------------------------------------

# plan_context may ONLY ever contain these top-level keys — the leak test pins this.
PLAN_CONTEXT_ALLOWED_KEYS = frozenset(
    {
        "workspace",
        "plan",
        "subscription_status",
        "current_period_end",
        "limits",
        "usage",
        "features",
    }
)


@frappe.whitelist()
def plan_context() -> dict:
    """Client-safe plan/entitlement snapshot for the frontend. NOTHING from
    WD AI Pricing Config may ever ride along here (leak test enforces)."""
    from wavedesk.tenancy import get_active_workspace

    workspace = get_active_workspace()
    sub = get_subscription(workspace)
    limits = get_limits(workspace)
    addons = get_addons(workspace)
    return {
        "workspace": workspace,
        "plan": sub["plan"] if sub else None,
        "subscription_status": sub["status"] if sub else None,
        "current_period_end": str(sub["current_period_end"]) if sub else None,
        "limits": limits,
        "usage": {resource: get_usage(workspace, resource) for resource in RESOURCE_COUNTERS},
        "features": {
            "ai_addon": has_feature(workspace, "ai_addon"),
            "ai_addon_trial_until": addons.get("ai_addon_trial_until"),
        },
    }
