import { timingSafeEqual } from 'node:crypto';
import type { FastifyInstance } from 'fastify';

export const INTERNAL_SECRET_HEADER = 'x-wavedesk-internal';

const PUBLIC_PATHS = new Set(['/health']);

/** Shared-secret middleware for Frappe ↔ gateway calls (master doc §2.2).
 * If no secret is configured (bare dev), everything is open — compose/staging set it. */
export function registerInternalAuth(app: FastifyInstance, secret: string | undefined): void {
  if (!secret) {
    app.log.warn('WA_GATEWAY_INTERNAL_SECRET not set — internal auth disabled (dev only)');
    return;
  }
  const expected = Buffer.from(secret);
  app.addHook('onRequest', (request, reply, done) => {
    if (PUBLIC_PATHS.has(request.url.split('?')[0] ?? '')) {
      done();
      return;
    }
    const provided = request.headers[INTERNAL_SECRET_HEADER];
    const providedBuf = Buffer.from(typeof provided === 'string' ? provided : '');
    const ok =
      providedBuf.length === expected.length && timingSafeEqual(providedBuf, expected);
    if (!ok) {
      void reply.code(401).send({ error: 'unauthorized' });
      return;
    }
    done();
  });
}
