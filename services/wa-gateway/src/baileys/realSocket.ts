/** Real Baileys socket factory. Version PINNED at 6.7.23 (root guide pitfall #3):
 * bumps happen deliberately, tested on canary numbers — never via semver range. */
import makeWASocket, {
  downloadMediaMessage,
  fetchLatestBaileysVersion,
} from '@whiskeysockets/baileys';
import type { WAMessage } from '@whiskeysockets/baileys';
import { createLogger } from '../logger.js';
import type { GatewaySocket, GroupMetadataLite, InboundMessage, SocketFactory } from './socket.js';

// Baileys' media downloader wants a pino-like logger; reuse our redacting one.
const mediaLogger = createLogger(process.env.LOG_LEVEL ?? 'info');

type WaVersion = [number, number, number];

// WhatsApp rejects registrations that advertise a stale web-client version
// ("Connection Failure" right after hello). Fetch the current version once per
// process; fall back to the library default if the lookup fails offline.
let versionPromise: Promise<WaVersion | undefined> | undefined;

function currentWaVersion(): Promise<WaVersion | undefined> {
  versionPromise ??= fetchLatestBaileysVersion()
    .then((result): WaVersion => result.version)
    .catch(() => undefined);
  return versionPromise;
}

interface BaileysGroupMetadata {
  id: string;
  subject: string;
  desc?: string | null | undefined;
  owner?: string | null | undefined;
  participants?: { id: string; admin?: 'admin' | 'superadmin' | null | undefined }[];
}

function toGroupLite(group: BaileysGroupMetadata): GroupMetadataLite {
  return {
    id: group.id,
    subject: group.subject,
    desc: group.desc ?? null,
    owner: group.owner ?? null,
    participants: (group.participants ?? []).map((p) => ({
      id: p.id,
      admin: p.admin ?? null,
    })),
  };
}

export const realSocketFactory: SocketFactory = async ({ state }) => {
  const version = await currentWaVersion();
  const sock = makeWASocket({
    auth: state,
    ...(version ? { version } : {}),
    printQRInTerminal: false,
    syncFullHistory: false,
  });

  const adapter: GatewaySocket = {
    onConnectionUpdate(cb) {
      sock.ev.on('connection.update', (update) => {
        cb(update);
      });
    },
    onCredsUpdate(cb) {
      sock.ev.on('creds.update', cb);
    },
    onMessagesUpsert(cb) {
      sock.ev.on('messages.upsert', (upsert) => {
        cb(upsert as unknown as Parameters<typeof cb>[0]);
      });
    },
    onGroupsUpsert(cb) {
      sock.ev.on('groups.upsert', (groups) => {
        cb(groups.map(toGroupLite));
      });
    },
    onGroupsUpdate(cb) {
      sock.ev.on('groups.update', (updates) => {
        cb(
          updates.map((u) => ({
            ...(u.id !== undefined ? { id: u.id } : {}),
            ...(u.subject !== undefined ? { subject: u.subject } : {}),
            ...(u.desc !== undefined ? { desc: u.desc ?? null } : {}),
          })),
        );
      });
    },
    onGroupParticipantsUpdate(cb) {
      sock.ev.on('group-participants.update', (update) => {
        cb(update as unknown as Parameters<typeof cb>[0]);
      });
    },
    async fetchAllGroups() {
      const groups = await sock.groupFetchAllParticipating();
      return Object.values(groups).map(toGroupLite);
    },
    async groupInviteCode(jid) {
      try {
        return (await sock.groupInviteCode(jid)) ?? null;
      } catch {
        return null; // not an admin of this group — the server refuses
      }
    },
    ownJid() {
      return sock.user?.id ?? null;
    },
    async downloadMedia(message: InboundMessage) {
      try {
        const buffer = await downloadMediaMessage(
          message as unknown as WAMessage,
          'buffer',
          {},
          // reuploadRequest lets Baileys re-fetch media that aged out of the CDN.
          { logger: mediaLogger, reuploadRequest: sock.updateMediaMessage },
        );
        return buffer;
      } catch {
        return null; // expired media / non-media / decrypt failure — caller ships metadata only
      }
    },
    async groupParticipantsAction(jid, participants, action) {
      await sock.groupParticipantsUpdate(jid, participants, action);
    },
    async groupUpdateSubject(jid, subject) {
      await sock.groupUpdateSubject(jid, subject);
    },
    async groupUpdateDescription(jid, description) {
      await sock.groupUpdateDescription(jid, description ?? undefined);
    },
    async groupRevokeInvite(jid) {
      return (await sock.groupRevokeInvite(jid)) ?? null;
    },
    async sendMessage(jid, content) {
      const result = await sock.sendMessage(jid, content);
      return result ?? undefined;
    },
    end() {
      sock.end(undefined);
    },
    async logout() {
      await sock.logout();
    },
  };
  return adapter;
};
