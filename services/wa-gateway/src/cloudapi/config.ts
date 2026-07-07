/** Cloud API number registry — Phase 0: per-number tokens from env
 * (CLOUD_API_NUMBERS JSON map). Embedded-signup per-tenant creds land in Phase 3. */

export interface CloudNumberConfig {
  token: string;
  workspace: string;
}

export interface CloudApiConfig {
  graphApiVersion: string;
  verifyToken: string | undefined;
  appSecret: string | undefined;
  /** phone_number_id → {token, workspace} */
  numbers: Record<string, CloudNumberConfig>;
}

export function loadCloudApiConfig(env: NodeJS.ProcessEnv = process.env): CloudApiConfig {
  let numbers: Record<string, CloudNumberConfig> = {};
  if (env.CLOUD_API_NUMBERS) {
    numbers = JSON.parse(env.CLOUD_API_NUMBERS) as Record<string, CloudNumberConfig>;
  }
  return {
    graphApiVersion: env.GRAPH_API_VERSION ?? 'v23.0',
    verifyToken: env.META_WEBHOOK_VERIFY_TOKEN,
    appSecret: env.META_APP_SECRET,
    numbers,
  };
}
