import { createHmac } from 'node:crypto';
import RedisMock from 'ioredis-mock';
import { pino } from 'pino';
import { describe, expect, it, vi } from 'vitest';
import { buildApp } from '../src/app.js';
import { loadCloudApiConfig } from '../src/cloudapi/config.js';
import { GraphClient } from '../src/cloudapi/graphClient.js';
import { loadConfig } from '../src/config.js';
import { WA_EVENTS_STREAM, type WaEvent } from '../src/events/envelope.js';
import { EventPublisher } from '../src/events/publisher.js';

const logger = pino({ level: 'silent' });
const APP_SECRET = 'meta-app-secret';
const VERIFY_TOKEN = 'verify-me';

const CLOUD_ENV = {
  LOG_LEVEL: 'silent',
  META_APP_SECRET: APP_SECRET,
  META_WEBHOOK_VERIFY_TOKEN: VERIFY_TOKEN,
  CLOUD_API_NUMBERS: JSON.stringify({
    '111222333': { token: 'graph-token-1', workspace: 'WS-00001' },
  }),
};

function makeCloudApp(fetchFn: typeof fetch = vi.fn() as typeof fetch) {
  const redis = new RedisMock();
  const cloudConfig = loadCloudApiConfig(CLOUD_ENV);
  const app = buildApp(loadConfig(CLOUD_ENV), {
    cloudApi: {
      config: cloudConfig,
      client: new GraphClient(cloudConfig, fetchFn),
      publisher: new EventPublisher(redis, logger),
    },
  });
  return { app, redis };
}

function sign(body: string): string {
  return `sha256=${createHmac('sha256', APP_SECRET).update(body).digest('hex')}`;
}

async function readEvents(redis: InstanceType<typeof RedisMock>): Promise<WaEvent[]> {
  const entries = (await redis.xrange(WA_EVENTS_STREAM, '-', '+')) as [string, string[]][];
  return entries.map(([, fields]) => JSON.parse(fields[1] ?? '{}') as WaEvent);
}

const WEBHOOK_FIXTURE = {
  entry: [
    {
      changes: [
        {
          value: {
            metadata: { phone_number_id: '111222333' },
            messages: [
              {
                from: '919999900002',
                id: 'wamid.INBOUND1',
                type: 'text',
                timestamp: '1751900000',
                text: { body: 'hello from cloud' },
              },
            ],
            statuses: [{ id: 'wamid.OUT1', status: 'delivered', recipient_id: '919999900002' }],
          },
        },
      ],
    },
  ],
};

describe('Meta webhook handshake (GET)', () => {
  it('echoes hub.challenge for the right verify token', async () => {
    const { app } = makeCloudApp();
    const res = await app.inject({
      method: 'GET',
      url: '/webhooks/meta?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=12345',
    });
    expect(res.statusCode).toBe(200);
    expect(res.body).toBe('12345');
    await app.close();
  });

  it('403s a wrong token', async () => {
    const { app } = makeCloudApp();
    const res = await app.inject({
      method: 'GET',
      url: '/webhooks/meta?hub.mode=subscribe&hub.verify_token=WRONG&hub.challenge=12345',
    });
    expect(res.statusCode).toBe(403);
    await app.close();
  });
});

