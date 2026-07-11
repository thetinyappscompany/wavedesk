export interface S3Config {
  endpoint: string;
  region: string;
  bucket: string;
  accessKey: string;
  secretKey: string;
}

export interface GatewayConfig {
  host: string;
  port: number;
  logLevel: string;
  /** Shared secret for Frappe ↔ gateway internal auth (required outside dev). */
  internalSharedSecret: string | undefined;
  redisUrl: string;
  /** AES-256-GCM key for session snapshots, base64-encoded 32 bytes. */
  sessionSnapshotKey: string | undefined;
  /** Encrypted session snapshot cadence (master doc §2.2: every 5 min). */
  snapshotIntervalMs: number;
  s3: S3Config;
  /** Bucket for inbound WhatsApp media (separate from session snapshots). */
  mediaBucket: string;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): GatewayConfig {
  return {
    host: env.WA_GATEWAY_HOST ?? '0.0.0.0',
    port: Number(env.WA_GATEWAY_PORT ?? 8081),
    logLevel: env.LOG_LEVEL ?? 'info',
    internalSharedSecret: env.WA_GATEWAY_INTERNAL_SECRET,
    redisUrl: env.REDIS_URL ?? 'redis://localhost:6379',
    sessionSnapshotKey: env.SESSION_SNAPSHOT_KEY,
    snapshotIntervalMs: Number(env.SNAPSHOT_INTERVAL_MS ?? 5 * 60 * 1000),
    mediaBucket: env.S3_MEDIA_BUCKET ?? 'wavedesk-media',
    s3: {
      endpoint: env.S3_ENDPOINT ?? 'http://localhost:9000',
      region: env.S3_REGION ?? 'us-east-1',
      bucket: env.S3_BUCKET ?? 'wavedesk-sessions',
      accessKey: env.S3_ACCESS_KEY ?? '',
      secretKey: env.S3_SECRET_KEY ?? '',
    },
  };
}
