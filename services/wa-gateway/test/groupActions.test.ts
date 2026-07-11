/** P2.3 acceptance: group action endpoints — participants add/remove/promote/
 * demote, subject/description updates, invite revoke — session-scoped and
 * validated. Frappe's audited action layer is the only caller. */
import { randomBytes } from 'node:crypto';
import RedisMock from 'ioredis-mock';
import { pino } from 'pino';
import { afterEach, describe, expect, it } from 'vitest';
import { buildApp } from '../src/app.js';
import { SessionManager } from '../src/baileys/sessionManager.js';
import { MemorySnapshotStorage } from '../src/baileys/snapshot.js';
import { MemoryMediaStorage } from '../src/baileys/media.js';
import { loadConfig } from '../src/config.js';
import { EventPublisher } from '../src/events/publisher.js';
import { INTERNAL_SECRET_HEADER } from '../src/auth/internal.js';
import { makeMockSocketFactory } from './helpers/mockSocket.js';

const logger = pino({ level: 'silent' });
const AUTH = { [INTERNAL_SECRET_HEADER]: 'dev-internal-secret' };
const GID = '120363000011112222@g.us';

function makeAppWithManager() {
  const redis = new RedisMock();
  const { factory, sockets } = makeMockSocketFactory();
  const manager = new SessionManager({
    redis,
    snapshots: new MemorySnapshotStorage(),
    snapshotKey: randomBytes(32),
    factory,
    publisher: new EventPublisher(redis, logger),
    mediaStorage: new MemoryMediaStorage(),
    logger,
    snapshotIntervalMs: 60_000,
  });
  const app = buildApp(loadConfig({ LOG_LEVEL: 'silent' }), { sessionManager: manager });
  return { app, manager, sockets };
}

describe('group action routes', () => {
  let cleanup: (() => Promise<void>) | undefined;

  afterEach(async () => {
    await cleanup?.();
    cleanup = undefined;
  });

  it('participants: validates and forwards to the socket', async () => {
    const { app, manager, sockets } = makeAppWithManager();
    cleanup = () => app.close();
    await manager.create('s1', 'WS-1');

    const bad = await app.inject({
      method: 'POST',
      url: `/sessions/s1/groups/${GID}/participants`,
      headers: AUTH,
      payload: { participants: [], action: 'add' },
    });
    expect(bad.statusCode).toBe(422);

    const badAction = await app.inject({
      method: 'POST',
      url: `/sessions/s1/groups/${GID}/participants`,
      headers: AUTH,
      payload: { participants: ['919111100001@s.whatsapp.net'], action: 'ban' },
    });
    expect(badAction.statusCode).toBe(422);

    const ok = await app.inject({
      method: 'POST',
      url: `/sessions/s1/groups/${GID}/participants`,
      headers: AUTH,
      payload: { participants: ['919111100001@s.whatsapp.net'], action: 'promote' },
    });
    expect(ok.statusCode).toBe(200);
    expect(sockets[0]!.participantActions).toEqual([
      { jid: GID, participants: ['919111100001@s.whatsapp.net'], action: 'promote' },
    ]);

    const missing = await app.inject({
      method: 'POST',
      url: `/sessions/nope/groups/${GID}/participants`,
      headers: AUTH,
      payload: { participants: ['x@s.whatsapp.net'], action: 'add' },
    });
    expect(missing.statusCode).toBe(404);
  });

  it('meta: updates subject and description', async () => {
    const { app, manager, sockets } = makeAppWithManager();
    cleanup = () => app.close();
    await manager.create('s1', 'WS-1');

    const empty = await app.inject({
      method: 'PATCH',
      url: `/sessions/s1/groups/${GID}`,
      headers: AUTH,
      payload: {},
    });
    expect(empty.statusCode).toBe(422);

    const ok = await app.inject({
      method: 'PATCH',
      url: `/sessions/s1/groups/${GID}`,
      headers: AUTH,
      payload: { subject: '  Traders 2.0  ', description: 'new about' },
    });
    expect(ok.statusCode).toBe(200);
    expect(sockets[0]!.metaUpdates).toEqual([
      { jid: GID, subject: 'Traders 2.0' },
      { jid: GID, description: 'new about' },
    ]);
  });

  it('revoke-invite returns the fresh code', async () => {
    const { app, manager, sockets } = makeAppWithManager();
    cleanup = () => app.close();
    await manager.create('s1', 'WS-1');

    const res = await app.inject({
      method: 'POST',
      url: `/sessions/s1/groups/${GID}/revoke-invite`,
      headers: AUTH,
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ invite_code: `NEW-CODE-${GID.slice(0, 6)}` });
    expect(sockets[0]!.revokedInvites).toEqual([GID]);
  });
});
