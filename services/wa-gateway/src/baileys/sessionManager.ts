import { EventEmitter } from 'node:events';
import type { Redis } from 'ioredis';
import type { Logger } from 'pino';
import { decrypt, encrypt } from '../crypto/secretbox.js';
import { makeEvent } from '../events/envelope.js';
import type { EventPublisher } from '../events/publisher.js';
import { logFields } from '../logger.js';
import { RedisAuthStore } from './authStore.js';
import type { GatewaySocket, SocketFactory } from './socket.js';

export type SessionStatus = 'connecting' | 'connected' | 'disconnected';

export interface SessionInfo {
  id: string;
  workspace: string;
  status: SessionStatus;
  transport: 'baileys';
}

export interface SessionHandle {
  info: SessionInfo;
  /** Emits 'qr' (raw QR string) and 'status' (SessionStatus). */
  emitter: EventEmitter;
  /** True when the session came up from persisted creds (no QR scan needed). */
  credsExisted: boolean;
  /** Latest QR payload while pairing (null once connected) — enables polling
   * via Frappe, since the SPA never talks to the gateway directly. */
  lastQr: string | null;
}

interface ManagedSession {
  info: SessionInfo;
  emitter: EventEmitter;
  socket: GatewaySocket;
  store: RedisAuthStore;
  credsExisted: boolean;
  lastQr: string | null;
}

export interface SessionManagerDeps {
  redis: Redis;
  snapshots: import('./snapshot.js').SnapshotStorage;
  /** AES-256-GCM key; undefined disables snapshots (bare dev). */
  snapshotKey: Buffer | undefined;
  factory: SocketFactory;
  publisher: EventPublisher;
  logger: Logger;
  snapshotIntervalMs: number;
}

const REGISTRY_KEY = 'wa:sessions';

/** One manager per gateway process; owns N Baileys sessions (master doc §2.2). */
export class SessionManager {
  private readonly sessions = new Map<string, ManagedSession>();
  private timer: NodeJS.Timeout | undefined;

  constructor(private readonly deps: SessionManagerDeps) {}

  async create(id: string, workspace: string): Promise<SessionHandle> {
    if (this.sessions.has(id)) {
      throw new SessionExistsError(id);
    }
    await this.deps.redis.hset(REGISTRY_KEY, id, JSON.stringify({ workspace }));
    return this.startSocket(id, workspace);
  }

  /** Boot-time restore: re-attach every registered session without QR re-scan. */
  async restoreAll(): Promise<SessionHandle[]> {
    const registry = await this.deps.redis.hgetall(REGISTRY_KEY);
    const handles: SessionHandle[] = [];
    for (const [id, rawMeta] of Object.entries(registry)) {
      if (this.sessions.has(id)) {
        continue;
      }
      const meta = JSON.parse(rawMeta) as { workspace: string };
      handles.push(await this.startSocket(id, meta.workspace));
    }
    return handles;
  }

  private async startSocket(id: string, workspace: string): Promise<SessionHandle> {
    const store = new RedisAuthStore(this.deps.redis, id);

    // Redis lost the hot state (e.g. eviction/new pod)? Restore from the
    // encrypted S3 snapshot before creating the socket.
    if (!(await store.hasCreds()) && this.deps.snapshotKey) {
      const blob = await this.deps.snapshots.get(id);
      if (blob) {
        await store.import(decrypt(blob, this.deps.snapshotKey));
        this.deps.logger.info(
          logFields({ session_id: id }),
          'session auth restored from encrypted snapshot',
        );
      }
    }

    const { state, saveCreds, credsExisted } = await store.load();
    const socket = await this.deps.factory({ sessionId: id, state });
    const emitter = new EventEmitter();
    const session: ManagedSession = {
      info: { id, workspace, status: 'connecting', transport: 'baileys' },
      emitter,
      socket,
      store,
      credsExisted,
      lastQr: null,
    };
    this.sessions.set(id, session);
    this.wire(session, saveCreds);
    this.deps.logger.info(
      logFields({ session_id: id, workspace, restored: credsExisted }),
      'baileys session started',
    );
    return this.toHandle(session);
  }

  private toHandle(session: ManagedSession): SessionHandle {
    return {
      info: session.info,
      emitter: session.emitter,
      credsExisted: session.credsExisted,
      lastQr: session.lastQr,
    };
  }

