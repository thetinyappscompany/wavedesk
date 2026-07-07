import Fastify, { type FastifyInstance } from 'fastify';
import { loadConfig, type GatewayConfig } from './config.js';
import { loggerOptions } from './logger.js';
import { registerHealthRoutes } from './routes/health.js';

export function buildApp(config: GatewayConfig = loadConfig()): FastifyInstance {
  const app = Fastify({
    logger: loggerOptions(config.logLevel),
  });

  registerHealthRoutes(app);

  return app;
}
