/**
 * @wavedesk/api-client — shared client for the WaveDesk Frappe API.
 *
 * Session 0.1: types + client shell only. Methods are added per epic as the
 * corresponding Frappe endpoints land (login/session first, in Phase 1 onboarding).
 * Consumed by `frontend` now and `mobile` (Expo) from week 14 — keep it
 * platform-neutral: no DOM/React imports, fetch is injectable.
 */

export interface ApiClientOptions {
  /** Frappe base URL, e.g. https://app.wavedesk.example or '' for same-origin. */
  baseUrl: string;
  /** Injectable fetch for non-browser runtimes (React Native, tests). */
  fetchFn?: typeof fetch;
}

export interface FrappeMethodResponse<T> {
  message: T;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: string,
  ) {
    super(`API request failed with status ${String(status)}`);
    this.name = 'ApiError';
  }
}

export interface WdNumber {
  name: string;
  phone: string | null;
  display_name: string | null;
  connection_type: 'baileys' | 'cloud_api';
  status: 'connecting' | 'connected' | 'disconnected' | 'banned';
  health_score: number;
  daily_send_limit: number;
  warmup_stage: number;
  waba_id: string | null;
  phone_number_id: string | null;
}

/** Per-number health + warm-up snapshot (P3.6 anti-ban). */
export interface WdNumberHealth {
  name: string;
  phone: string | null;
  display_name: string | null;
  status: WdNumber['status'];
  health_score: number;
  risk_level: 'low' | 'medium' | 'high';
  daily_send_limit: number;
  warmup_started_on: string | null;
  health_checked_at: string | null;
  warmup_day: number;
  daily_cap: number | null; // null = unlimited
  sent_today: number;
  warming: boolean;
}

export interface NumberStatus {
  number: string;
  status: WdNumber['status'];
  /** base64 data-URL QR while pairing, null otherwise */
  qr: string | null;
}

/** A label as applied to a chat (denormalized for chip rendering). */
export interface WdChatLabelChip {
  label: string;
  title: string;
  color: string;
}

export interface WdChat {
  name: string;
  chat_type: 'dm' | 'group';
  status: 'open' | 'pending' | 'resolved' | 'snoozed';
  number: string | null;
  contact: string | null;
  assigned_agent: string | null;
  assigned_team: string | null;
  snoozed_until: string | null;
  last_message_at: string | null;
  unread_count: number;
  wa_chat_id: string;
  contact_name: string | null;
  contact_phone: string | null;
  /** Group registry link + denormalized subject (group chats only). */
  group: string | null;
  group_subject: string | null;
  /** Needs Reply queue (P2.2): a question has waited past the threshold. */
  needs_reply: boolean;
  pending_query_since: string | null;
  labels: WdChatLabelChip[];
}

export interface WdGroup {
  name: string;
  wa_group_id: string;
  subject: string;
  description: string | null;
  member_count: number;
  invite_link: string | null;
  owned_by_us: boolean;
  number: string | null;
  number_name: string | null;
  chat: string | null;
  last_message_at: string | null;
  unread_count: number;
  msgs_today: number;
  needs_reply: boolean;
}

export interface WdGroupMember {
  name: string;
  /** Phone digits — masked for agents when the workspace masks numbers. */
  display: string;
  contact: string | null;
  contact_name: string | null;
  role: 'member' | 'admin';
  joined_at: string | null;
}

export interface WdGroupDetail {
  name: string;
  wa_group_id: string;
  subject: string;
  description: string | null;
  member_count: number;
  invite_link: string | null;
  owned_by_us: boolean;
  number: string | null;
  members: WdGroupMember[];
}

export type WdParticipantAction = 'add' | 'remove' | 'promote' | 'demote';

export interface ChatListParams {
  status?: string;
  number?: string;
  search?: string;
  /** 'me' | 'unassigned' | a member's user id */
  assignee?: string;
  /** a WD Label id — filters to chats carrying that label */
  label?: string;
  /** true → only the Needs Reply queue (unanswered group questions) */
  needs_reply?: boolean;
  limit?: number;
  offset?: number;
}

export interface WdLabel {
  name: string;
  title: string;
  color: string;
  description: string | null;
}

export interface WdCannedResponse {
  name: string;
  shortcode: string;
  content: string;
}

/** AI add-on state for the active workspace (Phase 4). Never carries rates/keys. */
export interface WdAiSettings {
  has_ai: boolean;
  kill_switch: boolean;
  byok_configured: boolean;
  byok_provider: string | null;
  persona_prompt: string | null;
  confidence_threshold: number | null;
}

/** Friendly AI usage meter — percent of allowance + credits in INR (never USD/tokens). */
export interface WdAiUsageMeter {
  has_ai: boolean;
  allowance_pct_used: number;
  credits_inr: number;
  paused: boolean;
  byok: boolean;
}

/** AI Auto-Agent config for the active workspace (Phase 4 feature 3). */
export interface WdAiAgentConfig {
  name: string;
  enabled: boolean;
  persona_prompt: string | null;
  confidence_threshold: number | null;
  handoff_team: string | null;
  after_hours_only: boolean;
  greeting: string | null;
  auto_ticket: boolean;
}

/** A knowledge-base document + its embedding status. */
export interface WdKnowledgeDoc {
  name: string;
  title: string;
  source_type: string;
  source_ref: string | null;
  embedding_status: string;
  chunk_count: number | null;
}

/** Auto-agent decision for a previewed question. */
export interface WdAgentAnswer {
  action: 'reply' | 'handoff';
  text: string | null;
  reason?: string;
  top_score?: number;
}

/** A per-workspace AI flag rule (Phase 4 feature 4). */
export interface WdAiFlagRule {
  name: string;
  flag_key: string;
  label: string | null;
  prompt: string;
  action: 'flag' | 'ticket';
  priority: string;
  enabled: boolean;
}

/** A public-API credential (P5). The secret is shown once at creation only. */
export interface WdApiKey {
  name: string;
  label: string;
  key_prefix: string;
  scopes: string[];
  enabled: boolean;
  rate_limit_per_min: number;
  last_used_at: string | null;
  creation: string;
}

/** Returned once at creation — full_key is never retrievable again. */
export interface WdApiKeyCreated {
  name: string;
  label: string;
  prefix: string;
  scopes: string[];
  rate_limit_per_min: number;
  full_key: string;
}

/** A per-vertical onboarding starter pack (P5). */
export interface WdVertical {
  key: string;
  label: string;
  description: string;
  labels: string[];
  canned: string[];
  automation: string[];
}

/** A 2FA enrollment challenge — secret + otpauth URI shown once (P5). */
export interface WdTwoFactorEnroll {
  secret: string;
  otpauth_uri: string;
}

/** One of the caller's active login sessions (P5). */
export interface WdSession {
  sid_tail: string;
  ip: string | null;
  last_active: string | null;
  status: string | null;
  current: boolean;
}

/** A DPDP/GDPR data-portability export request (P5). */
export interface WdDataExport {
  name: string;
  status: 'pending' | 'processing' | 'ready' | 'failed';
  file_url: string | null;
  record_counts: Record<string, number>;
  requested_by: string | null;
  creation: string;
}

/** Cross-workspace summary row for the platform admin console (P5). */
export interface WdAdminWorkspace {
  name: string;
  workspace_name: string;
  plan: string | null;
  owner_user: string | null;
  suspended: boolean;
  send_rate_clamp: number;
  members: number;
  messages_total: number;
  subscription_status: string | null;
  creation: string;
}

/** Platform-wide roll-up for the SaaS-provider overview (P5). */
export interface WdPlatformStats {
  totals: {
    workspaces: number;
    users: number;
    messages: number;
    contacts: number;
    numbers: number;
  };
  operational: { suspended: number };
  by_subscription_status: Record<string, number>;
  trial_vs_paid: { trial: number; paid: number; past_due: number };
  by_plan: Array<{ plan: string; count: number }>;
}

