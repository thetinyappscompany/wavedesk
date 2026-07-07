export interface GatewayConfig {
  host: string;
  port: number;
  logLevel: string;
  /** Shared secret for Frappe ↔ gateway internal auth (required outside dev). */
  internalSharedSecret: string | undefined;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): GatewayConfig {
  return {
    host: env.WA_GATEWAY_HOST ?? '0.0.0.0',
    port: Number(env.WA_GATEWAY_PORT ?? 8081),
    logLevel: env.LOG_LEVEL ?? 'info',
    internalSharedSecret: env.WA_GATEWAY_INTERNAL_SECRET,
  };
}
