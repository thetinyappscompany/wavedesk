"""Declarative table map: one Spec per Frappe doctype we migrate.

A field is `(dst_column, src_column, kind)`:
    "S"        scalar / text / number — passed through
    "B"        Frappe Check (0/1 int) → bool
    "J"        Frappe Long Text JSON string → dict/list (JSONB)
    "F" / "I"  float / int (Currency, Float, Int) — passed through
    "D"        datetime — passed through (Frappe stores naive; target is tz-aware)
    "L:<DT>"   Link — src holds the referent's Frappe name → uuid5("<DT>", name)

`id` is always uuid5(doctype, name). `workspace_id` is derived from the row's
`workspace` Link when has_workspace is True. created_at/updated_at come from
Frappe's `creation`/`modified`. Only columns listed here are migrated — Frappe
housekeeping cols (owner/docstatus/idx…) and dropped fields (secrets like
cloud_token, regenerable state) are deliberately left out.

SPECS is ordered so every referenced table is inserted before its referrers
(FK constraints are checked per-statement in Postgres).
"""

from dataclasses import dataclass

from app import models


@dataclass(frozen=True)
class Spec:
    doctype: str
    model: type
    fields: list[tuple[str, str, str]]
    has_workspace: bool = True
    src_table: str | None = None  # defaults to f"tab{doctype}"
    # child tables carry no `name`-based workspace link; the parent FK column
    # is derived from Frappe's `parent` via parent_link = (dst_col, "<DT>").
    parent_link: tuple[str, str] | None = None

    @property
    def table(self) -> str:
        return self.src_table or f"tab{self.doctype}"


