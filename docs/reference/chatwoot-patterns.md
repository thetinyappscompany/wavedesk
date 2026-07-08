# Chatwoot patterns — reference for WaveDesk Phase 1–3 epics

Source: chatwoot-develop snapshot (founder-provided, 2026-07-08), Rails + Vue team-inbox.
Purpose: port **behavioral rules and data-model decisions**, not code (different stack:
Frappe/React). The proprietary `enterprise/` directory was ignored.

How to use: each section maps to a WaveDesk epic. When building that epic, follow these
rules unless the master build guide says otherwise (guide always wins).

---

## 1. Contacts (→ P1.8 contacts drawer + CSV import)

### Data model rules
- Contact fields: `name`, `email` (lowercased, blank→NULL), `phone_number` (strict E.164
  `+[1-9]\d{1,14}`), `identifier` (external/CRM key), `additional_attributes` JSON
  (app-written enrichment: company, city, country, social), `custom_attributes` JSON
  (user-defined), `last_activity_at` (default sort key, DESC NULLS LAST), `blocked` bool.
- Uniqueness **per account**: email, identifier (real DB unique indexes); phone unique at
  app level only. Blank-to-NULL conversion is what keeps unique indexes usable.
- Soft-fail on bad updates: if an inbound-message-driven update sets a malformed
  phone/email, revert to the previous value instead of erroring.
- "Resolved" vs anonymous contacts: lists only show contacts having at least one of
  email/phone/identifier.

### contact_inboxes — the one idea to steal wholesale
One human = one Contact, but a per-channel identity join (`contact_id`, `inbox_id`,
`source_id`, UNIQUE(inbox, source_id)) binds them to each channel address:
WhatsApp Cloud = phone without `+`, Twilio WA = `whatsapp:+phone`, email = email.
Conversations hang off the identity, not the contact. This is how the same person on
two of our numbers stays ONE contact. WaveDesk equivalent: WD Contact Identity
(contact, number, wa_id) — consider in P1.8; our current WD Chat→contact link stays,
identities dedupe the contact behind it.

### CSV import rules (DataImport model + job)
- Async job with status lifecycle pending→processing→completed/failed and counters
  `processed_records` / `total_records`.
- Recognized headers: `name,email,phone_number,identifier,labels,company_name,city`;
  **every unknown column lands in custom_attributes** (forward-compatible imports).
- Encoding hardening: force UTF-8, fall back via UTF-16LE round-trip dropping invalid
  bytes, strip UTF-8 BOM. (We already know Windows BOMs bite — test these.)
- Dedup/merge per row: find existing by **identifier → email → phone** (first hit wins),
  overwrite scalar fields only when CSV value present, JSON attrs merged non-destructively.
  Phones normalized by prepending `+` when missing.
- Unknown labels reject the ROW (import never auto-creates labels).
- Bulk insert in batches of 1000, duplicate keys ignored (unique indexes = last defense).
- **Partial-failure UX**: rejected rows are written to a downloadable errors CSV =
  original columns + `errors` column; user fixes and re-uploads. Completion email sent.

### Contact APIs
- list (resolved only, `labels` filter), search (`ILIKE` on name/email/phone/identifier;
  returns `has_more` instead of expensive COUNT), advanced filter endpoint, avatar
  upload/purge, page size 15.
- `contactable_inboxes` resolver: for one contact, compute per owned inbox the source_id
  you'd use to START an outbound conversation (skip channels lacking the needed identity)
  → powers the "new conversation" composer. We'll want this for compose-to-contact.

### Contact panel (conversation right sidebar)
- Collapsible reorderable sections, order persisted per user: ContactInfo (avatar,
  click-to-edit name/email/phone with copy buttons + duplicate-error mapping),
  conversation actions, custom attributes editor, **previous conversations across all
  channels** (cross-number history — our killer view for multi-number), notes, shared
  files. Actions: new message, edit, merge, delete.

### Merge (dedupe two contacts)
Single transaction: same-account guard → repoint conversations/messages/identities/notes
from mergee→base → deep-merge attrs (base wins, JSON unioned) → **delete mergee BEFORE
writing base's merged email/phone** (avoids unique-constraint collision) → emit event.

---

## 2. Labels & canned responses (→ P1.9)

### Labels
- Definition row per account: `title` (lowercased, letters/digits/-/_ only, unique per
  account), `color` (hex, default), `description`, `show_on_sidebar`.
- Attachment is a polymorphic tagging on BOTH conversations and contacts — same title,
  independent attachments. API replaces the whole label list (`{labels: [...]}`) rather
  than add/remove deltas; a union-style `add_labels` exists for automation.
- **Denormalize**: conversation caches `cached_label_list` (comma-joined) so the inbox
  list renders labels without a join per row. Changes to the list emit an activity/system
  message ("X added label y").
- Rename/delete must cascade: rename rewrites existing taggings (background job); delete
  strips the tag everywhere (background job).
- List filter: `labels` array param, OR semantics; sidebar saved-views are just
  single-label filters.

### Canned responses
- Row: `short_code` (unique per account) + `content`. Search endpoint ranks:
  short_code prefix (1.0) > short_code substring (0.5) > content substring (0.2).
