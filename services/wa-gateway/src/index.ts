import { Redis } from 'ioredis';
import { buildApp } from './app.js';
import { realSocketFactory } from './baileys/realSocket.js';
import { loadCloudApiConfig } from './cloudapi/config.js';
import { GraphClient } from './cloudapi/graphClient.js';
import { SessionManager } from './baileys/sessionManager.js';
import { S3MediaStorage } from './baileys/media.js';
import { S3SnapshotStorage } from './baileys/snapshot.js';
import { loadConfig } from './config.js';
import { parseKey } from './crypto/secretbox.js';
import { createLogger } from './logger.js';
import { EventPublisher } from './events/publisher.js';
import { initSentry } from './observability/sentry.js';

const config = loadConfig();
const logger = createLogger(config.logLevel);
initSentry(process.env.SENTRY_DSN, logger);

const redis = new Redis(config.redisUrl, { lazyConnect: false, maxRetriesPerRequest: 3 });
const publisher = new EventPublisher(redis, logger);
const manager = new SessionManager({
  redis,
  snapshots: new S3SnapshotStorage(config.s3),
  snapshotKey: config.sessionSnapshotKey ? parseKey(config.sessionSnapshotKey) : undefined,
  factory: realSocketFactory,
  publisher,
  mediaStorage: new S3MediaStorage(config.s3, config.mediaBucket),
  logger,
  snapshotIntervalMs: config.snapshotIntervalMs,
});

const cloudConfig = loadCloudApiConfig();
const app = buildApp(config, {
  sessionManager: manager,
  cloudApi: {
    config: cloudConfig,
    client: new GraphClient(cloudConfig),
    publisher,
  },
});

app
  .listen({ host: config.host, port: config.port })
  .then(async () => {
    // Boot-time restore: every registered session re-attaches without QR re-scan.
    const restored = await manager.restoreAll();
    app.log.info({ restored_count: restored.length }, 'session restore complete');
    manager.startSnapshotTimer();
  })
  .catch((err: unknown) => {
    app.log.error(err);
    process.exit(1);
  });

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    void manager
      .shutdown()
      .then(() => app.close())
      .then(() => redis.quit())
      .then(() => process.exit(0));
  });
}
