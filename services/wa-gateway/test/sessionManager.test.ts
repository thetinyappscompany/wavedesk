import { randomBytes } from 'node:crypto';
import RedisMock from 'ioredis-mock';
import type { Redis } from 'ioredis';
import { pino } from 'pino';
import { beforeEach, describe, expect, it } from 'vitest';
import { RedisAuthStore } from '../src/baileys/authStore.js';
import { SessionExistsError, SessionManager } from '../src/baileys/sessionManager.js';
import { MemorySnapshotStorage } from '../src/baileys/snapshot.js';
import { MemoryMediaStorage } from '../src/baileys/media.js';
import { WA_EVENTS_STREAM, type WaEvent } from '../src/events/envelope.js';
import { EventPublisher } from '../src/events/publisher.js';
import { makeMockSocketFactory, simulatePairing } from './helpers/mockSocket.js';

const logger = pino({ level: 'silent' });

function makeManager(overrides?: {
  redis?: Redis;
  snapshots?: MemorySnapshotStorage;
  snapshotKey?: Buffer;
}) {
  const redis = overrides?.redis ?? (new RedisMock());
  const snapshots = overrides?.snapshots ?? new MemorySnapshotStorage();
  const snapshotKey = overrides?.snapshotKey ?? randomBytes(32);
  const mediaStorage = new MemoryMediaStorage();
  const { factory, sockets } = makeMockSocketFactory();
  const manager = new SessionManager({
    redis,
    snapshots,
    snapshotKey,
    factory,
    publisher: new EventPublisher(redis, logger),
    mediaStorage,
    logger,
    snapshotIntervalMs: 60_000,
  });
  return { manager, redis, snapshots, snapshotKey, sockets, mediaStorage };
}