- Composer `/` UX: menu opens the instant `/` is typed (minChars 0), **reply mode only,
  never on internal notes**; typing after `/` live-updates a server-side search; empty
  results hide the menu; ↑/↓ + Enter select (Enter swallowed while menu open so it
  doesn't send); on select the content replaces the `/term` range in the composer.
- Variables `{{contact.name}}`-style, substituted **client-side at insert time** so the
  agent sees + can edit real values; unresolved variables stay literal and trigger a
  warning before send. Supported keys: conversation.id, contact.{id,name,first_name,
  last_name,email,phone}, agent.{name,first_name,last_name,email}, inbox.{id,name}.
- Two-tier templating: agent-typed canned responses substitute in the frontend;
  automated/campaign sends substitute server-side (Liquid with contact/agent/inbox/account
  drops) at send time — that's our Phase 3 rules-engine tier. WhatsApp provider templates
  (positional {{1}}, {{2}}) are a separate processor.

### Keyboard shortcuts & command bar (UI-spec items in the master guide)
- tinykeys-style registry, one static list: Alt+J/K prev/next chat, Alt+E resolve,
  Cmd/Ctrl+Alt+E resolve→next, Alt+M snooze menu, Alt+P/L note vs reply, Cmd+/ help.
- Cmd+K palette: flat action list with parent/children drill-down
  ({id,title,section,icon,parent,handler}); actions assembled from per-domain builders
  (conversation, inbox, go-to, appearance, bulk); snooze accepts free text ("in 3 days").
  Reuse the same add/remove-label logic between palette and sidebar.

---

## 3. Realtime, unread, statuses, WhatsApp window (→ inbox polish + P3)

### Event catalog (theirs vs ours — grow ours toward this as features land)
Chatwoot broadcasts, per audience (inbox members / contact / single user / account):
`conversation.created|updated|read|status_changed|contact_changed|unread_count_changed`,
`conversation.typing_on|typing_off` (payload {conversation, user, is_private}, actor
excluded from recipients), `conversation.mentioned`, `assignee.changed`, `team.changed`,
`message.created|updated` (updated carries previous_changes; contact excluded for
private notes), `first.reply.created`, `notification.*` (with unread_count),
`contact.created|updated|merged|deleted`, `presence.update`.
WaveDesk today: wd:message, wd:message_status, wd:chat, wd:presence — wd:chat is our
coarse equivalent of status_changed+assignee.changed; split it when the UI needs
payload-level granularity (avoid refetching the whole list per event at scale).

### Typing indicator timing (adopt these constants)
- Client fires typing_on on first keystroke, auto typing_off after **4000ms idle**,
  immediate typing_off on composer blur. Sent over HTTP (not raw socket); server
  rebroadcasts to everyone except the actor.
- Ours: 10s viewing heartbeat + typing pings min-gap 4s with 15s Redis TTL. Close
  enough; consider explicit typing_off on blur for snappier clearing.

### Agent presence/availability
- Redis sorted set per account (score = last-ping unix ts); "online" = pinged within
  20s (contacts 90s, widget pings every 60s). Availability (online/busy/offline) is a
  separate Redis hash + DB fallback; `auto_offline=false` pins an agent available.
- presence.update pushes the full {user_id: status} map on subscribe + ping.

### Unread / read watermarks
- Per-conversation `agent_last_seen_at` watermark; unread = incoming messages newer
  than it. **Mark-as-unread** = set watermark to just before the last incoming message.
- Write-throttle: update_last_seen only writes if watermark blank or >1h old, except
  when there genuinely are unread messages — protects the DB from per-focus writes.
- Ours is a counter (unread_count++ on inbound, reset on mark_read); fine for P1, but
  the watermark model gives mark-as-unread + per-agent accuracy for free — consider at
  P2 when multiple agents share an inbox.

### Statuses / snooze / auto-reopen (P1.7 built; port the reopen rules)
- Same enum (open/resolved/pending/snoozed). snoozed_until cleared whenever leaving
  snoozed (we do this). Presets: next-reply, +1h, tomorrow 9:00, next Monday 9:00,
  next month 1st 9:00, custom. ("Until next reply" = snooze with NO timestamp, woken
  by the reopen rule below — worth adding to ours.)
- Background job reopens due snoozed conversations (we have the minutely cron).
- **Auto-reopen on inbound** (we should add in the consumer): on new incoming message —
  skip if muted; snoozed → open; resolved → open (or pending when a bot owns the inbox).

### WhatsApp 24-hour customer-service window (→ Cloud API chats, guide P1 feature 1)
- `can_reply?` = no window configured, OR now < last_incoming_message.created_at + 24h
  (window is per channel type; WhatsApp Cloud/Twilio-WA = 24h).
- Exposed as a boolean on the conversation payload; UI shows a banner + blocks the
  reply box when expired, offering template send instead (templates = our Phase 3).
- WaveDesk: compute window from last inbound message creation on cloud_api chats,
  expose `can_reply` in list_chats/list_messages, banner in ConversationPane. Baileys
  chats have no window.