  private wire(session: ManagedSession, saveCreds: () => Promise<void>): void {
    const { socket, emitter, info } = session;

    socket.onCredsUpdate(() => {
      void saveCreds().catch((err: unknown) => {
        this.deps.logger.error(
          logFields({ session_id: info.id, err_type: String(err) }),
          'failed to persist creds',
        );
      });
    });

    socket.onConnectionUpdate((update) => {
      if (update.qr) {
        info.status = 'connecting';
        session.lastQr = update.qr;
        emitter.emit('qr', update.qr);
      }
      if (update.connection) {
        info.status =
          update.connection === 'open'
            ? 'connected'
            : update.connection === 'close'
              ? 'disconnected'
              : 'connecting';
        if (info.status === 'connected') {
          session.lastQr = null; // paired — QR is spent
        }
        emitter.emit('status', info.status);
        void this.deps.publisher.publish(
          makeEvent({
            transport: 'baileys',
            type: 'session.status',
            workspace_hint: info.workspace,
            wa_chat_id: null,
            wa_message_id: null,
            payload: { session_id: info.id, status: info.status },
          }),
        );
      }
    });

    socket.onMessagesUpsert(({ messages }) => {
      for (const message of messages) {
        void this.deps.publisher.publish(
          makeEvent({
            transport: 'baileys',
            type: 'message.received',
            workspace_hint: info.workspace,
            wa_chat_id: message.key.remoteJid ?? null,
            wa_message_id: message.key.id ?? null,
            payload: { session_id: info.id, message },
          }),
        );
      }
    });
  }

  list(): SessionInfo[] {
    return [...this.sessions.values()].map((s) => s.info);
  }

  get(id: string): SessionHandle | undefined {
    const session = this.sessions.get(id);
    if (!session) {
      return undefined;
    }
    return this.toHandle(session);
  }

  /** Disconnect the socket but KEEP auth state — reconnect() resumes without QR. */
  disconnect(id: string): boolean {
    const session = this.sessions.get(id);
    if (!session) {
      return false;
    }
    session.socket.end();
    session.info.status = 'disconnected';
    session.lastQr = null;
    session.emitter.emit('status', 'disconnected');
    return true;
  }

  /** Re-attach a disconnected session from persisted creds (no QR re-scan). */
  async reconnect(id: string): Promise<SessionHandle> {
    const session = this.sessions.get(id);
    if (!session) {
      throw new SessionNotFoundError(id);
    }
    const workspace = session.info.workspace;
    session.socket.end();
    this.sessions.delete(id);
    return this.startSocket(id, workspace);
  }

  async sendText(
    id: string,
    to: string,
    text: string,
  ): Promise<{ wa_message_id: string | null }> {
    const session = this.sessions.get(id);
    if (!session) {
      throw new SessionNotFoundError(id);
    }
    const jid = to.includes('@') ? to : `${to.replace(/[^0-9]/g, '')}@s.whatsapp.net`;
    const result = await session.socket.sendMessage(jid, { text });
    return { wa_message_id: result?.key.id ?? null };
  }

  /** DELETE = disconnect AND forget: auth state + snapshot removed. */
  async destroy(id: string): Promise<boolean> {
    const session = this.sessions.get(id);
    if (!session) {
      return false;
    }
    try {
      await session.socket.logout();
    } catch {
      // already disconnected — proceed with cleanup
    }
    session.socket.end();
    await session.store.clear();
    await this.deps.snapshots.remove(id).catch(() => undefined);
    await this.deps.redis.hdel(REGISTRY_KEY, id);
    this.sessions.delete(id);
    this.deps.logger.info(logFields({ session_id: id }), 'baileys session destroyed');
    return true;
  }

  /** Encrypted snapshot of every session's auth state → S3 (every 5 min + shutdown). */
  async snapshotAll(): Promise<number> {
    if (!this.deps.snapshotKey) {
      return 0;
    }
    let count = 0;
    for (const session of this.sessions.values()) {
      const blob = await session.store.export();
      await this.deps.snapshots.put(session.info.id, encrypt(blob, this.deps.snapshotKey));
      count += 1;
    }
    return count;
  }

  startSnapshotTimer(): void {
    if (this.timer) {
      return;
    }
    this.timer = setInterval(() => {
      void this.snapshotAll().catch((err: unknown) => {
        this.deps.logger.error(
          logFields({ err_type: String(err) }),
          'periodic session snapshot failed',
        );
      });
    }, this.deps.snapshotIntervalMs);
    this.timer.unref();
  }

  /** Graceful shutdown: snapshot, close sockets, KEEP auth (restart = no re-scan). */
  async shutdown(): Promise<void> {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = undefined;
    }
    await this.snapshotAll();
    for (const session of this.sessions.values()) {
      session.socket.end();
    }
    this.sessions.clear();
  }
}

export class SessionExistsError extends Error {
  constructor(id: string) {
    super(`session ${id} already exists`);
    this.name = 'SessionExistsError';
  }
}

export class SessionNotFoundError extends Error {
  constructor(id: string) {
    super(`session ${id} not found`);
    this.name = 'SessionNotFoundError';
  }
}
