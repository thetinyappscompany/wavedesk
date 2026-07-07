"""Trial auto-provisioning (master doc §3.2): every new WD Workspace atomically
gets a trialing WD Subscription (14d), a WD Wallet at zero, and the time-boxed
AI add-on trial preview. Runs in the same transaction as the workspace insert."""

import frappe
from frappe.utils import add_days, now_datetime

TRIAL_PLAN = "Trial"
DEFAULT_TRIAL_DAYS = 14


def provision_workspace(doc, method: str | None = None) -> None:
    """after_insert hook on WD Workspace. Idempotent."""
    from wavedesk.plan.gating import _parse
    from wavedesk.wallet.ledger import get_or_create_wallet

    if frappe.db.exists("WD Subscription", {"workspace": doc.name}):
        return

    plan = doc.plan or TRIAL_PLAN
    if not doc.plan:
        doc.db_set("plan", plan, update_modified=False)

    trial_days = DEFAULT_TRIAL_DAYS
    plan_limits = _parse(frappe.db.get_value("WD Plan", plan, "limits"))
    if plan_limits.get("trial_days"):
        trial_days = int(plan_limits["trial_days"])

    trial_end = add_days(now_datetime(), trial_days)
    subscription = frappe.new_doc("WD Subscription")
    subscription.update(
        {
            "workspace": doc.name,
            "plan": plan,
            "status": "trialing",
            "provider": "zoho_billing",
            "current_period_end": trial_end,
            # Time-boxed AI preview to create desire (§3.2); real add-on via Zoho (P5).
            "addons": frappe.as_json({"ai_addon_trial_until": str(trial_end)}),
        }
    )
    subscription.insert(ignore_permissions=True)

    get_or_create_wallet(doc.name)
