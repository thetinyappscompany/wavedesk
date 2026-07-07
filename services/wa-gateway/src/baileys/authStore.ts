/** Baileys auth state backed by Redis (hot) — snapshot/restore via export/import.
 * Redis layout per session:
 *   wa:auth:{id}:creds  — AuthenticationCreds JSON (BufferJSON encoding)
 *   wa:auth:{id}:keys   — hash, field `${type}:${keyId}` → signal key JSON
 */
import { BufferJSON, initAuthCreds, proto } from '@whiskeysockets/baileys';
import type {
  AuthenticationCreds,
  AuthenticationState,
  SignalDataTypeMap,
} from '@whiskeysockets/baileys';
import type { Redis } from 'ioredis';

export interface LoadedAuthState {
  state: AuthenticationState;
  saveCreds: () => Promise<void>;
  /** True when creds already existed (restored session — no QR needed). */
  credsExisted: boolean;
}

interface ExportedAuthBlob {
  creds: string | null;
  keys: Record<string, string>;
}

export class RedisAuthStore {
  constructor(
    private readonly redis: Redis,
    private readonly sessionId: string,
  ) {}

  private get credsKey(): string {
    return `wa:auth:${this.sessionId}:creds`;
  }

  private get keysKey(): string {
    return `wa:auth:${this.sessionId}:keys`;
  }

  async hasCreds(): Promise<boolean> {
    return (await this.redis.exists(this.credsKey)) === 1;
  }

  async load(): Promise<LoadedAuthState> {
    const rawCreds = await this.redis.get(this.credsKey);
    const credsExisted = rawCreds !== null;
    const creds: AuthenticationCreds = rawCreds
      ? (JSON.parse(rawCreds, BufferJSON.reviver) as AuthenticationCreds)
      : initAuthCreds();

    const state: AuthenticationState = {
      creds,
      keys: {
        get: async <T extends keyof SignalDataTypeMap>(type: T, ids: string[]) => {
          const result: { [id: string]: SignalDataTypeMap[T] } = {};
          if (ids.length === 0) {
            return result;
          }
          const fields = ids.map((id) => `${type}:${id}`);
          const values = await this.redis.hmget(this.keysKey, ...fields);
          ids.forEach((id, i) => {
            const raw = values[i];
            if (!raw) {
              return;
            }
            let value = JSON.parse(raw, BufferJSON.reviver) as SignalDataTypeMap[T];
            if (type === 'app-state-sync-key') {
              value = proto.Message.AppStateSyncKeyData.fromObject(
                value,
              ) as unknown as SignalDataTypeMap[T];
            }
            result[id] = value;
          });
          return result;
        },
        set: async (data) => {
          const toSet: Record<string, string> = {};
          const toDelete: string[] = [];
          for (const [type, entries] of Object.entries(data)) {
            for (const [id, value] of Object.entries(entries)) {
              const field = `${type}:${id}`;
              if (value === null || value === undefined) {
                toDelete.push(field);
              } else {
                toSet[field] = JSON.stringify(value, BufferJSON.replacer);
              }
            }
          }
          if (Object.keys(toSet).length > 0) {
            await this.redis.hset(this.keysKey, toSet);
          }
          if (toDelete.length > 0) {
            await this.redis.hdel(this.keysKey, ...toDelete);
          }
        },
      },
    };

    const saveCreds = async (): Promise<void> => {
      await this.redis.set(this.credsKey, JSON.stringify(state.creds, BufferJSON.replacer));
    };

    return { state, saveCreds, credsExisted };
  }

  /** Plaintext JSON blob (creds + keys) — caller encrypts before persisting. */
  async export(): Promise<string> {
    const blob: ExportedAuthBlob = {
      creds: await this.redis.get(this.credsKey),
      keys: await this.redis.hgetall(this.keysKey),
    };
    return JSON.stringify(blob);
  }

  /** Hydrate Redis from a decrypted snapshot blob. */
  async import(json: string): Promise<void> {
    const blob = JSON.parse(json) as ExportedAuthBlob;
    if (blob.creds) {
      await this.redis.set(this.credsKey, blob.creds);
    }
    if (Object.keys(blob.keys).length > 0) {
      await this.redis.hset(this.keysKey, blob.keys);
    }
  }

  async clear(): Promise<void> {
    await this.redis.del(this.credsKey, this.keysKey);
  }
}
