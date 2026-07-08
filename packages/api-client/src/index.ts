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

export interface WdChat {
  name: string;
  chat_type: 'dm' | 'group';
  status: 'open' | 'pending' | 'resolved' | 'snoozed';
  number: string | null;
  assigned_agent: string | null;
  assigned_team: string | null;
  snoozed_until: string | null;
  last_message_at: string | null;
  unread_count: number;
  wa_chat_id: string;
  contact_name: string | null;
  contact_phone: string | null;
}

export interface ChatListParams {
  status?: string;
  number?: string;
  search?: string;
  /** 'me' | 'unassigned' | a member's user id */
  assignee?: string;
  limit?: number;
  offset?: number;
}

export interface WdMember {
  user: string;
  role: 'Owner' | 'Admin' | 'Agent';
  full_name: string | null;
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
  wa_message_id: string | null;
  quoted_message: string | null;
  quoted_body: string | null;
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
