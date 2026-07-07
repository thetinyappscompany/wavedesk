import Fastify, { type FastifyInstance } from 'fastify';
import { registerInternalAuth } from './auth/internal.js';
import type { SessionManager } from './baileys/sessionManager.js';
import { loadConfig, type GatewayConfig } from './config.js';
import { loggerOptions } from './logger.js';
import { registerHealthRoutes } from './routes/health.js';
import { registerSessionRoutes } from './routes/sessions.js';

export interface AppDeps {
  sessionManager?: SessionManager;
}

export function buildApp(config: GatewayConfig = loadConfig(), deps: AppDeps = {}): FastifyInstance {
  const app = Fastify({
    logger: loggerOptions(config.logLevel),
  });

  registerInternalAuth(app, config.internalSharedSecret);
  registerHealthRoutes(app);
  if (deps.sessionManager) {
    registerSessionRoutes(app, deps.sessionManager);
  }

  return app;
}
