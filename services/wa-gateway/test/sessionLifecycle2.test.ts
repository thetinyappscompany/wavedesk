import { randomBytes } from 'node:crypto';
import RedisMock from 'ioredis-mock';
import type { Redis } from 'ioredis';
import { pino } from 'pino';
import { describe, expect, it } from 'vitest';
import { buildApp } from '../src/app.js';
import { RedisAuthStore } from '../src/baileys/authStore.js';
import { SessionManager } from '../src/baileys/sessionManager.js';
import { MemorySnapshotStorage } from '../src/baileys/snapshot.js';
import { loadConfig } from '../src/config.js';
import { EventPublisher } from '../src/events/publisher.js';
import { makeMockSocketFactory, simulatePairing } from './helpers/mockSocket.js';

const logger = pino({ level: 'silent' });
const tick = () => new Promise((resolve) => setImmediate(resolve));

function make() {
  const redis: Redis = new RedisMock();
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
  const app = buildApp(loadConfig({ LOG_LEVEL: 'silent' }), { sessionManager: manager });
  return { app, manager, redis, sockets };
}

describe('P1.1 gateway session API', () => {
  it('POST /sessions with stream:false returns JSON immediately', async () => {
    const { app, manager } = make();
    const res = await app.inject({
      method: 'POST',
      url: '/sessions',
      payload: { session_id: 'j1', workspace: 'WS-1', stream: false },
    });
    expect(res.statusCode).toBe(201);
    expect(res.json<{ session: { id: string } }>().session.id).toBe('j1');
    await manager.shutdown();
    await app.close();
  });

  it('GET /sessions/:id serves the current QR while pairing, null after connect', async () => {
    const { app, manager } = make();
    await app.inject({
      method: 'POST',
      url: '/sessions',
      payload: { session_id: 'q1', workspace: 'WS-1', stream: false },
    });
    // between QR emission and 'open' the QR is exposed; after connect it's spent
    await tick();
    const after = await app.inject({ method: 'GET', url: '/sessions/q1' });
    expect(after.statusCode).toBe(200);
    const body = after.json<{ session: { status: string }; qr: string | null }>();
    expect(body.session.status).toBe('connected');
    expect(body.qr).toBeNull();

    expect((await app.inject({ method: 'GET', url: '/sessions/ghost' })).statusCode).toBe(404);
    await manager.shutdown();
    await app.close();
  });

  it('disconnect keeps auth; reconnect resumes without QR', async () => {
    const { app, manager, redis, sockets } = make();
    await manager.create('r1', 'WS-1');
    await tick();

    // pair "for real" so creds persist
    const store = new RedisAuthStore(redis, 'r1');
    const loaded = await store.load();
    simulatePairing(loaded.state);
    await loaded.saveCreds();

    const disc = await app.inject({ method: 'POST', url: '/sessions/r1/disconnect' });
    expect(disc.statusCode).toBe(204);
    expect(manager.get('r1')?.info.status).toBe('disconnected');
    expect(await store.hasCreds()).toBe(true); // auth KEPT

    const rec = await app.inject({ method: 'POST', url: '/sessions/r1/reconnect' });
    expect(rec.statusCode).toBe(200);
    expect(rec.json<{ restored: boolean }>().restored).toBe(true); // ← no QR re-scan
    await tick();
    expect(sockets.at(-1)?.hadCredsAtCreation).toBe(true);
    expect(manager.get('r1')?.info.status).toBe('connected');
    await manager.shutdown();
    await app.close();
  });
});