describe('Meta webhook receiver (POST)', () => {
  it('rejects an invalid signature with 403 and publishes nothing', async () => {
    const { app, redis } = makeCloudApp();
    const body = JSON.stringify(WEBHOOK_FIXTURE);
    const res = await app.inject({
      method: 'POST',
      url: '/webhooks/meta',
      headers: { 'content-type': 'application/json', 'x-hub-signature-256': 'sha256=' + '0'.repeat(64) },
      payload: body,
    });
    expect(res.statusCode).toBe(403);
    expect(await readEvents(redis)).toHaveLength(0);
    await app.close();
  });

  it('rejects when the signature header is missing entirely', async () => {
    const { app } = makeCloudApp();
    const res = await app.inject({
      method: 'POST',
      url: '/webhooks/meta',
      headers: { 'content-type': 'application/json' },
      payload: JSON.stringify(WEBHOOK_FIXTURE),
    });
    expect(res.statusCode).toBe(403);
    await app.close();
  });

  it('normalizes valid webhooks into the SAME wa:events envelope as Baileys', async () => {
    const { app, redis } = makeCloudApp();
    const body = JSON.stringify(WEBHOOK_FIXTURE);
    const res = await app.inject({
      method: 'POST',
      url: '/webhooks/meta',
      headers: { 'content-type': 'application/json', 'x-hub-signature-256': sign(body) },
      payload: body,
    });
    expect(res.statusCode).toBe(200);

    const events = await readEvents(redis);
    expect(events).toHaveLength(2);

    const message = events.find((e) => e.type === 'message.received');
    expect(message).toMatchObject({
      transport: 'cloud_api',
      workspace_hint: 'WS-00001', // resolved via the per-number env map
      wa_chat_id: '919999900002',
      wa_message_id: 'wamid.INBOUND1',
    });
    expect((message?.payload as { text: string }).text).toBe('hello from cloud');

    const status = events.find((e) => e.type === 'message.status');
    expect(status).toMatchObject({
      transport: 'cloud_api',
      wa_message_id: 'wamid.OUT1',
    });
    expect((status?.payload as { status: string }).status).toBe('delivered');
    await app.close();
  });

  it('webhook path is exempt from internal-secret auth (Meta cannot send it)', async () => {
    const redis = new RedisMock();
    const cloudConfig = loadCloudApiConfig(CLOUD_ENV);
    const app = buildApp(
      loadConfig({ ...CLOUD_ENV, WA_GATEWAY_INTERNAL_SECRET: 'internal-s3cret' }),
      {
        cloudApi: {
          config: cloudConfig,
          client: new GraphClient(cloudConfig),
          publisher: new EventPublisher(redis, logger),
        },
      },
    );
    const body = JSON.stringify(WEBHOOK_FIXTURE);
    const res = await app.inject({
      method: 'POST',
      url: '/webhooks/meta',
      headers: { 'content-type': 'application/json', 'x-hub-signature-256': sign(body) },
      payload: body,
    });
    expect(res.statusCode).toBe(200); // signature IS the auth on this path
    await app.close();
  });
});

describe('Graph send client', () => {
  it('sends text through the Graph API with the per-number token', async () => {
    const fetchFn = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ messages: [{ id: 'wamid.SENT1' }] }), { status: 200 }),
      ),
    ) as unknown as typeof fetch;
    const { app } = makeCloudApp(fetchFn);

    const res = await app.inject({
      method: 'POST',
      url: '/cloud/111222333/messages',
      payload: { to: '919999900002', text: 'reply from wavedesk' },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json<{ wa_message_id: string }>().wa_message_id).toBe('wamid.SENT1');

    const call = (fetchFn as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      { headers: Record<string, string>; body: string },
    ];
    expect(call[0]).toBe('https://graph.facebook.com/v23.0/111222333/messages');
    expect(call[1].headers.authorization).toBe('Bearer graph-token-1');
    expect(JSON.parse(call[1].body)).toMatchObject({ to: '919999900002', type: 'text' });
    await app.close();
  });

  it('404s an unknown phone_number_id and 502s Graph errors', async () => {
    const fetchFn = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ error: { message: 'bad token' } }), { status: 401 }),
      ),
    ) as unknown as typeof fetch;
    const { app } = makeCloudApp(fetchFn);

    const unknown = await app.inject({
      method: 'POST',
      url: '/cloud/999/messages',
      payload: { to: '1', text: 'x' },
    });
    expect(unknown.statusCode).toBe(404);

    const graphError = await app.inject({
      method: 'POST',
      url: '/cloud/111222333/messages',
      payload: { to: '1', text: 'x' },
    });
    expect(graphError.statusCode).toBe(502);
    await app.close();
  });
});
