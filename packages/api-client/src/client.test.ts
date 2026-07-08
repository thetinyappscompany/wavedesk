import { describe, expect, it, vi } from 'vitest';
import { ApiError, WaveDeskClient } from './index.js';

function mockFetch(status: number, json: unknown): typeof fetch {
  return vi.fn(async () =>
    new Response(JSON.stringify(json), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  ) as unknown as typeof fetch;
}

describe('WaveDeskClient', () => {
  it('unwraps Frappe message envelope', async () => {
    const fetchFn = mockFetch(200, { message: { ok: true } });
    const client = new WaveDeskClient({ baseUrl: 'https://x.test/', fetchFn });
    const result = await client.call<{ ok: boolean }>('wavedesk.ping');
    expect(result).toEqual({ ok: true });
    expect(fetchFn).toHaveBeenCalledWith(
      'https://x.test/api/method/wavedesk.ping',
      expect.objectContaining({ method: 'GET', credentials: 'include' }),
    );
  });

  it('POSTs JSON params', async () => {
    const fetchFn = mockFetch(200, { message: 'ok' });
    const client = new WaveDeskClient({ baseUrl: '', fetchFn });
    await client.call('wavedesk.echo', { value: 1 });
    expect(fetchFn).toHaveBeenCalledWith(
      '/api/method/wavedesk.echo',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ value: 1 }) }),
    );
  });

  it('assignment helpers hit the assign API with null-safe params', async () => {
    const fetchFn = mockFetch(200, { message: { chat: 'CHAT-1' } });
    const client = new WaveDeskClient({ baseUrl: '', fetchFn });
    await client.assignChat('CHAT-1', 'riya@x.test');
    expect(fetchFn).toHaveBeenCalledWith(
      '/api/method/wavedesk.api.assign.assign_chat',
      expect.objectContaining({
        body: JSON.stringify({ chat: 'CHAT-1', agent: 'riya@x.test', team: null }),
      }),
    );
    await client.setChatStatus('CHAT-1', 'snoozed', '2026-07-09 10:00:00');
    expect(fetchFn).toHaveBeenCalledWith(
      '/api/method/wavedesk.api.assign.set_chat_status',
      expect.objectContaining({
        body: JSON.stringify({
          chat: 'CHAT-1',
          status: 'snoozed',
          snoozed_until: '2026-07-09 10:00:00',
        }),
      }),
    );
  });

  it('throws ApiError with status on non-2xx', async () => {
    const fetchFn = mockFetch(403, { exc_type: 'PermissionError' });
    const client = new WaveDeskClient({ baseUrl: '', fetchFn });
    await expect(client.call('wavedesk.secret')).rejects.toThrowError(ApiError);
    await expect(client.call('wavedesk.secret')).rejects.toMatchObject({ status: 403 });
  });
});
