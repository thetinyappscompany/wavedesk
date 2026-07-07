import Fastify, { type FastifyInstance } from 'fastify';
import { registerInternalAuth } from './auth/internal.js';
import type { SessionManager } from './baileys/sessionManager.js';
import { loadConfig, type GatewayConfig } from './config.js';
import { loggerOptions } from './logger.js';
import { registerRawJsonParser } from './plugins/rawBody.js';
import { registerCloudApiRoutes, type CloudApiDeps } from './routes/cloudapi.js';
import { registerHealthRoutes } from './routes/health.js';
import { registerSessionRoutes } from './routes/sessions.js';

export interface AppDeps {
  sessionManager?: SessionManager;
  cloudApi?: CloudApiDeps;
}

export function buildApp(config: GatewayConfig = loadConfig(), deps: AppDeps = {}): FastifyInstance {
  const app = Fastify({
    logger: loggerOptions(config.logLevel),
  });

  registerRawJsonParser(app);
  registerInternalAuth(app, config.internalSharedSecret);
  registerHealthRoutes(app);
  if (deps.sessionManager) {
    registerSessionRoutes(app, deps.sessionManager);
  }
  if (deps.cloudApi) {
    registerCloudApiRoutes(app, deps.cloudApi);
  }

  return app;
}
