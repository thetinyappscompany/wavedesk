import type { FastifyInstance } from 'fastify';

declare module 'fastify' {
  interface FastifyRequest {
    /** Raw request bytes — needed for Meta's X-Hub-Signature-256 HMAC check. */
    rawBody?: Buffer;
  }
}

/** JSON parser that keeps the raw body buffer alongside the parsed object. */
export function registerRawJsonParser(app: FastifyInstance): void {
  app.removeContentTypeParser('application/json');
  app.addContentTypeParser<Buffer>(
    'application/json',
    { parseAs: 'buffer' },
    (request, body, done) => {
      request.rawBody = body;
      if (body.length === 0) {
        done(null, {});
        return;
      }
      try {
        done(null, JSON.parse(body.toString('utf8')));
      } catch (err) {
        done(err as Error, undefined);
      }
    },
  );
}
