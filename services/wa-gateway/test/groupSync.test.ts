/** P2.1 acceptance: on connect the whole group registry is published; live
 * metadata + participant changes stream as they happen; invite links are
 * fetched only where we hold admin. */
import { randomBytes } from 'node:crypto';
import RedisMock from 'ioredis-mock';
import type { Redis } from 'ioredis';
import { pino } from 'pino';
import { beforeEach, describe, expect, it } from 'vitest';
import { SessionManager } from '../src/baileys/sessionManager.js';
import { MemorySnapshotStorage } from '../src/baileys/snapshot.js';
import type { GroupMetadataLite } from '../src/baileys/socket.js';
import { WA_EVENTS_STREAM, type WaEvent } from '../src/events/envelope.js';
import { EventPublisher } from '../src/events/publisher.js';
import { makeMockSocketFactory } from './helpers/mockSocket.js';

const logger = pino({ level: 'silent' });

function makeManager() {
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
  return { manager, redis, sockets };
}

async function readEvents(redis: Redis): Promise<WaEvent[]> {
  const entries = (await redis.xrange(WA_EVENTS_STREAM, '-', '+')) as [string, string[]][];
  return entries.map(([, fields]) => JSON.parse(fields[1] ?? '{}') as WaEvent);
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => {
  // group sync runs async after 'open' — a few macrotask turns settle it
  await tick();
  await tick();
  await tick();
};

function group(id: string, subject: string, weAreAdmin = false): GroupMetadataLite {
  return {
    id,
    subject,
    desc: 'about us',
    owner: '917700000009@s.whatsapp.net',
    participants: [
      // our own jid carries a device suffix on the socket, bare in groups
      { id: '919999900000@s.whatsapp.net', admin: weAreAdmin ? 'admin' : null },
      { id: '919111100001@s.whatsapp.net', admin: null },
      { id: '917700000009@s.whatsapp.net', admin: 'superadmin' },
    ],
  };
}

describe('group registry sync', () => {
  let ctx: ReturnType<typeof makeManager>;

  beforeEach(() => {
    ctx = makeManager();
  });

  it('publishes group.upsert for every group on connect', async () => {
    await ctx.manager.create('s1', 'WS-1');
    // socket exists now but 'open' fires on the next macrotask — set groups first
    ctx.sockets[0]!.groupsToReturn = [
      group('g1@g.us', 'Traders A'),
      group('g2@g.us', 'Traders B', true),
    ];
    await settle();

    const upserts = (await readEvents(ctx.redis)).filter((e) => e.type === 'group.upsert');
    expect(upserts).toHaveLength(2);
    expect(upserts.map((e) => e.wa_chat_id).sort()).toEqual(['g1@g.us', 'g2@g.us']);

    const payload = upserts.find((e) => e.wa_chat_id === 'g2@g.us')?.payload as {
      group: GroupMetadataLite;
      owned_by_us: boolean;
      invite_code: string | null;
      session_id: string;
    };
    expect(payload.session_id).toBe('s1');
    expect(payload.group.subject).toBe('Traders B');
    expect(payload.group.participants).toHaveLength(3);
    expect(payload.owned_by_us).toBe(true);
    expect(payload.invite_code).toBe('MOCK-INVITE-g2@g.u');
  });

  it('fetches invite links only where we are admin', async () => {
    await ctx.manager.create('s1', 'WS-1');
    ctx.sockets[0]!.groupsToReturn = [
      group('g1@g.us', 'Not ours'),
      group('g2@g.us', 'Ours', true),
    ];
    await settle();

    expect(ctx.sockets[0]!.inviteCodeCalls).toEqual(['g2@g.us']);
    const upserts = (await readEvents(ctx.redis)).filter((e) => e.type === 'group.upsert');
    const notOurs = upserts.find((e) => e.wa_chat_id === 'g1@g.us')?.payload as {
      owned_by_us: boolean;
      invite_code: string | null;
    };
    expect(notOurs.owned_by_us).toBe(false);
    expect(notOurs.invite_code).toBeNull();
  });

  it('streams live groups.upsert / groups.update / participant changes', async () => {
    await ctx.manager.create('s1', 'WS-1');
    await settle();

    ctx.sockets[0]!.emitGroupsUpsert([group('g9@g.us', 'Brand New')]);
    ctx.sockets[0]!.emitGroupsUpdate([{ id: 'g9@g.us', subject: 'Renamed' }]);
    ctx.sockets[0]!.emitGroupParticipants({
      id: 'g9@g.us',
      participants: ['919111100001@s.whatsapp.net'],
      action: 'promote',
    });
    await settle();

    const events = await readEvents(ctx.redis);
    const upsert = events.find((e) => e.type === 'group.upsert' && e.wa_chat_id === 'g9@g.us');
    expect(upsert).toBeDefined();

    const update = events.find((e) => e.type === 'group.update');
    expect(update?.wa_chat_id).toBe('g9@g.us');
    expect((update?.payload as { update: { subject: string } }).update.subject).toBe('Renamed');

    const participants = events.find((e) => e.type === 'group.participants');
    expect(participants?.wa_chat_id).toBe('g9@g.us');
    expect(participants?.payload).toMatchObject({
      session_id: 's1',
      action: 'promote',
      participants: ['919111100001@s.whatsapp.net'],
    });
  });

  it('a failing sync never kills the session', async () => {
    await ctx.manager.create('s1', 'WS-1');
    ctx.sockets[0]!.fetchAllGroups = () => Promise.reject(new Error('boom'));
    // force a reconnect-style open to re-trigger the sync
    ctx.sockets[0]!.emitConnection({ connection: 'open' });
    await settle();

    expect(ctx.manager.list()[0]?.status).toBe('connected');
  });
});
