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
  limit?: number;
  offset?: number;
}

export interface ChatListResult {
  chats: WdChat[];
  total: number;
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