export interface WdAdminWorkspaceDetail {
  name: string;
  workspace_name: string;
  plan: string | null;
  owner_user: string | null;
  suspended: boolean;
  suspended_reason: string | null;
  send_rate_clamp: number;
  numbers: number;
  contacts: number;
  open_tickets: number;
  sent_today: number;
  kill_switch: boolean;
}

/** An outbound-webhook subscriber (P5). */
export interface WdWebhookEndpoint {
  name: string;
  label: string;
  url: string;
  signing_secret: string;
  events: string[];
  enabled: boolean;
  last_status: string | null;
  last_delivery_at: string | null;
}

/** One delivery attempt / dead-letter row (P5). */
export interface WdWebhookDelivery {
  name: string;
  endpoint: string;
  event_type: string;
  event_id: string;
  status: 'pending' | 'delivered' | 'failed' | 'dead';
  attempts: number;
  response_code: number | null;
  last_error: string | null;
  next_attempt_at: string | null;
  delivered_at: string | null;
  creation: string;
}

/** One day's business-hours window; a day with no entry is closed (P3.2). */
export interface WdBusinessHoursDay {
  open: string; // "HH:MM"
  close: string; // "HH:MM"
}

export interface WdBusinessHours {
  enabled: boolean;
  timezone: string;
  days: Partial<Record<'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun', WdBusinessHoursDay>>;
  holidays: string[]; // ISO dates "YYYY-MM-DD"
}

export interface WdWorkspaceSettings {
  workspace: string;
  workspace_name: string | null;
  /** the caller's role in the active workspace (null for system users) */
  role: 'Owner' | 'Admin' | 'Agent' | null;
  mask_numbers: boolean;
  /** minutes an unanswered group question waits before entering Needs Reply */
  needs_reply_minutes: number;
  /** team new chats auto-route to (P3.2), or null */
  default_routing_team: string | null;
  business_hours: WdBusinessHours;
  ooo_reply_enabled: boolean;
  ooo_reply_message: string;
}

export interface WdContact {
  name: string;
  phone: string;
  full_name: string | null;
  email: string | null;
  custom_attributes: Record<string, string>;
  opt_out: boolean;
}

export interface WdContactListRow {
  name: string;
  phone: string;
  full_name: string | null;
  email: string | null;
}

export interface WdContactChat {
  name: string;
  status: WdChat['status'];
  last_message_at: string | null;
  unread_count: number;
  number_name: string | null;
  number_phone: string | null;
}

export interface WdContactProfile extends WdContact {
  chats: WdContactChat[];
}

export interface WdContactImportStatus {
  import: string;
  file_name: string | null;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  total_rows: number;
  imported_rows: number;
  merged_rows: number;
  rejected_rows: number;
  error_csv: string | null;
  failure_reason: string | null;
}

export interface WdMember {
  user: string;
  role: 'Owner' | 'Admin' | 'Agent';
  full_name: string | null;
  /** live availability (P3.2) — powers the online dot in the assignee picker */
  online?: boolean;
  available?: boolean;
}

/** A member's live routing state (P3.2) — availability + current open-chat load. */
export interface WdAgentStatus extends WdMember {
  online: boolean;
  available: boolean;
  load: number;
}

export interface WdOnboardingStatus {
  has_workspace: boolean;
  workspace?: string;
  workspace_name?: string | null;
  role?: 'Owner' | 'Admin' | 'Agent' | null;
  connected_numbers?: number;
  total_numbers?: number;
  members?: number;
  pending_invites?: number;
}

export interface WdInvite {
  name: string;
  email: string;
  role: 'Admin' | 'Agent';
  status: 'pending' | 'accepted' | 'revoked' | 'expired';
  expires_at: string | null;
  /** Copyable accept link (managers only — the link is the credential). */
  invite_url: string;
}

export interface WdInviteAcceptResult {
  workspace: string;
  workspace_name: string | null;
  user: string;
  new_user: boolean;
}

export type WdSlaTarget = 'agent' | 'team' | 'owner' | 'slack' | 'webhook';

export interface WdSlaEscalationStep {
  after_mins: number;
  target: WdSlaTarget;
  url?: string;
}

export interface WdSlaPolicy {
  name: string;
  policy_name: string;
  enabled: boolean;
  first_response_mins: number;
  resolution_mins: number;
  escalation_chain: WdSlaEscalationStep[];
}

export interface WdSlaEvent {
  name: string;
  chat: string | null;
  policy: string | null;
  metric: 'first_response' | 'resolution' | null;
  outcome: 'breached' | 'escalated';
  target: string | null;
  detail: string | null;
  creation: string;
}

export type WdTemplateCategory = 'marketing' | 'utility' | 'authentication';
export type WdTemplateStatus = 'draft' | 'pending' | 'approved' | 'rejected';

export interface WdMessageTemplate {
  name: string;
  template_name: string;
  category: WdTemplateCategory;
  language: string;
  header_text: string | null;
  body_text: string;
  footer_text: string | null;
  buttons: unknown[];
  variable_count: number;
  status: WdTemplateStatus;
  meta_template_id: string | null;
  rejection_reason: string | null;
}

export type WdSegmentConditionType =
  | 'has_tag'
  | 'attribute'
  | 'opted_out'
  | 'has_email'
  | 'name_contains'
  | 'phone_prefix'
  | 'last_seen_days'
  | 'in_group';

export interface WdSegmentCondition {
  type: WdSegmentConditionType;
  key?: string;
  value?: string | number | boolean;
}

export interface WdSegment {
  name: string;
  segment_name: string;
  description: string | null;
  match_type: 'all' | 'any';
  filters: WdSegmentCondition[];
}

export interface WdSegmentPreview {
  count: number;
  sample: { name: string; phone: string | null; full_name: string | null }[];
}

export type WdScheduleTargetType = 'chat' | 'group' | 'broadcast';
export type WdScheduleType = 'once' | 'recurring';

export interface WdRecurrence {
  frequency: 'daily' | 'weekly';
  time: string; // "HH:MM"
  weekdays?: number[]; // 0 = Monday
}

export interface WdScheduledMessage {
  name: string;
  title: string;
  target_type: WdScheduleTargetType;
  target: string;
  number: string | null;
  body: string | null;
  schedule_type: WdScheduleType;
  scheduled_at: string | null;
  recurrence: WdRecurrence | Record<string, never>;
  timezone: string;
  next_run_at: string | null;
  last_run_at: string | null;
  run_count: number;
  status: 'scheduled' | 'sent' | 'cancelled' | 'failed';
  enabled: boolean;
}

export type WdBroadcastStatus = 'draft' | 'sending' | 'paused' | 'completed' | 'cancelled';
export type WdAudienceType = 'csv' | 'group_members' | 'all_contacts' | 'segment';

export interface WdBroadcast {
  name: string;
  broadcast_name: string;
  number: string;
  message_template: string;
  status: WdBroadcastStatus;
  audience_type: WdAudienceType | null;
  audience_ref: string | null;
  total_recipients: number;
  sent_count: number;
  failed_count: number;
  daily_cap: number;
  min_interval_sec: number;
  max_interval_sec: number;
  failure_pause_pct: number;
}

export interface WdBroadcastRecipient {
  name: string;
  phone: string | null;
  recipient_name: string | null;
  status: 'pending' | 'sent' | 'failed' | 'opted_out' | 'skipped';
  error: string | null;
  message_status: string | null;
}

export interface WdBroadcastReport {
  broadcast: WdBroadcast;
  counts: Record<'pending' | 'sent' | 'failed' | 'opted_out' | 'skipped', number>;
  recipients: WdBroadcastRecipient[];
}

export interface WdBroadcastPreview {
  phone: string | null;
  name: string | null;
  rendered: string;
}

