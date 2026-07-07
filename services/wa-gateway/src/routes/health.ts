import type { FastifyInstance } from 'fastify';

export function registerHealthRoutes(app: FastifyInstance): void {
  app.get('/health', () => ({
    status: 'ok',
    service: 'wa-gateway',
    uptime_s: Math.round(process.uptime()),
  }));
}
