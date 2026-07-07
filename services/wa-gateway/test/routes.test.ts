import { randomBytes } from 'node:crypto';
import RedisMock from 'ioredis-mock';
import { pino } from 'pino';
import { afterEach, describe, expect, it } from 'vitest';
import { buildApp } from '../src/app.js';
import { SessionManager } from '../src/baileys/sessionManager.js';
import { MemorySnapshotStorage } from '../src/baileys/snapshot.js';
import { loadConfig } from '../src/config.js';
import { EventPublisher } from '../src/events/publisher.js';
import { INTERNAL_SECRET_HEADER } from '../src/auth/internal.js';
import { makeMockSocketFactory } from './helpers/mockSocket.js';

const logger = pino({ level: 'silent' });

function makeAppWithManager(env: NodeJS.ProcessEnv = {}) {
  const redis = new RedisMock();
  const { factory, sockets } = makeMockSocketFactory();
  const manager = new SessionManager({
    redis,
    snapshots: new MemorySnapshotStorage(),
    snapshotKey: randomBytes(32),
    factory,
    publisher: new EventPublisher(redis, logger),
    logger,
    snapshotIntervalMs: 60_000,
  });
  const app = buildApp(loadConfig({ LOG_LEVEL: 'silent', ...env }), {
    sessionManager: manager,
  });
  return { app, manager, sockets };
}

describe('internal auth middleware', () => {
  it('lets /health through without a secret, blocks everything else', async () => {
    const { app } = makeAppWithManager({ WA_GATEWAY_INTERNAL_SECRET: 's3cret' });
    expect((await app.inject({ method: 'GET', url: '/health' })).statusCode).toBe(200);
    expect((await app.inject({ method: 'GET', url: '/sessions' })).statusCode).toBe(401);
    const ok = await app.inject({
      method: 'GET',
      url: '/sessions',
      headers: { [INTERNAL_SECRET_HEADER]: 's3cret' },
    });
    expect(ok.statusCode).toBe(200);
    const wrong = await app.inject({
      method: 'GET',
      url: '/sessions',
      headers: { [INTERNAL_SECRET_HEADER]: 'wrong' },
    });
    expect(wrong.statusCode).toBe(401);
    await app.close();
  });
});

describe('session routes', () => {
  let cleanup: (() => Promise<void>) | undefined;

  afterEach(async () => {
    await cleanup?.();
    cleanup = undefined;
  });

  it('POST /sessions streams SSE status + QR frames until connected', async () => {
    const { app, manager } = makeAppWithManager();
    await app.listen({ port: 0, host: '127.0.0.1' });
    cleanup = async () => {
      await manager.shutdown();
      await app.close();
    };
    const address = app.server.address();
    const port = typeof address === 'object' && address ? address.port : 0;

    const response = await fetch(`http://127.0.0.1:${String(port)}/sessions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ session_id: 'sse-1', workspace: 'WS-00001' }),
    });
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toContain('text/event-stream');

    const body = await response.text(); // stream ends on 'connected'
    const events = body
      .split('\n\n')
      .filter((chunk) => chunk.startsWith('data: '))
      .map((chunk) => JSON.parse(chunk.slice(6)) as { type: string; qr?: string; status?: string });

    const qrEvents = events.filter((e) => e.type === 'qr');
    expect(qrEvents).toHaveLength(1);
    expect(qrEvents[0]!.qr).toMatch(/^data:image\/png;base64,/); // base64 QR frame
    expect(events.at(-1)).toMatchObject({ type: 'status', status: 'connected' });
  });

  it('GET /sessions lists, DELETE removes, unknown DELETE is 404', async () => {
    const { app, manager } = makeAppWithManager();
    cleanup = async () => {
      await manager.shutdown();
      await app.close();
    };
    await manager.create('s1', 'WS-00001');

    const list = await app.inject({ method: 'GET', url: '/sessions' });
    expect(list.json<{ sessions: unknown[] }>().sessions).toHaveLength(1);

    expect((await app.inject({ method: 'DELETE', url: '/sessions/s1' })).statusCode).toBe(204);
    expect((await app.inject({ method: 'DELETE', url: '/sessions/nope' })).statusCode).toBe(404);
  });

  it('POST /sessions/:id/messages sends via the socket (stub level)', async () => {
    const { app, manager, sockets } = makeAppWithManager();
    cleanup = async () => {
      await manager.shutdown();
      await app.close();
    };
    await manager.create('s1', 'WS-00001');

    const res = await app.inject({
      method: 'POST',
      url: '/sessions/s1/messages',
      payload: { to: '919999900001', text: 'hi there' },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json<{ queued: boolean; wa_message_id: string }>()).toMatchObject({
      queued: true,
      wa_message_id: 'MOCK-1',
    });
    expect(sockets[0]!.sent).toHaveLength(1);

    const missing = await app.inject({
      method: 'POST',
      url: '/sessions/ghost/messages',
      payload: { to: '1', text: 'x' },
    });
    expect(missing.statusCode).toBe(404);

    const invalid = await app.inject({
      method: 'POST',
      url: '/sessions/s1/messages',
      payload: { to: '919999900001' },
    });
    expect(invalid.statusCode).toBe(422);
  });
});