export type WdRouting = 'manual' | 'round_robin' | 'load_based';

export interface WdTeam {
  name: string;
  team_name: string;
  /** routing mode (P3.2); defaults to 'manual' */
  routing: WdRouting;
  /** max open chats per agent via auto-routing; 0 = unlimited (P3.2) */
  capacity_per_agent: number;
  members: string[];
}

export interface ChatListResult {
  chats: WdChat[];
  total: number;
}

export interface WdMessage {
  name: string;
  direction: 'in' | 'out';
  message_type: string;
  body: string | null;
  status: 'queued' | 'sent' | 'delivered' | 'read' | 'failed' | null;
  sender_agent: string | null;
  sender_contact: string | null;
  /** Group sender identity (P2.2) — masked for agents when the workspace says so. */
  sender_jid: string | null;
  sender_name: string | null;
  sender_display: string | null;
  wa_message_id: string | null;
  quoted_message: string | null;
  quoted_body: string | null;
  /** A monitoring rule matched this message (P2.4). */
  flagged: boolean;
  flag_reason: string | null;
  /** Media pipeline (P4.5): this message has downloadable media in the store —
   * resolve a short-lived URL via getMediaUrl(name). The raw S3 key stays server-side. */
  has_media: boolean;
  media_mimetype: string | null;
  media_filename: string | null;
  media_size: number | null;
  media_duration: number | null;
  is_voice: boolean;
  /** Speech-to-text of a voice note (P4.5 Whisper), once transcribed. */
  transcript: string | null;
  creation: string;
}

export interface WdMediaUrl {
  message: string;
  message_type: string;
  /** Short-lived presigned URL, or null when media is undownloadable/unconfigured. */
  url: string | null;
  mimetype: string | null;
  filename: string | null;
  size: number | null;
  duration: number | null;
  is_voice: boolean;
  available: boolean;
}

export interface WdVolumePoint {
  date: string;
  count: number;
}

export interface WdContributor {
  display: string;
  messages: number;
}

export interface WdGroupAnalytics {
  days: number;
  total_messages: number;
  inbound_messages: number;
  outbound_messages: number;
  volume_trend: WdVolumePoint[];
  active_member_pct: number;
  top_contributors: WdContributor[];
  best_posting_hours: { hour: number; messages: number }[];
  avg_response_mins: number | null;
  answered_queries: number;
  unanswered_now: number;
}

export interface WdWorkspaceAnalytics {
  days: number;
  groups: number;
  messages: number;
  inbound_messages: number;
  unanswered_now: number;
}

export interface WdDashboard {
  days: number;
  live: { open: number; unassigned: number; needs_reply: number; sla_breached: number };
  conversations_trend: WdVolumePoint[];
  conversations_total: number;
  first_response_avg_mins: number | null;
  first_response_p90_mins: number | null;
  resolution_avg_mins: number | null;
  resolution_p90_mins: number | null;
  messages_per_agent: { agent: string; agent_name: string; messages: number }[];
  per_number_volume: { number: string; display_name: string | null; messages: number }[];
}

export type WdAutomationTrigger = 'message_received' | 'chat_created' | 'status_change';

export interface WdAutomationCondition {
  type:
    | 'is_group'
    | 'is_dm'
    | 'has_label'
    | 'number'
    | 'first_time_contact'
    | 'keyword'
    | 'in_segment';
  value?: string;
}

export interface WdAutomationAction {
  type:
    | 'assign_agent'
    | 'assign_team'
    | 'add_label'
    | 'create_ticket'
    | 'set_status'
    | 'snooze'
    | 'send_webhook'
    | 'notify_slack'
    | 'auto_reply';
  [param: string]: string | number | undefined;
}

export interface WdAutomationRule {
  name: string;
  rule_name: string;
  enabled: boolean;
  trigger_event: WdAutomationTrigger;
  conditions: WdAutomationCondition[];
  actions: WdAutomationAction[];
  run_count: number;
}

export interface WdAutomationLog {
  name: string;
  rule: string | null;
  rule_name: string;
  trigger_event: string;
  chat: string | null;
  outcome: 'fired' | 'skipped' | 'error';
  detail: string | null;
  creation: string;
}

export type WdTicketStatus = 'open' | 'in_progress' | 'resolved' | 'closed';
export type WdTicketPriority = 'low' | 'medium' | 'high' | 'urgent';

export interface WdTicket {
  name: string;
  title: string;
  status: WdTicketStatus;
  priority: WdTicketPriority;
  chat: string | null;
  source_message?: string | null;
  assigned_agent: string | null;
  team: string | null;
  resolution_note?: string | null;
  creation: string;
}

export interface TicketListParams {
  status?: WdTicketStatus;
  priority?: WdTicketPriority;
  /** 'me' | 'unassigned' | a member's user id */
  assignee?: string;
  limit?: number;
  offset?: number;
}

export type WdMonitoringRuleType = 'keyword' | 'link' | 'phone_number' | 'member_change';

export interface WdMonitoringRule {
  name: string;
  rule_name: string;
  enabled: boolean;
  rule_type: WdMonitoringRuleType;
  group: string | null;
  keywords: string | null;
  notify_agents: boolean;
  notify_slack_url: string | null;
  notify_webhook_url: string | null;
}

export interface WdAlert {
  name: string;
  rule_name: string | null;
  kind: WdMonitoringRuleType;
  group: string | null;
  group_subject: string | null;
  chat: string | null;
  message: string | null;
  summary: string;
  seen: boolean;
  creation: string;
}

export interface MessageListResult {
  messages: WdMessage[];
  has_more: boolean;
  next_before: string | null;
}

export interface ConnectCloudParams {
  phone: string;
  phone_number_id: string;
  waba_id: string;
  token: string;
  display_name?: string;
}

