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

export interface WdWorkspaceSettings {
  workspace: string;
  workspace_name: string | null;
  /** the caller's role in the active workspace (null for system users) */
  role: 'Owner' | 'Admin' | 'Agent' | null;
  mask_numbers: boolean;
  /** minutes an unanswered group question waits before entering Needs Reply */
  needs_reply_minutes: number;
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

export interface WdTeam {
  name: string;
  team_name: string;
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
  creation: string;
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
  live: { open: number; unassigned: number; needs_reply: number };
  conversations_trend: WdVolumePoint[];
  conversations_total: number;
  first_response_avg_mins: number | null;
  first_response_p90_mins: number | null;
  resolution_avg_mins: number | null;
  resolution_p90_mins: number | null;
  messages_per_agent: { agent: string; agent_name: string; messages: number }[];
  per_number_volume: { number: string; display_name: string | null; messages: number }[];
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

  createTeam(teamName: string, members?: string[]): Promise<WdTeam> {
    return this.call('wavedesk.api.teams.create_team', {
      team_name: teamName,
      ...(members ? { members } : {}),
    });
  }

  updateTeam(team: string, changes: { teamName?: string; members?: string[] }): Promise<WdTeam> {
    return this.call('wavedesk.api.teams.update_team', {
      team,
      ...(changes.teamName !== undefined ? { team_name: changes.teamName } : {}),
      ...(changes.members !== undefined ? { members: changes.members } : {}),
    });
  }

  deleteTeam(team: string): Promise<{ deleted: string }> {
    return this.call('wavedesk.api.teams.delete_team', { team });
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
  }): Promise<WdWorkspaceSettings> {
    return this.call('wavedesk.api.workspace.update_workspace_settings', { ...changes });
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
