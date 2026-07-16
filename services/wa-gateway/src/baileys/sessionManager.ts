import { EventEmitter } from 'node:events';
import type { Redis } from 'ioredis';
import type { Logger } from 'pino';
import { decrypt, encrypt } from '../crypto/secretbox.js';
import { makeEvent } from '../events/envelope.js';
import type { EventPublisher } from '../events/publisher.js';
import { logFields } from '../logger.js';
import { RedisAuthStore } from './authStore.js';
import { type MediaRef, type MediaStorage, extractMediaMeta, mediaKey } from './media.js';
import type { GatewaySocket, GroupMetadataLite, InboundMessage, SocketFactory } from './socket.js';

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
  /** Auto-restarts since the last successful 'open' (bounded — no crash loops). */
  restartCount: number;
}

// WhatsApp disconnect codes we act on (Boom statusCode from lastDisconnect).
const DISCONNECT_RESTART_REQUIRED = 515; // normal after QR pairing — MUST reconnect
const DISCONNECT_LOGGED_OUT = 401; // device unlinked — creds are dead
const MAX_AUTO_RESTARTS = 5;
const FAST_RESTART_DELAY_MS = 2_000;
export const SLOW_RESTART_DELAY_MS = 60_000;

/** '9199…:12@s.whatsapp.net' → '9199…' — device suffix and domain stripped so
 * our own jid can be matched against group participant ids. */
function bareJid(jid: string | null | undefined): string {
  return jid?.split('@')[0]?.split(':')[0] ?? '';
}

function disconnectCode(update: { lastDisconnect?: { error?: unknown } }): number | undefined {
  const error = update.lastDisconnect?.error as
    | { output?: { statusCode?: number } }
    | undefined;
  return error?.output?.statusCode;
}