export class WaveDeskClient {
  private readonly baseUrl: string;
  private readonly fetchFn: typeof fetch;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
    // Bind: calling bare `fetch` through a property (`this.fetchFn(...)`) throws
    // "Illegal invocation" in browsers — fetch requires the global as receiver.
    this.fetchFn = options.fetchFn ?? fetch.bind(globalThis);
  }

  // --- auth (cookie session) ---
  async login(email: string, password: string): Promise<void> {
    await this.call('login', { usr: email, pwd: password });
  }

  async logout(): Promise<void> {
    await this.call('logout');
  }

  // --- numbers (Phase 1 feature 1) ---
  listNumbers(): Promise<WdNumber[]> {
    return this.call('wavedesk.api.numbers.list_numbers');
  }

  connectBaileys(displayName?: string): Promise<{ number: string; session_ref: string }> {
    return this.call('wavedesk.api.numbers.connect_baileys', {
      display_name: displayName ?? null,
    });
  }

  numberStatus(number: string): Promise<NumberStatus> {
    return this.call('wavedesk.api.numbers.number_status', { number });
  }

  disconnectNumber(number: string): Promise<{ status: string }> {
    return this.call('wavedesk.api.numbers.disconnect_number', { number });
  }

  reconnectNumber(number: string): Promise<{ status: string }> {
    return this.call('wavedesk.api.numbers.reconnect_number', { number });
  }

  deleteNumber(number: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.numbers.delete_number', { number });
  }

  // --- anti-ban (Phase 3 feature 6) ---
  numberHealth(): Promise<WdNumberHealth[]> {
    return this.call('wavedesk.api.antiban.number_health');
  }

  startWarmup(number: string, dailyTarget: number): Promise<{ number: string; warmup_started_on: string }> {
    return this.call('wavedesk.api.antiban.start_warmup', { number, daily_target: dailyTarget });
  }

  stopWarmup(number: string): Promise<{ number: string; warming: boolean }> {
    return this.call('wavedesk.api.antiban.stop_warmup', { number });
  }

  refreshHealth(number: string): Promise<{ score: number; risk: string }> {
    return this.call('wavedesk.api.antiban.refresh_health', { number });
  }

  connectCloudNumber(params: ConnectCloudParams): Promise<{ number: string; status: string }> {
    return this.call('wavedesk.api.numbers.connect_cloud_number', { ...params });
  }

  // --- chats (Phase 1 feature 2) ---
  listChats(params: ChatListParams = {}): Promise<ChatListResult> {
    return this.call('wavedesk.api.chats.list_chats', { ...params });
  }

  listMessages(chat: string, before?: string, limit?: number): Promise<MessageListResult> {
    return this.call('wavedesk.api.messages.list_messages', {
      chat,
      ...(before ? { before } : {}),
      ...(limit ? { limit } : {}),
    });
  }

  markChatRead(chat: string): Promise<{ chat: string; unread_count: number }> {
    return this.call('wavedesk.api.messages.mark_chat_read', { chat });
  }

  /** Media pipeline (P4.5): resolve a short-lived URL for a message's media. */
  getMediaUrl(message: string): Promise<WdMediaUrl> {
    return this.call('wavedesk.api.media.media_url', { message });
  }

  // --- contacts (Phase 1 feature 4) ---
  listContacts(params: { search?: string; limit?: number; offset?: number } = {}): Promise<{
    contacts: WdContactListRow[];
    total: number;
  }> {
    return this.call('wavedesk.api.contacts.list_contacts', { ...params });
  }

  getContact(contact: string): Promise<WdContactProfile> {
    return this.call('wavedesk.api.contacts.get_contact', { contact });
  }

  updateContact(
    contact: string,
    changes: {
      full_name?: string;
      email?: string;
      custom_attributes?: Record<string, string>;
    },
  ): Promise<WdContact> {
    return this.call('wavedesk.api.contacts.update_contact', { contact, ...changes });
  }

  importContacts(csvContent: string, fileName?: string): Promise<{ import: string; status: string }> {
    return this.call('wavedesk.api.contacts.import_contacts', {
      csv_content: csvContent,
      ...(fileName ? { file_name: fileName } : {}),
    });
  }

  importStatus(importName: string): Promise<WdContactImportStatus> {
    return this.call('wavedesk.api.contacts.import_status', { import_name: importName });
  }

  // --- assignment / status / presence (Phase 1 feature 3) ---
  listMembers(): Promise<WdMember[]> {
    return this.call('wavedesk.api.assign.list_members');
  }

  assignChat(
    chat: string,
    agent?: string | null,
    team?: string | null,
  ): Promise<{ chat: string; assigned_agent: string | null; assigned_team: string | null }> {
    return this.call('wavedesk.api.assign.assign_chat', {
      chat,
      agent: agent ?? null,
      team: team ?? null,
    });
  }

  setChatStatus(
    chat: string,
    status: WdChat['status'],
    snoozedUntil?: string,
  ): Promise<{ chat: string; status: WdChat['status']; snoozed_until: string | null }> {
    return this.call('wavedesk.api.assign.set_chat_status', {
      chat,
      status,
      ...(snoozedUntil ? { snoozed_until: snoozedUntil } : {}),
    });
  }

  presencePing(chat: string, state: 'viewing' | 'typing'): Promise<{ ok: boolean }> {
    return this.call('wavedesk.api.assign.presence_ping', { chat, state });
  }

  getLoggedUser(): Promise<string> {
    return this.call('frappe.auth.get_logged_user');
  }

  // --- teams (Phase 1 feature 3 — manual assignment; routing is Phase 3) ---
  listTeams(): Promise<WdTeam[]> {
    return this.call('wavedesk.api.teams.list_teams');
  }

  createTeam(
    teamName: string,
    options: { members?: string[]; routing?: WdRouting; capacityPerAgent?: number } = {},
  ): Promise<WdTeam> {
    return this.call('wavedesk.api.teams.create_team', {
      team_name: teamName,
      ...(options.members ? { members: options.members } : {}),
      ...(options.routing !== undefined ? { routing: options.routing } : {}),
      ...(options.capacityPerAgent !== undefined
        ? { capacity_per_agent: options.capacityPerAgent }
        : {}),
    });
  }

  updateTeam(
    team: string,
    changes: {
      teamName?: string;
      members?: string[];
      routing?: WdRouting;
      capacityPerAgent?: number;
    },
  ): Promise<WdTeam> {
    return this.call('wavedesk.api.teams.update_team', {
      team,
      ...(changes.teamName !== undefined ? { team_name: changes.teamName } : {}),
      ...(changes.members !== undefined ? { members: changes.members } : {}),
      ...(changes.routing !== undefined ? { routing: changes.routing } : {}),
      ...(changes.capacityPerAgent !== undefined
        ? { capacity_per_agent: changes.capacityPerAgent }
        : {}),
    });
  }

  deleteTeam(team: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.teams.delete_team', { team });
  }

  // --- auto-assignment & routing (Phase 3 feature 2) ---
  /** Keep the caller marked online for auto-routing (call on a timer). */
  routingHeartbeat(): Promise<{ online: boolean }> {
    return this.call('wavedesk.api.routing.heartbeat');
  }

  getAvailability(): Promise<{ available: boolean; online: boolean }> {
    return this.call('wavedesk.api.routing.get_availability');
  }

  setAvailability(available: boolean): Promise<{ available: boolean }> {
    return this.call('wavedesk.api.routing.set_availability', { available });
  }

  teamStatus(): Promise<WdAgentStatus[]> {
    return this.call('wavedesk.api.routing.team_status');
  }

  /** Manual 'route now' — auto-assign an agent to a team-owned chat. */
  routeChat(chat: string): Promise<{ chat: string; assigned_agent: string | null }> {
    return this.call('wavedesk.api.routing.route_chat', { chat });
  }

  // --- SLA engine (Phase 3 feature 3) ---
  listSlaPolicies(): Promise<WdSlaPolicy[]> {
    return this.call('wavedesk.api.sla.list_policies');
  }

  createSlaPolicy(policy: {
    policyName: string;
    firstResponseMins?: number;
    resolutionMins?: number;
    escalationChain?: WdSlaEscalationStep[];
  }): Promise<WdSlaPolicy> {
    return this.call('wavedesk.api.sla.create_policy', {
      policy_name: policy.policyName,
      first_response_mins: policy.firstResponseMins ?? 0,
      resolution_mins: policy.resolutionMins ?? 0,
      escalation_chain: policy.escalationChain ?? [],
    });
  }

  updateSlaPolicy(
    policy: string,
    changes: {
      policyName?: string;
      enabled?: boolean;
      firstResponseMins?: number;
      resolutionMins?: number;
      escalationChain?: WdSlaEscalationStep[];
    },
  ): Promise<WdSlaPolicy> {
    return this.call('wavedesk.api.sla.update_policy', {
      policy,
      ...(changes.policyName !== undefined ? { policy_name: changes.policyName } : {}),
      ...(changes.enabled !== undefined ? { enabled: changes.enabled } : {}),
      ...(changes.firstResponseMins !== undefined
        ? { first_response_mins: changes.firstResponseMins }
        : {}),
      ...(changes.resolutionMins !== undefined ? { resolution_mins: changes.resolutionMins } : {}),
      ...(changes.escalationChain !== undefined
        ? { escalation_chain: changes.escalationChain }
        : {}),
    });
  }

  deleteSlaPolicy(policy: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.sla.delete_policy', { policy });
  }

  attachSlaPolicy(
    chat: string,
    policy: string,
  ): Promise<{ chat: string; sla_policy: string; first_response_due: string | null; resolution_due: string | null }> {
    return this.call('wavedesk.api.sla.attach_policy', { chat, policy });
  }

  listSlaBreaches(limit?: number): Promise<WdSlaEvent[]> {
    return this.call('wavedesk.api.sla.list_breaches', { ...(limit ? { limit } : {}) });
  }

  // --- broadcasts (Phase 3 feature 4) ---
  listBroadcasts(): Promise<WdBroadcast[]> {
    return this.call('wavedesk.api.broadcasts.list_broadcasts');
  }

  createBroadcast(input: {
    broadcastName: string;
    number: string;
    messageTemplate: string;
    audienceType: WdAudienceType;
    audience?: { phone: string; name?: string }[];
    audienceRef?: string;
    dailyCap?: number;
    minIntervalSec?: number;
    maxIntervalSec?: number;
    failurePausePct?: number;
  }): Promise<WdBroadcast> {
    return this.call('wavedesk.api.broadcasts.create_broadcast', {
      broadcast_name: input.broadcastName,
      number: input.number,
      message_template: input.messageTemplate,
      audience_type: input.audienceType,
      ...(input.audience ? { audience: input.audience } : {}),
      ...(input.audienceRef ? { audience_ref: input.audienceRef } : {}),
      ...(input.dailyCap !== undefined ? { daily_cap: input.dailyCap } : {}),
      ...(input.minIntervalSec !== undefined ? { min_interval_sec: input.minIntervalSec } : {}),
      ...(input.maxIntervalSec !== undefined ? { max_interval_sec: input.maxIntervalSec } : {}),
      ...(input.failurePausePct !== undefined ? { failure_pause_pct: input.failurePausePct } : {}),
    });
  }

  startBroadcast(broadcast: string): Promise<WdBroadcast> {
    return this.call('wavedesk.api.broadcasts.start_broadcast', { broadcast });
  }

  pauseBroadcast(broadcast: string): Promise<WdBroadcast> {
    return this.call('wavedesk.api.broadcasts.pause_broadcast', { broadcast });
  }

  resumeBroadcast(broadcast: string): Promise<WdBroadcast> {
    return this.call('wavedesk.api.broadcasts.resume_broadcast', { broadcast });
  }

  cancelBroadcast(broadcast: string): Promise<WdBroadcast> {
    return this.call('wavedesk.api.broadcasts.cancel_broadcast', { broadcast });
  }

  retryBroadcast(broadcast: string): Promise<{ retried: number }> {
    return this.call('wavedesk.api.broadcasts.retry_broadcast', { broadcast });
  }

  previewBroadcast(broadcast: string, limit?: number): Promise<WdBroadcastPreview[]> {
    return this.call('wavedesk.api.broadcasts.preview_broadcast', {
      broadcast,
      ...(limit ? { limit } : {}),
    });
  }

  broadcastReport(broadcast: string): Promise<WdBroadcastReport> {
    return this.call('wavedesk.api.broadcasts.delivery_report', { broadcast });
  }

  deleteBroadcast(broadcast: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.broadcasts.delete_broadcast', { broadcast });
  }

  // --- scheduled messages (Phase 3 feature 5) ---
  listSchedules(): Promise<WdScheduledMessage[]> {
    return this.call('wavedesk.api.schedules.list_schedules');
  }

  createSchedule(input: {
    title: string;
    targetType: WdScheduleTargetType;
    target: string;
    scheduleType: WdScheduleType;
    body?: string;
    number?: string;
    scheduledAt?: string;
    recurrence?: WdRecurrence;
    timezone?: string;
  }): Promise<WdScheduledMessage> {
    return this.call('wavedesk.api.schedules.create_schedule', {
      title: input.title,
      target_type: input.targetType,
      target: input.target,
      schedule_type: input.scheduleType,
      ...(input.body !== undefined ? { body: input.body } : {}),
      ...(input.number ? { number: input.number } : {}),
      ...(input.scheduledAt ? { scheduled_at: input.scheduledAt } : {}),
      ...(input.recurrence ? { recurrence: input.recurrence } : {}),
      ...(input.timezone ? { timezone: input.timezone } : {}),
    });
  }

  updateSchedule(
    schedule: string,
    changes: {
      title?: string;
      body?: string;
      scheduledAt?: string;
      recurrence?: WdRecurrence;
      timezone?: string;
      enabled?: boolean;
    },
  ): Promise<WdScheduledMessage> {
    return this.call('wavedesk.api.schedules.update_schedule', {
      schedule,
      ...(changes.title !== undefined ? { title: changes.title } : {}),
      ...(changes.body !== undefined ? { body: changes.body } : {}),
      ...(changes.scheduledAt !== undefined ? { scheduled_at: changes.scheduledAt } : {}),
      ...(changes.recurrence !== undefined ? { recurrence: changes.recurrence } : {}),
      ...(changes.timezone !== undefined ? { timezone: changes.timezone } : {}),
      ...(changes.enabled !== undefined ? { enabled: changes.enabled } : {}),
    });
  }

  cancelSchedule(schedule: string): Promise<WdScheduledMessage> {
    return this.call('wavedesk.api.schedules.cancel_schedule', { schedule });
  }

  runScheduleNow(schedule: string): Promise<WdScheduledMessage> {
    return this.call('wavedesk.api.schedules.run_schedule_now', { schedule });
  }

  deleteSchedule(schedule: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.schedules.delete_schedule', { schedule });
  }

  // --- segments (Phase 3 feature 7) ---
  listSegments(): Promise<WdSegment[]> {
    return this.call('wavedesk.api.segments.list_segments');
  }

  createSegment(input: {
    segmentName: string;
    matchType?: 'all' | 'any';
    filters?: WdSegmentCondition[];
    description?: string;
  }): Promise<WdSegment> {
    return this.call('wavedesk.api.segments.create_segment', {
      segment_name: input.segmentName,
      match_type: input.matchType ?? 'all',
      filters: input.filters ?? [],
      ...(input.description !== undefined ? { description: input.description } : {}),
    });
  }

  updateSegment(
    segment: string,
    changes: {
      segmentName?: string;
      matchType?: 'all' | 'any';
      filters?: WdSegmentCondition[];
      description?: string;
    },
  ): Promise<WdSegment> {
    return this.call('wavedesk.api.segments.update_segment', {
      segment,
      ...(changes.segmentName !== undefined ? { segment_name: changes.segmentName } : {}),
      ...(changes.matchType !== undefined ? { match_type: changes.matchType } : {}),
      ...(changes.filters !== undefined ? { filters: changes.filters } : {}),
      ...(changes.description !== undefined ? { description: changes.description } : {}),
    });
  }

  deleteSegment(segment: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.segments.delete_segment', { segment });
  }

  previewSegment(segment: string, limit?: number): Promise<WdSegmentPreview> {
    return this.call('wavedesk.api.segments.preview_segment', {
      segment,
      ...(limit ? { limit } : {}),
    });
  }

  // --- message templates (Phase 3 feature 8) ---
  listTemplates(): Promise<WdMessageTemplate[]> {
    return this.call('wavedesk.api.templates.list_templates');
  }

  createTemplate(input: {
    templateName: string;
    bodyText: string;
    category?: WdTemplateCategory;
    language?: string;
    headerText?: string;
    footerText?: string;
  }): Promise<WdMessageTemplate> {
    return this.call('wavedesk.api.templates.create_template', {
      template_name: input.templateName,
      body_text: input.bodyText,
      category: input.category ?? 'utility',
      language: input.language ?? 'en',
      ...(input.headerText !== undefined ? { header_text: input.headerText } : {}),
      ...(input.footerText !== undefined ? { footer_text: input.footerText } : {}),
    });
  }

  updateTemplate(
    template: string,
    changes: {
      templateName?: string;
      bodyText?: string;
      category?: WdTemplateCategory;
      language?: string;
      headerText?: string;
      footerText?: string;
    },
  ): Promise<WdMessageTemplate> {
    return this.call('wavedesk.api.templates.update_template', {
      template,
      ...(changes.templateName !== undefined ? { template_name: changes.templateName } : {}),
      ...(changes.bodyText !== undefined ? { body_text: changes.bodyText } : {}),
      ...(changes.category !== undefined ? { category: changes.category } : {}),
      ...(changes.language !== undefined ? { language: changes.language } : {}),
      ...(changes.headerText !== undefined ? { header_text: changes.headerText } : {}),
      ...(changes.footerText !== undefined ? { footer_text: changes.footerText } : {}),
    });
  }

  submitTemplate(template: string): Promise<{ status: string; live: boolean; note?: string }> {
    return this.call('wavedesk.api.templates.submit_template', { template });
  }

  deleteTemplate(template: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.templates.delete_template', { template });
  }

  previewTemplate(template: string, values?: string[]): Promise<{ rendered: string }> {
    return this.call('wavedesk.api.templates.preview_template', {
      template,
      ...(values ? { values } : {}),
    });
  }

  // --- groups (Phase 2 feature 1 — registry; bulk actions land in P2.3) ---
  listGroups(params: { search?: string; limit?: number; offset?: number } = {}): Promise<{
    groups: WdGroup[];
    total: number;
  }> {
    return this.call('wavedesk.api.groups.list_groups', { ...params });
  }

  getGroup(group: string): Promise<WdGroupDetail> {
    return this.call('wavedesk.api.groups.get_group', { group });
  }

  updateGroup(
    group: string,
    changes: { subject?: string; description?: string },
  ): Promise<{ group: string }> {
    return this.call('wavedesk.api.groups.update_group', { group, ...changes });
  }

  groupParticipants(
    group: string,
    participants: string[],
    action: WdParticipantAction,
  ): Promise<{ group: string; action: WdParticipantAction; count: number }> {
    return this.call('wavedesk.api.groups.group_participants', { group, participants, action });
  }

  revokeGroupInvite(group: string): Promise<{ group: string; invite_link: string | null }> {
    return this.call('wavedesk.api.groups.revoke_group_invite', { group });
  }

  /** Bulk message N groups — queued + jittered server-side. */
  sendToGroups(groups: string[], body: string): Promise<{ queued_groups: number }> {
    return this.call('wavedesk.api.groups.send_to_groups', { groups, body });
  }

  // --- automation (Phase 3 feature 1) ---
  listAutomationRules(): Promise<WdAutomationRule[]> {
    return this.call('wavedesk.api.automation.list_rules');
  }

  createAutomationRule(rule: {
    rule_name: string;
    trigger_event: WdAutomationTrigger;
    conditions?: WdAutomationCondition[];
    actions?: WdAutomationAction[];
  }): Promise<WdAutomationRule> {
    return this.call('wavedesk.api.automation.create_rule', { ...rule });
  }

  updateAutomationRule(
    rule: string,
    changes: {
      rule_name?: string;
      trigger_event?: WdAutomationTrigger;
      enabled?: boolean;
      conditions?: WdAutomationCondition[];
      actions?: WdAutomationAction[];
    },
  ): Promise<WdAutomationRule> {
    return this.call('wavedesk.api.automation.update_rule', { rule, ...changes });
  }

  deleteAutomationRule(rule: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.automation.delete_rule', { rule });
  }

  listAutomationLogs(rule?: string): Promise<WdAutomationLog[]> {
    return this.call('wavedesk.api.automation.list_logs', { ...(rule ? { rule } : {}) });
  }

  // --- tickets (Phase 2 feature 7) ---
  createTicket(params: {
    title?: string;
    chat?: string;
    source_message?: string;
    priority?: WdTicketPriority;
  }): Promise<WdTicket> {
    return this.call('wavedesk.api.tickets.create_ticket', { ...params });
  }

  listTickets(params: TicketListParams = {}): Promise<{ tickets: WdTicket[]; total: number }> {
    return this.call('wavedesk.api.tickets.list_tickets', { ...params });
  }

  getTicket(ticket: string): Promise<WdTicket> {
    return this.call('wavedesk.api.tickets.get_ticket', { ticket });
  }

  updateTicket(
    ticket: string,
    changes: {
      title?: string;
      status?: WdTicketStatus;
      priority?: WdTicketPriority;
      assigned_agent?: string;
      resolution_note?: string;
      _unset_agent?: boolean;
    },
  ): Promise<WdTicket> {
    return this.call('wavedesk.api.tickets.update_ticket', { ticket, ...changes });
  }

  deleteTicket(ticket: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.tickets.delete_ticket', { ticket });
  }

  // --- group analytics (Phase 2 feature 5) ---
  groupAnalytics(group: string, days?: number): Promise<WdGroupAnalytics> {
    return this.call('wavedesk.api.analytics.group_analytics', {
      group,
      ...(days ? { days } : {}),
    });
  }

  workspaceAnalytics(days?: number): Promise<WdWorkspaceAnalytics> {
    return this.call('wavedesk.api.analytics.workspace_analytics', {
      ...(days ? { days } : {}),
    });
  }

  workspaceDashboard(days?: number): Promise<WdDashboard> {
    return this.call('wavedesk.api.analytics.workspace_dashboard', {
      ...(days ? { days } : {}),
    });
  }

  /** URL for the CSV export — open it directly to trigger a browser download. */
  dashboardCsvUrl(days: number): string {
    return `${this.baseUrl}/api/method/wavedesk.api.analytics.export_dashboard_csv?days=${String(days)}`;
  }

  // --- onboarding + invites (Phase 1 feature 8) ---
  createWorkspace(workspaceName: string): Promise<{ workspace: string; workspace_name: string }> {
    return this.call('wavedesk.api.onboarding.create_workspace', {
      workspace_name: workspaceName,
    });
  }

  onboardingStatus(): Promise<WdOnboardingStatus> {
    return this.call('wavedesk.api.onboarding.onboarding_status');
  }

  inviteMember(email: string, role: WdInvite['role'] = 'Agent'): Promise<WdInvite> {
    return this.call('wavedesk.api.invites.invite_member', { email, role });
  }

  listInvites(): Promise<WdInvite[]> {
    return this.call('wavedesk.api.invites.list_invites');
  }

  revokeInvite(invite: string): Promise<{ invite: string; status: string }> {
    return this.call('wavedesk.api.invites.revoke_invite', { invite });
  }

  acceptInvite(
    token: string,
    details: { full_name?: string; password?: string } = {},
  ): Promise<WdInviteAcceptResult> {
    return this.call('wavedesk.api.invites.accept_invite', { token, ...details });
  }

  // --- labels (Phase 1 feature 5) ---
  listLabels(): Promise<WdLabel[]> {
    return this.call('wavedesk.api.labels.list_labels');
  }

  createLabel(title: string, color?: string, description?: string): Promise<WdLabel> {
    return this.call('wavedesk.api.labels.create_label', {
      title,
      ...(color ? { color } : {}),
      ...(description ? { description } : {}),
    });
  }

  updateLabel(
    label: string,
    changes: { title?: string; color?: string; description?: string },
  ): Promise<WdLabel> {
    return this.call('wavedesk.api.labels.update_label', { label, ...changes });
  }

  deleteLabel(label: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.labels.delete_label', { label });
  }

  /** Replaces the chat's whole label list (the picker always sends the full selection). */
  setChatLabels(
    chat: string,
    labels: string[],
  ): Promise<{ chat: string; labels: WdChatLabelChip[] }> {
    return this.call('wavedesk.api.labels.set_chat_labels', { chat, labels });
  }

  // --- canned responses (Phase 1 feature 5) ---
  listCanned(): Promise<WdCannedResponse[]> {
    return this.call('wavedesk.api.canned.list_canned');
  }

  searchCanned(term: string): Promise<WdCannedResponse[]> {
    return this.call('wavedesk.api.canned.search_canned', { term });
  }

  createCanned(shortcode: string, content: string): Promise<WdCannedResponse> {
    return this.call('wavedesk.api.canned.create_canned', { shortcode, content });
  }

  updateCanned(
    canned: string,
    changes: { shortcode?: string; content?: string },
  ): Promise<WdCannedResponse> {
    return this.call('wavedesk.api.canned.update_canned', { canned, ...changes });
  }

  deleteCanned(canned: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.canned.delete_canned', { canned });
  }

  // --- AI settings + usage (Phase 4 feature 1) ---
  aiSettings(): Promise<WdAiSettings> {
    return this.call('wavedesk.api.ai.ai_settings');
  }

  aiUsageMeter(): Promise<WdAiUsageMeter> {
    return this.call('wavedesk.api.ai.usage_meter');
  }

  setByok(
    provider: string,
    apiKey: string,
  ): Promise<{ byok_configured: boolean; byok_provider: string }> {
    return this.call('wavedesk.api.ai.set_byok', { provider, api_key: apiKey });
  }

  revokeByok(): Promise<{ byok_configured: boolean }> {
    return this.call('wavedesk.api.ai.revoke_byok');
  }

  setAiKillSwitch(enabled: boolean): Promise<{ kill_switch: boolean }> {
    return this.call('wavedesk.api.ai.set_kill_switch', { enabled: enabled ? 1 : 0 });
  }

  // --- Agent Copilot (Phase 4 feature 2) ---
  copilotSuggestReply(chat: string): Promise<{ text: string }> {
    return this.call('wavedesk.api.copilot.suggest_reply', { chat });
  }

  copilotRewrite(text: string, mode: 'polish' | 'expand' | 'shorten'): Promise<{ text: string }> {
    return this.call('wavedesk.api.copilot.rewrite', { text, mode });
  }

  copilotTranslate(
    text: string,
    targetLang: string,
    sourceLang?: string,
  ): Promise<{ text: string }> {
    return this.call('wavedesk.api.copilot.translate', {
      text,
      target_lang: targetLang,
      source_lang: sourceLang,
    });
  }

  copilotSummarize(chat: string, since?: string): Promise<{ text: string }> {
    return this.call('wavedesk.api.copilot.summarize', { chat, since });
  }

  // --- AI Auto-Agent (Phase 4 feature 3) ---
  getAgentConfig(): Promise<WdAiAgentConfig> {
    return this.call('wavedesk.api.agent.get_agent_config');
  }

  updateAgentConfig(changes: {
    enabled?: boolean;
    persona_prompt?: string;
    confidence_threshold?: number;
    handoff_team?: string;
    after_hours_only?: boolean;
    greeting?: string;
    auto_ticket?: boolean;
  }): Promise<WdAiAgentConfig> {
    const payload: Record<string, unknown> = { ...changes };
    if (changes.enabled !== undefined) payload.enabled = changes.enabled ? 1 : 0;
    if (changes.after_hours_only !== undefined)
      payload.after_hours_only = changes.after_hours_only ? 1 : 0;
    if (changes.auto_ticket !== undefined)
      payload.auto_ticket = changes.auto_ticket ? 1 : 0;
    return this.call('wavedesk.api.agent.update_agent_config', payload);
  }

  listKnowledge(): Promise<WdKnowledgeDoc[]> {
    return this.call('wavedesk.api.agent.list_knowledge');
  }

  createKnowledge(
    title: string,
    content: string,
    sourceType = 'text',
    sourceRef?: string,
  ): Promise<{ name: string; embedding_status: string }> {
    return this.call('wavedesk.api.agent.create_knowledge', {
      title,
      content,
      source_type: sourceType,
      source_ref: sourceRef,
    });
  }

  deleteKnowledge(doc: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.agent.delete_knowledge', { doc });
  }

  previewAnswer(question: string): Promise<WdAgentAnswer> {
    return this.call('wavedesk.api.agent.preview_answer', { question });
  }

  // --- AI message flagging (Phase 4 feature 4) ---
  listFlagRules(): Promise<WdAiFlagRule[]> {
    return this.call('wavedesk.api.flagging.list_rules');
  }

  createFlagRule(
    flagKey: string,
    prompt: string,
    opts?: { label?: string; action?: 'flag' | 'ticket'; priority?: string },
  ): Promise<{ name: string; flag_key: string }> {
    return this.call('wavedesk.api.flagging.create_rule', {
      flag_key: flagKey,
      prompt,
      label: opts?.label,
      action: opts?.action ?? 'flag',
      priority: opts?.priority ?? 'medium',
    });
  }

  updateFlagRule(
    rule: string,
    changes: { prompt?: string; label?: string; action?: 'flag' | 'ticket'; priority?: string; enabled?: boolean },
  ): Promise<{ name: string; enabled: boolean }> {
    const payload: Record<string, unknown> = { rule, ...changes };
    if (changes.enabled !== undefined) payload.enabled = changes.enabled ? 1 : 0;
    return this.call('wavedesk.api.flagging.update_rule', payload);
  }

  deleteFlagRule(rule: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.flagging.delete_rule', { rule });
  }

  // --- public API keys (Phase 5) ---
  apiKeyScopes(): Promise<string[]> {
    return this.call<{ scopes: string[] }>('wavedesk.api.publicapi.available_scopes').then(
      (r) => r.scopes,
    );
  }

  listApiKeys(): Promise<WdApiKey[]> {
    return this.call<{ keys: WdApiKey[] }>('wavedesk.api.publicapi.list_api_keys').then(
      (r) => r.keys,
    );
  }

  createApiKey(
    label: string,
    scopes: string[],
    rateLimitPerMin?: number,
  ): Promise<WdApiKeyCreated> {
    return this.call('wavedesk.api.publicapi.create_api_key', {
      label,
      scopes,
      rate_limit_per_min: rateLimitPerMin,
    });
  }

  revokeApiKey(name: string): Promise<{ name: string; enabled: boolean }> {
    return this.call('wavedesk.api.publicapi.revoke_api_key', { name });
  }

  // --- outbound webhooks (Phase 5) ---
  webhookEventCatalog(): Promise<string[]> {
    return this.call<{ events: string[] }>('wavedesk.api.webhooks.event_catalog').then(
      (r) => r.events,
    );
  }

  listWebhookEndpoints(): Promise<WdWebhookEndpoint[]> {
    return this.call<{ endpoints: WdWebhookEndpoint[] }>(
      'wavedesk.api.webhooks.list_endpoints',
    ).then((r) => r.endpoints);
  }

  createWebhookEndpoint(
    label: string,
    url: string,
    events: string[],
  ): Promise<WdWebhookEndpoint> {
    return this.call('wavedesk.api.webhooks.create_endpoint', { label, url, events });
  }

  updateWebhookEndpoint(
    name: string,
    changes: { url?: string; events?: string[]; enabled?: boolean },
  ): Promise<WdWebhookEndpoint> {
    const payload: Record<string, unknown> = { name, ...changes };
    if (changes.enabled !== undefined) payload.enabled = changes.enabled ? 1 : 0;
    return this.call('wavedesk.api.webhooks.update_endpoint', payload);
  }

  deleteWebhookEndpoint(name: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.webhooks.delete_endpoint', { name });
  }

  listWebhookDeliveries(
    opts: { endpoint?: string; status?: string; limit?: number } = {},
  ): Promise<WdWebhookDelivery[]> {
    return this.call<{ deliveries: WdWebhookDelivery[] }>(
      'wavedesk.api.webhooks.list_deliveries',
      opts as Record<string, unknown>,
    ).then((r) => r.deliveries);
  }

  redeliverWebhook(delivery: string): Promise<{ delivery: string; status: string }> {
    return this.call('wavedesk.api.webhooks.redeliver', { delivery });
  }

  // --- platform admin / superadmin (Phase 5) ---
  adminWhoami(): Promise<boolean> {
    return this.call<{ is_platform_admin: boolean }>('wavedesk.api.admin.whoami').then(
      (r) => r.is_platform_admin,
    );
  }

  adminPlatformStats(): Promise<WdPlatformStats> {
    return this.call<WdPlatformStats>('wavedesk.api.admin.platform_stats');
  }

  adminListWorkspaces(search?: string): Promise<WdAdminWorkspace[]> {
    return this.call<{ workspaces: WdAdminWorkspace[] }>('wavedesk.api.admin.list_workspaces', {
      ...(search ? { search } : {}),
    }).then((r) => r.workspaces);
  }

  adminWorkspaceDetail(workspace: string): Promise<WdAdminWorkspaceDetail> {
    return this.call('wavedesk.api.admin.workspace_detail', { workspace });
  }

  adminSuspendWorkspace(workspace: string, reason: string): Promise<{ suspended: boolean }> {
    return this.call('wavedesk.api.admin.suspend_workspace', { workspace, reason });
  }

  adminUnsuspendWorkspace(workspace: string): Promise<{ suspended: boolean }> {
    return this.call('wavedesk.api.admin.unsuspend_workspace', { workspace });
  }

  adminSetSendRateClamp(workspace: string, clamp: number): Promise<{ send_rate_clamp: number }> {
    return this.call('wavedesk.api.admin.set_send_rate_clamp', { workspace, clamp });
  }

  adminSetKillSwitch(workspace: string, enabled: boolean): Promise<{ kill_switch: boolean }> {
    return this.call('wavedesk.api.admin.set_ai_kill_switch', {
      workspace,
      enabled: enabled ? 1 : 0,
    });
  }

  adminImpersonate(user: string): Promise<{ impersonating: string }> {
    return this.call('wavedesk.api.admin.impersonate', { user });
  }

  // --- DPDP/GDPR data controls (Phase 5) ---
  getRetention(): Promise<number> {
    return this.call<{ retention_days: number }>('wavedesk.api.privacy.get_retention').then(
      (r) => r.retention_days,
    );
  }

  setRetention(days: number): Promise<{ retention_days: number }> {
    return this.call('wavedesk.api.privacy.set_retention', { days });
  }

  requestDataExport(): Promise<{ export: string }> {
    return this.call('wavedesk.api.privacy.request_export');
  }

  listDataExports(): Promise<WdDataExport[]> {
    return this.call<{ exports: WdDataExport[] }>('wavedesk.api.privacy.list_exports').then(
      (r) => r.exports,
    );
  }

  eraseContact(contact: string): Promise<{ contact: string; erased: boolean }> {
    return this.call('wavedesk.api.privacy.erase_contact', { contact });
  }

  // --- account security: 2FA + sessions (Phase 5) ---
  twofaStatus(): Promise<boolean> {
    return this.call<{ enabled: boolean }>('wavedesk.api.security.twofa_status').then(
      (r) => r.enabled,
    );
  }

  twofaBeginEnroll(): Promise<WdTwoFactorEnroll> {
    return this.call('wavedesk.api.security.twofa_begin_enroll');
  }

  twofaConfirm(code: string): Promise<{ enabled: boolean; recovery_codes: string[] }> {
    return this.call('wavedesk.api.security.twofa_confirm', { code });
  }

  twofaDisable(code: string): Promise<{ enabled: boolean }> {
    return this.call('wavedesk.api.security.twofa_disable', { code });
  }

  twofaVerify(code: string): Promise<{ verified: boolean }> {
    return this.call('wavedesk.api.security.twofa_verify', { code });
  }

  listSessions(): Promise<WdSession[]> {
    return this.call<{ sessions: WdSession[] }>('wavedesk.api.security.list_sessions').then(
      (r) => r.sessions,
    );
  }

  revokeSession(sidTail: string): Promise<{ revoked: string }> {
    return this.call('wavedesk.api.security.revoke_session', { sid_tail: sidTail });
  }

  revokeOtherSessions(): Promise<{ revoked: number }> {
    return this.call('wavedesk.api.security.revoke_other_sessions');
  }

  // --- IP allowlist (Phase 5, Business plan) ---
  getIpAllowlist(): Promise<string[]> {
    return this.call<{ ip_allowlist: string[] }>('wavedesk.api.access.get_ip_allowlist').then(
      (r) => r.ip_allowlist,
    );
  }

  setIpAllowlist(entries: string[]): Promise<{ ip_allowlist: string[] }> {
    return this.call('wavedesk.api.access.set_ip_allowlist', { entries });
  }

  // --- vertical starter packs (Phase 5) ---
  listVerticals(): Promise<WdVertical[]> {
    return this.call<{ verticals: WdVertical[] }>('wavedesk.api.verticals.list_verticals').then(
      (r) => r.verticals,
    );
  }

  applyVertical(
    vertical: string,
  ): Promise<{ vertical: string; added: { labels: number; canned: number; automation: number } }> {
    return this.call('wavedesk.api.verticals.apply_vertical', { vertical });
  }

  // --- monitoring (Phase 2 feature 4) ---
  listMonitoringRules(): Promise<WdMonitoringRule[]> {
    return this.call('wavedesk.api.monitoring.list_rules');
  }

  createMonitoringRule(rule: {
    rule_name: string;
    rule_type: WdMonitoringRuleType;
    keywords?: string;
    group?: string;
    notify_agents?: boolean;
    notify_slack_url?: string;
    notify_webhook_url?: string;
  }): Promise<WdMonitoringRule> {
    return this.call('wavedesk.api.monitoring.create_rule', { ...rule });
  }

  updateMonitoringRule(
    rule: string,
    changes: Partial<Omit<WdMonitoringRule, 'name'>>,
  ): Promise<WdMonitoringRule> {
    return this.call('wavedesk.api.monitoring.update_rule', { rule, ...changes });
  }

  deleteMonitoringRule(rule: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.monitoring.delete_rule', { rule });
  }

  listAlerts(): Promise<{ alerts: WdAlert[]; unseen: number }> {
    return this.call('wavedesk.api.monitoring.list_alerts');
  }

  markAlertsSeen(): Promise<{ unseen: number }> {
    return this.call('wavedesk.api.monitoring.mark_alerts_seen');
  }

  // --- workspace settings (Phase 1 feature 6 — number masking) ---
  getWorkspaceSettings(): Promise<WdWorkspaceSettings> {
    return this.call('wavedesk.api.workspace.get_workspace_settings');
  }

  updateWorkspaceSettings(changes: {
    mask_numbers?: boolean;
    needs_reply_minutes?: number;
    default_routing_team?: string | null;
    business_hours?: WdBusinessHours;
    ooo_reply_enabled?: boolean;
    ooo_reply_message?: string;
  }): Promise<WdWorkspaceSettings> {
    return this.call('wavedesk.api.workspace.update_workspace_settings', {
      ...changes,
      ...(changes.business_hours !== undefined
        ? { business_hours: JSON.stringify(changes.business_hours) }
        : {}),
    });
  }

  // --- sending (Phase 1 feature 7 — queued pipeline) ---
  sendMessage(chat: string, body: string): Promise<{ name: string; status: string }> {
    return this.call('wavedesk.api.send.send_message', { chat, body });
  }

  retryMessage(message: string): Promise<{ name: string; status: string }> {
    return this.call('wavedesk.api.send.retry_message', { message });
  }

  /** Low-level call to a whitelisted Frappe method (`/api/method/<path>`). */
  async call<T>(method: string, params?: Record<string, unknown>): Promise<T> {
    const res = await this.fetchFn(`${this.baseUrl}/api/method/${method}`, {
      method: params ? 'POST' : 'GET',
      headers: {
        Accept: 'application/json',
        ...(params ? { 'Content-Type': 'application/json' } : {}),
      },
      credentials: 'include',
      ...(params ? { body: JSON.stringify(params) } : {}),
    });
    if (!res.ok) {
      throw new ApiError(res.status, await res.text());
    }
    const data = (await res.json()) as FrappeMethodResponse<T>;
    return data.message;
  }
}