async function readEvents(redis: Redis): Promise<WaEvent[]> {
  const entries = (await redis.xrange(WA_EVENTS_STREAM, '-', '+')) as [string, string[]][];
  return entries.map(([, fields]) => JSON.parse(fields[1] ?? '{}') as WaEvent);
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

describe('SessionManager lifecycle', () => {
  let ctx: ReturnType<typeof makeManager>;

  beforeEach(() => {
    ctx = makeManager();
  });

  it('creates a session: fresh session emits QR then connects', async () => {
    const qrs: string[] = [];
    const statuses: string[] = [];
    const handle = await ctx.manager.create('s1', 'WS-00001');
    handle.emitter.on('qr', (qr: string) => qrs.push(qr));
    handle.emitter.on('status', (s: string) => statuses.push(s));
    await tick();

    expect(handle.credsExisted).toBe(false);
    expect(qrs).toEqual(['mock-qr-payload']);
    expect(statuses).toContain('connected');
    expect(ctx.manager.list()).toEqual([
      { id: 's1', workspace: 'WS-00001', status: 'connected', transport: 'baileys' },
    ]);
  });

  it('rejects duplicate session ids', async () => {
    await ctx.manager.create('s1', 'WS-00001');
    await expect(ctx.manager.create('s1', 'WS-00001')).rejects.toThrow(SessionExistsError);
  });

  it('publishes session.status and message.received to wa:events', async () => {
    await ctx.manager.create('s1', 'WS-00001');
    await tick();
    ctx.sockets[0]!.emitMessages([
      { key: { remoteJid: '919999900001@s.whatsapp.net', id: 'WAMID.1' }, message: { conversation: 'hi' } },
    ]);
    await tick();

    const events = await readEvents(ctx.redis);
    const statusEvents = events.filter((e) => e.type === 'session.status');
    const messageEvents = events.filter((e) => e.type === 'message.received');
    expect(statusEvents.length).toBeGreaterThanOrEqual(1);
    expect(statusEvents[0]).toMatchObject({ transport: 'baileys', workspace_hint: 'WS-00001' });
    expect(messageEvents).toHaveLength(1);
    expect(messageEvents[0]).toMatchObject({
      transport: 'baileys',
      wa_chat_id: '919999900001@s.whatsapp.net',
      wa_message_id: 'WAMID.1',
      workspace_hint: 'WS-00001',
    });
    expect(typeof messageEvents[0]!.ts).toBe('string');
  });

  it('sendText routes through the socket and normalizes the jid', async () => {
    await ctx.manager.create('s1', 'WS-00001');
    await tick();
    const result = await ctx.manager.sendText('s1', '+91 99999 00001', 'hello');
    expect(ctx.sockets[0]!.sent[0]).toEqual({
      jid: '919999900001@s.whatsapp.net',
      content: { text: 'hello' },
    });
    expect(result.wa_message_id).toBe('MOCK-1');
  });

  it('destroy logs out, clears auth state and registry', async () => {
    await ctx.manager.create('s1', 'WS-00001');
    await tick();
    // Persist some creds first, as a paired session would.
    const store = new RedisAuthStore(ctx.redis, 's1');
    expect(await ctx.manager.destroy('s1')).toBe(true);
    expect(ctx.sockets[0]!.loggedOut).toBe(true);
    expect(await store.hasCreds()).toBe(false);
    expect(await ctx.redis.hgetall('wa:sessions')).toEqual({});
    expect(ctx.manager.list()).toEqual([]);
    expect(await ctx.manager.destroy('s1')).toBe(false);
  });
});

describe('restart without re-scan (THE Session 0.6 acceptance)', () => {
  it('a paired session restored by a new manager instance requests NO QR', async () => {
    const redis = new RedisMock();
    const snapshots = new MemorySnapshotStorage();
    const snapshotKey = randomBytes(32);

    // --- process 1: pair the session, then graceful shutdown ---
    const first = makeManager({ redis, snapshots, snapshotKey });
    const handle = await first.manager.create('s1', 'WS-00001');
    await tick();
    expect(handle.credsExisted).toBe(false); // fresh pair → QR was needed

    // Simulate the QR scan completing: creds become "registered" and persist.
    const store = new RedisAuthStore(redis, 's1');
    const loaded = await store.load();
    simulatePairing(loaded.state);
    await loaded.saveCreds();

    await first.manager.shutdown(); // snapshots written, sockets closed, auth KEPT

    // --- process 2: fresh manager, same stores ---
    const second = makeManager({ redis, snapshots, snapshotKey });
    const restored = await second.manager.restoreAll();
    await tick();

    expect(restored).toHaveLength(1);
    expect(restored[0]!.credsExisted).toBe(true);
    expect(second.sockets[0]!.hadCredsAtCreation).toBe(true); // ← no QR re-scan
  });

  it('restores from the encrypted S3 snapshot when Redis lost the hot state', async () => {
    const snapshots = new MemorySnapshotStorage();
    const snapshotKey = randomBytes(32);

    // process 1 with its own redis: pair + snapshot
    const redis1 = new RedisMock();
    const first = makeManager({ redis: redis1, snapshots, snapshotKey });
    await first.manager.create('s1', 'WS-00001');
    await tick();
    const store1 = new RedisAuthStore(redis1, 's1');
    const loaded = await store1.load();
    simulatePairing(loaded.state);
    await loaded.saveCreds();
    expect(await first.manager.snapshotAll()).toBe(1);
    expect(snapshots.blobs.get('s1')).toBeDefined();
    expect(snapshots.blobs.get('s1')).not.toContain('919999900000'); // encrypted, not plaintext

    // process 2: EMPTY redis (hot state gone) but registry re-seeded + same snapshots
    const redis2 = new RedisMock();
    await redis2.hset('wa:sessions', 's1', JSON.stringify({ workspace: 'WS-00001' }));
    const second = makeManager({ redis: redis2, snapshots, snapshotKey });
    const restored = await second.manager.restoreAll();
    await tick();

    expect(restored[0]!.credsExisted).toBe(true);
    expect(second.sockets[0]!.hadCredsAtCreation).toBe(true);
  });
});
