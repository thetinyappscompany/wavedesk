app_name = "wavedesk"
app_title = "WaveDesk"
app_publisher = "WaveDesk"
app_description = "Multi-tenant WhatsApp team-inbox & group-management SaaS"
app_email = "bacokushal@gmail.com"
app_license = "Proprietary"

# Seeding is idempotent — safe on every migrate (plans + AI pricing config).
after_install = "wavedesk.setup.install.after_install"
after_migrate = ["wavedesk.setup.install.seed_defaults"]

# --- Document events ----------------------------------------------------------
doc_events = {
    "WD Workspace": {
        # §3.2: trial subscription + wallet + AI preview, same transaction as insert
        "after_insert": "wavedesk.plan.provisioning.provision_workspace",
    },
    # Outbound webhook (P5): ticket.created fires for EVERY creator (API, AI
    # flagging, auto-ticket, public API) via one after_insert hook.
    "WD Ticket": {
        "after_insert": "wavedesk.webhooks.dispatch.on_ticket_created",
    },
}

# --- Scheduler ---------------------------------------------------------------
scheduler_events = {
    # Poll wa:events every minute as the RQ baseline; a dedicated long-running
    # consumer worker replaces this for sub-second latency in Phase 1 (p95 < 2s).
    "cron": {
        "* * * * *": [
            "wavedesk.pipeline.consumer.process_wa_events",
            "wavedesk.inbox.unsnooze_due_chats",
            "wavedesk.sla.check_breaches",
            "wavedesk.schedules.run_due_schedules",
            "wavedesk.webhooks.dispatch.retry_due",
        ],
    },
    "daily": [
        "wavedesk.wallet.ledger.reconcile_all_wallets",
        "wavedesk.analytics.compute_engagement_scores",
        "wavedesk.antiban.recompute_all_health",
        "wavedesk.billing.reconcile.reconcile_all",
        "wavedesk.compliance.privacy.apply_retention",
    ],
}

# --- Tenancy (master doc §3.1) ---------------------------------------------
# Single registration point. The doctype lists live in wavedesk/tenancy.py;
# the meta-test in tests/test_tenancy.py fails CI if any WD DocType is missing.
from wavedesk.tenancy import TENANT_DOCTYPES as _TENANT_DOCTYPES  # noqa: E402

permission_query_conditions = {
    "WD Workspace": "wavedesk.tenancy.workspace_permission_query",
    **{dt: "wavedesk.tenancy.permission_query" for dt in _TENANT_DOCTYPES},
}

has_permission = {
    "WD Workspace": "wavedesk.tenancy.has_permission",
    **{dt: "wavedesk.tenancy.has_permission" for dt in _TENANT_DOCTYPES},
}