export interface SessionManagerDeps {
  redis: Redis;
  snapshots: import('./snapshot.js').SnapshotStorage;
  /** AES-256-GCM key; undefined disables snapshots (bare dev). */
  snapshotKey: Buffer | undefined;
  factory: SocketFactory;
  publisher: EventPublisher;
  /** Object store for inbound WhatsApp media (P4.5 prerequisite). */
  mediaStorage: MediaStorage;
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
      restartCount: 0,
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
          session.restartCount = 0;
          // Phase 2: refresh the group registry on every (re)connect — the
          // consumer upserts idempotently, so re-syncs only heal drift.
          void this.syncGroups(session);
        }
        if (update.connection === 'close') {
          this.handleClose(session, disconnectCode(update));
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
        void this.handleInboundMessage(session, message);
      }
    });

    // Group registry (Phase 2): live metadata + membership updates.
    socket.onGroupsUpsert((groups) => {
      for (const group of groups) {
        void this.publishGroupUpsert(session, group);
      }
    });
    socket.onGroupsUpdate((updates) => {
      for (const update of updates) {
        if (!update.id) {
          continue;
        }
        void this.deps.publisher.publish(
          makeEvent({
            transport: 'baileys',
            type: 'group.update',
            workspace_hint: info.workspace,
            wa_chat_id: update.id,
            wa_message_id: null,
            payload: { session_id: info.id, update },
          }),
        );
      }
    });
    socket.onGroupParticipantsUpdate((update) => {
      void this.deps.publisher.publish(
        makeEvent({
          transport: 'baileys',
          type: 'group.participants',
          workspace_hint: info.workspace,
          wa_chat_id: update.id,
          wa_message_id: null,
          payload: { session_id: info.id, ...update },
        }),
      );
    });
  }

  /** Publish one inbound message. For media (image/video/voice/document/sticker)
   * we first download the bytes from WhatsApp's CDN and park them in the object
   * store, attaching a media ref to the payload so Frappe — which never touches
   * WhatsApp — can serve them to the SPA and transcribe voice notes (P4.5).
   * Download failures degrade gracefully: the metadata still ships with key=null. */
  private async handleInboundMessage(
    session: ManagedSession,
    message: InboundMessage,
  ): Promise<void> {
    const { socket, info } = session;
    const waMessageId = message.key.id ?? null;
    const meta = extractMediaMeta(message);
    let media: MediaRef | undefined;

    // Download inbound media only — outbound echoes are the team's own sends.
    if (meta && waMessageId && !message.key.fromMe) {
      const key = mediaKey(info.workspace, waMessageId);
      try {
        const bytes = await socket.downloadMedia(message);
        if (bytes) {
          await this.deps.mediaStorage.put(
            key,
            bytes,
            meta.mimetype ?? 'application/octet-stream',
          );
          media = { ...meta, key };
        } else {
          media = { ...meta, key: null }; // expired/undownloadable — metadata only
        }
      } catch (err: unknown) {
        this.deps.logger.warn(
          logFields({
            session_id: info.id,
            wa_message_id: waMessageId,
            media_type: meta.type,
            err_type: String(err),
          }),
          'inbound media download/store failed — publishing metadata only',
        );
        media = { ...meta, key: null };
      }
    } else if (meta) {
      media = { ...meta, key: null }; // outbound / id-less media — metadata only
    }

    await this.deps.publisher.publish(
      makeEvent({
        transport: 'baileys',
        type: 'message.received',
        workspace_hint: info.workspace,
        wa_chat_id: message.key.remoteJid ?? null,
        wa_message_id: waMessageId,
        payload: { session_id: info.id, message, ...(media ? { media } : {}) },
      }),
    );
  }

  /** Full registry sync — one groupFetchAllParticipating call covers subject,
   * description, owner, and participants for every group (exit target: 200
   * groups < 60s). Invite links are fetched only where we hold admin (the
   * server refuses otherwise); avatars are deferred to a later epic. */
  private async syncGroups(session: ManagedSession): Promise<void> {
    const { socket, info } = session;
    try {
      const groups = await socket.fetchAllGroups();
      for (const group of groups) {
        await this.publishGroupUpsert(session, group);
      }
      this.deps.logger.info(
        logFields({ session_id: info.id, group_count: groups.length }),
        'group registry synced',
      );
    } catch (err: unknown) {
      this.deps.logger.warn(
        logFields({ session_id: info.id, err_type: String(err) }),
        'group sync failed — will retry on next reconnect',
      );
    }
  }

  private async publishGroupUpsert(
    session: ManagedSession,
    group: GroupMetadataLite,
  ): Promise<void> {
    const { socket, info } = session;
    const me = bareJid(socket.ownJid());
    const weAreAdmin =
      me !== '' && group.participants.some((p) => bareJid(p.id) === me && p.admin);
    const inviteCode = weAreAdmin ? await socket.groupInviteCode(group.id) : null;
    await this.deps.publisher.publish(
      makeEvent({
        transport: 'baileys',
        type: 'group.upsert',
        workspace_hint: info.workspace,
        wa_chat_id: group.id,
        wa_message_id: null,
        payload: {
          session_id: info.id,
          group,
          owned_by_us: weAreAdmin,
          invite_code: inviteCode,
        },
      }),
    );
  }

  /** Baileys closes the stream mid-flow by design: after QR pairing succeeds the
   * server sends 515 (restart required) and the client MUST reconnect with the
   * saved creds to complete the link — without this the phone hangs on loading. */
  private handleClose(session: ManagedSession, code: number | undefined): void {
    const id = session.info.id;
    if (code === DISCONNECT_LOGGED_OUT) {
      this.deps.logger.info(logFields({ session_id: id }), 'device unlinked — creds cleared');
      void session.store.clear();
      return;
    }
    if (session.restartCount >= MAX_AUTO_RESTARTS) {
      // Fast lane exhausted (e.g. a network blip caused a 408 loop). Do NOT die:
      // keep trying on the slow lane — a paired session must survive transient
      // outages without human intervention (master doc: number safety).
      this.deps.logger.warn(
        logFields({ session_id: id, restart_count: session.restartCount }),
        'fast-lane restarts exhausted — retrying on slow lane',
      );
      this.scheduleRestart(session, SLOW_RESTART_DELAY_MS);
      return;
    }
    session.restartCount += 1;
    this.deps.logger.info(
      logFields({
        session_id: id,
        disconnect_code: code ?? null,
        restart_count: session.restartCount,
        restart_required: code === DISCONNECT_RESTART_REQUIRED,
      }),
      'auto-restarting baileys socket',
    );
    this.scheduleRestart(
      session,
      code === DISCONNECT_RESTART_REQUIRED ? 0 : FAST_RESTART_DELAY_MS,
    );
  }

  private scheduleRestart(session: ManagedSession, delayMs: number): void {
    const id = session.info.id;
    const restartCount = session.restartCount;
    const timer = setTimeout(() => {
      void (async () => {
        const current = this.sessions.get(id);
        if (!current || current !== session) {
          return; // destroyed or already replaced
        }
        current.socket.end();
        this.sessions.delete(id);
        const handle = await this.startSocket(id, session.info.workspace);
        const replacement = this.sessions.get(id);
        if (replacement) {
          replacement.restartCount = restartCount; // carry the bound across restarts
        }
        // Re-point existing emitter subscribers (SSE) at the new socket's events.
        handle.emitter.on('qr', (qr: string) => session.emitter.emit('qr', qr));
        handle.emitter.on('status', (status: string) => session.emitter.emit('status', status));
      })().catch((err: unknown) => {
        this.deps.logger.error(
          logFields({ session_id: id, err_type: String(err) }),
          'auto-restart failed',
        );
      });
    }, delayMs);
    timer.unref();
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

  // --- group actions (P2.3) — thin session-scoped wrappers; Baileys emits
  // groups.update / group-participants.update afterwards, which the live
  // listeners publish, so the registry heals itself without extra plumbing.

  private requireSocket(id: string): GatewaySocket {
    const session = this.sessions.get(id);
    if (!session) {
      throw new SessionNotFoundError(id);
    }
    return session.socket;
  }

  async groupParticipants(
    id: string,
    jid: string,
    participants: string[],
    action: 'add' | 'remove' | 'promote' | 'demote',
  ): Promise<void> {
    await this.requireSocket(id).groupParticipantsAction(jid, participants, action);
  }

  async groupUpdateMeta(
    id: string,
    jid: string,
    changes: { subject?: string; description?: string | null },
  ): Promise<void> {
    const socket = this.requireSocket(id);
    if (changes.subject !== undefined) {
      await socket.groupUpdateSubject(jid, changes.subject);
    }
    if (changes.description !== undefined) {
      await socket.groupUpdateDescription(jid, changes.description);
    }
  }

  async groupRevokeInvite(id: string, jid: string): Promise<string | null> {
    return this.requireSocket(id).groupRevokeInvite(jid);
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
