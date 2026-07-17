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
  autoOpen?: boolean;
  credsPromoteGraceMs?: number;
}) {
  const redis = overrides?.redis ?? (new RedisMock());
  const snapshots = overrides?.snapshots ?? new MemorySnapshotStorage();
  const snapshotKey = overrides?.snapshotKey ?? randomBytes(32);
  const mediaStorage = new MemoryMediaStorage();
  const { factory, sockets } = makeMockSocketFactory({ autoOpen: overrides?.autoOpen ?? true });
  const manager = new SessionManager({
    redis,
    snapshots,
    snapshotKey,
    factory,
    publisher: new EventPublisher(redis, logger),
    mediaStorage,
    logger,
    snapshotIntervalMs: 60_000,
    credsPromoteGraceMs: overrides?.credsPromoteGraceMs ?? 20,
  });
  return { manager, redis, snapshots, snapshotKey, sockets, mediaStorage };
}

async function readEvents(redis: Redis): Promise<WaEvent[]> {
  const entries = (await redis.xrange(WA_EVENTS_STREAM, '-', '+')) as [string, string[]][];
  return entries.map(([, fields]) => JSON.parse(fields[1] ?? '{}') as WaEvent);
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

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
      {
        id: 's1',
        workspace: 'WS-00001',
        status: 'connected',
        transport: 'baileys',
        phone: '919999900000:1@s.whatsapp.net', // set from ownJid() on connect
      },
    ]);
  });

  it('connects via a creds update when the fork never delivers connection:open', async () => {
    // The whiskeysockets fork can buffer 'connection: open' during
    // AwaitingInitialSync — simulate that by suppressing the auto 'open'.
    const noOpen = makeManager({ autoOpen: false });
    const statuses: string[] = [];
    const handle = await noOpen.manager.create('s2', 'WS-00002');
    handle.emitter.on('status', (s: string) => statuses.push(s));
    await tick();
    expect(handle.info.status).toBe('connecting'); // no 'open' arrived

    // A creds update carrying the registered device promotes it to connected —
    // after the grace window (an instant promotion would false-connect restored
    // sessions whose creds rotate mid-handshake).
    noOpen.sockets[0]!.emitCreds();
    await tick();
    expect(handle.info.status).toBe('connecting'); // grace window still open
    await sleep(40); // > credsPromoteGraceMs (20ms in tests)
    expect(statuses).toContain('connected');
    expect(noOpen.manager.list()[0]).toMatchObject({
      status: 'connected',
      phone: '919999900000:1@s.whatsapp.net',
    });

    // ioredis-mock shares its store across instances — clear s2 from the shared
    // registry so later tests that assert registry contents aren't polluted.
    await noOpen.manager.destroy('s2');
  });

  it('never publishes connected for a creds update during a doomed handshake', async () => {
    // A RESTORED session persists routine key rotations during a reconnect
    // handshake — before 'open', and before the failure close arrives. The
    // grace-delayed promotion must be cancelled by the close, so the backend
    // never sees a false 'connected'.
    const noOpen = makeManager({ autoOpen: false });
    const statuses: string[] = [];
    const handle = await noOpen.manager.create('s3', 'WS-00003');
    handle.emitter.on('status', (s: string) => statuses.push(s));
    await tick();

    noOpen.sockets[0]!.emitCreds(); // mid-handshake creds rotation
    await tick();
    // The doomed handshake closes within the grace window (e.g. 401 logged out).
    noOpen.sockets[0]!.emitConnection({ connection: 'close' });
    await sleep(40); // let the (cancelled) grace timer elapse

    expect(statuses).not.toContain('connected');
    expect(handle.info.status).toBe('disconnected');
    const events = await readEvents(noOpen.redis);
    const published = events
      .filter((e) => e.type === 'session.status')
      .map((e) => (e.payload as { session_id: string; status: string }))
      .filter((p) => p.session_id === 's3')
      .map((p) => p.status);
    expect(published).not.toContain('connected');

    await noOpen.manager.destroy('s3');
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