# ── ordered so referents precede referrers ──────────────────────────────────
SPECS: list[Spec] = [
    # Identity — Frappe `tabUser`, name == email.
    Spec(
        "User", models.User,
        [("email", "name", "S"), ("first_name", "first_name", "S"),
         ("enabled", "enabled", "B")],
        has_workspace=False, src_table="tabUser",
    ),
    Spec(
        "WD Workspace", models.Workspace,
        [("name", "workspace_name", "S"), ("plan", "plan", "S"),
         ("settings", "settings", "J"), ("suspended", "suspended", "B")],
        has_workspace=False,
    ),
    Spec(
        "WD Workspace Member", models.WorkspaceMember,
        [("user_id", "user", "L:User"), ("role", "role", "S")],
        has_workspace=False, parent_link=("workspace_id", "WD Workspace"),
    ),
    Spec(
        "WD WhatsApp Number", models.WhatsAppNumber,
        [("display_name", "display_name", "S"), ("connection_type", "connection_type", "S"),
         ("status", "status", "S"), ("session_ref", "session_ref", "S"),
         ("phone", "phone", "S"), ("phone_number_id", "phone_number_id", "S"),
         ("waba_id", "waba_id", "S"), ("warmup_started_on", "warmup_started_on", "D"),
         ("daily_send_limit", "daily_send_limit", "I"), ("health_score", "health_score", "I"),
         ("risk_level", "risk_level", "S")],
    ),
    Spec(
        "WD Contact", models.Contact,
        [("phone", "phone", "S"), ("full_name", "full_name", "S"),
         ("email", "email", "S"), ("opt_out", "opt_out", "B"),
         ("erased", "erased", "B"), ("tags", "tags", "S"),
         ("custom_attributes", "custom_attributes", "J")],
    ),
    Spec(
        "WD Team", models.Team,
        [("team_name", "team_name", "S"), ("routing", "routing", "S"),
         ("capacity_per_agent", "capacity_per_agent", "I")],
    ),
    Spec(
        "WD Team Member", models.TeamMember,
        [("user_id", "user", "L:User")],
        has_workspace=False, parent_link=("team_id", "WD Team"),
    ),
    Spec(
        "WD Label", models.Label,
        [("title", "title", "S"), ("color", "color", "S"),
         ("description", "description", "S")],
    ),
    Spec(
        "WD Canned Response", models.CannedResponse,
        [("shortcode", "shortcode", "S"), ("content", "content", "S")],
    ),
    Spec(
        "WD Group", models.Group,
        [("wa_group_id", "wa_group_id", "S"), ("subject", "subject", "S"),
         ("description", "description", "S"), ("member_count", "member_count", "I"),
         ("invite_link", "invite_link", "S"), ("owned_by_us", "owned_by_us", "B"),
         ("number_id", "number", "L:WD WhatsApp Number")],
    ),
    Spec(
        "WD Group Member", models.GroupMember,
        [("group_id", "group", "L:WD Group"), ("participant_id", "participant_id", "S"),
         ("role", "role", "S"), ("contact_id", "contact", "L:WD Contact"),
         ("joined_at", "joined_at", "D"), ("left_at", "left_at", "D")],
        has_workspace=False,
    ),
    Spec(
        "WD Chat", models.Chat,
        [("chat_type", "chat_type", "S"), ("wa_chat_id", "wa_chat_id", "S"),
         ("status", "status", "S"), ("number_id", "number", "L:WD WhatsApp Number"),
         ("contact_id", "contact", "L:WD Contact"),
         ("assigned_agent_id", "assigned_agent", "L:User"),
         ("assigned_team_id", "assigned_team", "L:WD Team"),
         ("group_id", "group", "L:WD Group"), ("unread_count", "unread_count", "I"),
         ("last_message_at", "last_message_at", "D"),
         ("first_response_at", "first_response_at", "D"),
         ("snoozed_until", "snoozed_until", "D"),
         ("pending_query_since", "pending_query_since", "D"),
         ("resolved_at", "resolved_at", "D"),
         # NB: sla_policy is intentionally NOT mapped — WD SLA Policy is in
         # NOT_MIGRATED (policies are re-created on the new backend), so mapping
         # the Link would point sla_policy_id at a non-existent sla_policies row
         # and the FK would abort the whole chats load. The due-time stamps below
         # still migrate; re-attaching a policy is a post-cutover config step.
         ("first_response_due", "first_response_due", "D"),
         ("resolution_due", "resolution_due", "D"),
         ("first_response_breached", "first_response_breached", "B"),
         ("resolution_breached", "resolution_breached", "B")],
    ),
    Spec(
        "WD Chat Label", models.ChatLabel,
        [("label_id", "label", "L:WD Label")],
        has_workspace=False, parent_link=("chat_id", "WD Chat"),
    ),
    Spec(
        "WD Message", models.Message,
        [("chat_id", "chat", "L:WD Chat"), ("direction", "direction", "S"),
         ("status", "status", "S"), ("wa_message_id", "wa_message_id", "S"),
         ("message_type", "message_type", "S"), ("body", "body", "S"),
         ("sender_agent_id", "sender_agent", "L:User"),
         ("sender_contact_id", "sender_contact", "L:WD Contact"),
         ("sender_jid", "sender_jid", "S"), ("sender_name", "sender_name", "S"),
         ("sent_via", "sent_via", "S"), ("flagged", "flagged", "B"),
         ("flag_reason", "flag_reason", "S"), ("media_key", "media_key", "S"),
         ("media_mimetype", "media_mimetype", "S"),
         ("media_filename", "media_filename", "S"), ("media_size", "media_size", "I"),
         ("media_duration", "media_duration", "I"), ("is_voice", "is_voice", "B"),
         ("transcript", "transcript", "S")],
    ),
    Spec(
        "WD Invite", models.Invite,
        [("email", "email", "S"), ("role", "role", "S"), ("token", "token", "S"),
         ("status", "status", "S"), ("expires_at", "expires_at", "D")],
    ),
    Spec(
        "WD Monitoring Rule", models.MonitoringRule,
        [("rule_name", "rule_name", "S"), ("rule_type", "rule_type", "S"),
         ("keyword", "keyword", "S"), ("group_id", "group", "L:WD Group"),
         ("enabled", "enabled", "B"), ("notify_agents", "notify_agents", "B")],
    ),
    Spec(
        "WD Ticket", models.Ticket,
        [("title", "title", "S"), ("status", "status", "S"), ("priority", "priority", "S"),
         ("chat_id", "chat", "L:WD Chat"),
         ("source_message_id", "source_message", "L:WD Message"),
         ("assigned_agent_id", "assigned_agent", "L:User"),
         ("team_id", "team", "L:WD Team"), ("resolution_note", "resolution_note", "S")],
    ),
    Spec(
        "WD Alert", models.Alert,
        [("kind", "kind", "S"), ("rule_id", "rule", "L:WD Monitoring Rule"),
         ("group_id", "group", "L:WD Group"), ("chat_id", "chat", "L:WD Chat"),
         ("message_id", "message", "L:WD Message"), ("detail", "detail", "S"),
         ("seen", "seen", "B")],
    ),
    Spec(
        "WD Subscription", models.Subscription,
        [("plan", "plan", "S"), ("status", "status", "S"), ("addons", "addons", "J"),
         ("provider", "provider", "S"), ("zoho_customer_id", "zoho_customer_id", "S"),
         ("zoho_subscription_id", "zoho_subscription_id", "S"),
         ("current_period_end", "current_period_end", "D")],
    ),
    # Money — append-only ledger (non-negotiable #2). running_balance is NOT
    # migrated: balance is always derived in the new schema.
    Spec(
        "WD Wallet Transaction", models.WalletTransaction,
        [("txn_type", "txn_type", "S"), ("amount", "amount", "F"),
         ("reference", "reference", "S"), ("idempotency_key", "idempotency_key", "S")],
    ),
    Spec(
        "WD AI Agent Config", models.AiAgentConfig,
        [("enabled", "enabled", "B"), ("persona_prompt", "persona_prompt", "S"),
         ("confidence_threshold", "confidence_threshold", "F"),
         ("handoff_team_id", "handoff_team", "L:WD Team"),
         ("after_hours_only", "after_hours_only", "B"),
         ("auto_ticket", "auto_ticket", "B")],
    ),
    Spec(
        "WD AI Flag Rule", models.AiFlagRule,
        [("flag_key", "flag_key", "S"), ("label", "label", "S"), ("prompt", "prompt", "S"),
         ("action", "action", "S"), ("priority", "priority", "S"),
         ("enabled", "enabled", "B")],
    ),
    Spec(
        "WD Knowledge Doc", models.KnowledgeDoc,
        [("title", "title", "S"), ("content", "content", "S"), ("status", "status", "S")],
    ),
]

# Doctypes deliberately NOT migrated (regenerable, ephemeral, or operational
# state that resets cleanly on the new backend). Documented in the runbook.
NOT_MIGRATED: list[str] = [
    "WD Automation Rule / Log",   # rules re-created; logs are history
    "WD SLA Policy / Event",      # policies re-created; events are history
    "WD Broadcast / Recipient",   # completed sends are history; in-flight paused
    "WD Scheduled Message",       # re-created; run state resets
    "WD Segment",                 # live-evaluated; re-created
    "WD Message Template",        # re-submitted to Meta
    "WD Usage Record",            # internal AI metering; resets monthly
    "WD Webhook Delivery",        # delivery attempts are ephemeral
    "WD Data Export",             # re-requested on demand
    "WD API Key",                 # re-issued (hashes; secrets shown once)
    "WD User 2FA",                # re-enrolled (secrets can't be re-shown)
    "WD Audit Log",               # history; export separately if needed
    "sessions",                   # users re-authenticate after cutover
]
