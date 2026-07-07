import { describe, expect, it } from 'vitest';
import { buildApp } from '../src/app.js';
import { loadConfig } from '../src/config.js';

describe('GET /health', () => {
  it('returns 200 with service status', async () => {
    const app = buildApp(loadConfig({ LOG_LEVEL: 'silent' }));
    const res = await app.inject({ method: 'GET', url: '/health' });
    expect(res.statusCode).toBe(200);
    const json = res.json<{ status: string; service: string }>();
    expect(json.status).toBe('ok');
    expect(json.service).toBe('wa-gateway');
    await app.close();
  });
});
