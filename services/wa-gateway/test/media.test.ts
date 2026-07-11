import { randomBytes } from 'node:crypto';
import RedisMock from 'ioredis-mock';
import type { Redis } from 'ioredis';
import { pino } from 'pino';
import { beforeEach, describe, expect, it } from 'vitest';
import { SessionManager } from '../src/baileys/sessionManager.js';
import { MemoryMediaStorage, extractMediaMeta, mediaKey } from '../src/baileys/media.js';
import { MemorySnapshotStorage } from '../src/baileys/snapshot.js';
import { WA_EVENTS_STREAM, type WaEvent } from '../src/events/envelope.js';
import { EventPublisher } from '../src/events/publisher.js';
import type { InboundMessage } from '../src/baileys/socket.js';
import { makeMockSocketFactory } from './helpers/mockSocket.js';

const logger = pino({ level: 'silent' });
const tick = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => {
  await tick();
  await tick();
};

function make() {
  const redis: Redis = new RedisMock();
  const mediaStorage = new MemoryMediaStorage();
  const { factory, sockets } = makeMockSocketFactory();
  const manager = new SessionManager({
    redis,
    snapshots: new MemorySnapshotStorage(),
    snapshotKey: randomBytes(32),
    factory,
    publisher: new EventPublisher(redis, logger),
    mediaStorage,
    logger,
    snapshotIntervalMs: 60_000,
  });
  return { manager, redis, sockets, mediaStorage };
}

async function readEvents(redis: Redis): Promise<WaEvent[]> {
  const entries = (await redis.xrange(WA_EVENTS_STREAM, '-', '+')) as [string, string[]][];
  return entries.map(([, fields]) => JSON.parse(fields[1] ?? '{}') as WaEvent);
}

const imageMsg = (id: string, fromMe = false): InboundMessage => ({
  key: { remoteJid: '919999900001@s.whatsapp.net', id, fromMe },
  message: { imageMessage: { mimetype: 'image/jpeg', caption: 'hi', fileLength: 2048 } },
  pushName: 'Tester',
});

describe('extractMediaMeta', () => {
  it('returns null for text and location (non-media)', () => {
    expect(extractMediaMeta({ key: {}, message: { conversation: 'hi' } })).toBeNull();
    expect(
      extractMediaMeta({ key: {}, message: { locationMessage: { name: 'HQ' } } }),
    ).toBeNull();
  });

  it('parses an image with caption and byte length', () => {
    const meta = extractMediaMeta(imageMsg('m1'));
    expect(meta).toMatchObject({ type: 'image', mimetype: 'image/jpeg', size: 2048 });
    expect(meta?.isVoice).toBe(false);
  });

  it('flags a push-to-talk audio as a voice note with duration', () => {
    const meta = extractMediaMeta({
      key: {},
      message: { audioMessage: { mimetype: 'audio/ogg', seconds: 7, ptt: true } },
    });
    expect(meta).toMatchObject({ type: 'audio', isVoice: true, duration: 7 });
  });

  it('non-ptt audio is not a voice note', () => {
    const meta = extractMediaMeta({
      key: {},
      message: { audioMessage: { mimetype: 'audio/mp4', seconds: 30, ptt: false } },
    });
    expect(meta).toMatchObject({ type: 'audio', isVoice: false, duration: 30 });
  });

  it('extracts a document filename', () => {
    const meta = extractMediaMeta({
      key: {},
      message: { documentMessage: { mimetype: 'application/pdf', fileName: 'invoice.pdf' } },
    });
    expect(meta).toMatchObject({ type: 'document', filename: 'invoice.pdf' });
  });

  it('unwraps view-once / ephemeral media', () => {
    const meta = extractMediaMeta({
      key: {},
      message: { viewOnceMessageV2: { message: { imageMessage: { mimetype: 'image/png' } } } },
    });
    expect(meta).toMatchObject({ type: 'image', mimetype: 'image/png' });
  });
});

describe('mediaKey', () => {
  it('is workspace-scoped, message-addressed, and sanitized', () => {
    expect(mediaKey('WS-1', 'WAMID.abc')).toBe('media/WS-1/WAMID_abc');
    // a hostile id can't escape the media/ prefix
    expect(mediaKey('WS-1', '../../etc/passwd')).toBe('media/WS-1/______etc_passwd');
  });
});

describe('SessionManager media pipeline', () => {
  let ctx: ReturnType<typeof make>;

  beforeEach(() => {
    ctx = make();
  });

  it('downloads inbound media, stores it, and attaches a media ref to the event', async () => {
    await ctx.manager.create('s1', 'WS-00001');
    await settle();
    ctx.sockets[0]!.emitMessages([imageMsg('WAMID.1')]);
    await settle();

    const key = mediaKey('WS-00001', 'WAMID.1');
    expect(ctx.mediaStorage.blobs.has(key)).toBe(true);
    expect(ctx.mediaStorage.blobs.get(key)?.contentType).toBe('image/jpeg');
    expect(ctx.sockets[0]!.downloadCalls).toHaveLength(1);

    // RedisMock shares the stream across a file's tests — match on the id.
    const event = (await readEvents(ctx.redis)).find((e) => e.wa_message_id === 'WAMID.1');
    const media = (event?.payload as { media?: Record<string, unknown> }).media;
    expect(media).toMatchObject({ type: 'image', key, mimetype: 'image/jpeg' });
  });

  it('degrades to metadata-only when the download fails (key null)', async () => {
    await ctx.manager.create('s1', 'WS-00001');
    await settle();
    ctx.sockets[0]!.mediaToReturn = null; // simulate expired/undownloadable media
    ctx.sockets[0]!.emitMessages([imageMsg('WAMID.2')]);
    await settle();

    expect(ctx.mediaStorage.blobs.has(mediaKey('WS-00001', 'WAMID.2'))).toBe(false);
    const event = (await readEvents(ctx.redis)).find((e) => e.wa_message_id === 'WAMID.2');
    const media = (event?.payload as { media?: Record<string, unknown> }).media;
    expect(media).toMatchObject({ type: 'image', key: null });
  });

  it('does not download outbound (fromMe) media', async () => {
    await ctx.manager.create('s1', 'WS-00001');
    await settle();
    ctx.sockets[0]!.emitMessages([imageMsg('WAMID.3', true)]);
    await settle();

    expect(ctx.sockets[0]!.downloadCalls).toHaveLength(0);
    expect(ctx.mediaStorage.blobs.has(mediaKey('WS-00001', 'WAMID.3'))).toBe(false);
    const event = (await readEvents(ctx.redis)).find((e) => e.wa_message_id === 'WAMID.3');
    const media = (event?.payload as { media?: Record<string, unknown> }).media;
    expect(media).toMatchObject({ type: 'image', key: null });
  });

  it('leaves text messages untouched (no media ref)', async () => {
    await ctx.manager.create('s1', 'WS-00001');
    await settle();
    ctx.sockets[0]!.emitMessages([
      { key: { remoteJid: '919999900001@s.whatsapp.net', id: 'WAMID.4' }, message: { conversation: 'hi' } },
    ]);
    await settle();

    expect(ctx.sockets[0]!.downloadCalls).toHaveLength(0);
    const event = (await readEvents(ctx.redis)).find((e) => e.wa_message_id === 'WAMID.4');
    expect((event?.payload as { media?: unknown }).media).toBeUndefined();
  });
});
