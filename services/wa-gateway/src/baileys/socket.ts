/** Narrow socket abstraction over Baileys — everything the gateway uses,
 * injectable so tests run against a mock (per Session 0.6 acceptance). */
import type { AuthenticationState } from '@whiskeysockets/baileys';

export interface ConnectionUpdate {
  connection?: 'close' | 'open' | 'connecting';
  qr?: string;
  lastDisconnect?: { error?: unknown };
}

export interface InboundMessage {
  key: { remoteJid?: string | null; id?: string | null; fromMe?: boolean | null };
  message?: unknown;
  pushName?: string | null;
  messageTimestamp?: number | bigint | null;
}

export interface GroupParticipant {
  id: string;
  admin?: 'admin' | 'superadmin' | null;
}

export interface GroupMetadataLite {
  id: string;
  subject: string;
  desc?: string | null;
  owner?: string | null;
  participants: GroupParticipant[];
}

/** Baileys `groups.update` delivers partial metadata patches. */
export interface GroupUpdateEntry {
  id?: string;
  subject?: string;
  desc?: string | null;
}

export interface GroupParticipantsUpdate {
  id: string;
  participants: string[];
  action: 'add' | 'remove' | 'promote' | 'demote';
}

export interface GatewaySocket {
  onConnectionUpdate(cb: (update: ConnectionUpdate) => void): void;
  onCredsUpdate(cb: () => void): void;
  onMessagesUpsert(cb: (upsert: { messages: InboundMessage[]; type: string }) => void): void;
  onGroupsUpsert(cb: (groups: GroupMetadataLite[]) => void): void;
  onGroupsUpdate(cb: (updates: GroupUpdateEntry[]) => void): void;
  onGroupParticipantsUpdate(cb: (update: GroupParticipantsUpdate) => void): void;
  /** One-call snapshot of every group this number participates in. */
  fetchAllGroups(): Promise<GroupMetadataLite[]>;
  /** Invite code — null when the server refuses (we are not an admin). */
  groupInviteCode(jid: string): Promise<string | null>;
  /** Group actions (P2.3) — require admin; the server rejects otherwise. */
  groupParticipantsAction(
    jid: string,
    participants: string[],
    action: GroupParticipantsUpdate['action'],
  ): Promise<void>;
  groupUpdateSubject(jid: string, subject: string): Promise<void>;
  groupUpdateDescription(jid: string, description: string | null): Promise<void>;
  /** Revoke the current invite link; resolves to the NEW code. */
  groupRevokeInvite(jid: string): Promise<string | null>;
  /** Our own jid once paired (device suffix included), else null. */
  ownJid(): string | null;
  /** Download an inbound media message's bytes from WhatsApp's CDN, or null if
   * it carries no media / the download fails. */
  downloadMedia(message: InboundMessage): Promise<Buffer | null>;
  sendMessage(
    jid: string,
    content: { text: string },
  ): Promise<{ key: { id?: string | null; remoteJid?: string | null } } | undefined>;
  end(): void;
  logout(): Promise<void>;
}

export interface SocketFactoryOptions {
  sessionId: string;
  state: AuthenticationState;
}

export type SocketFactory = (
  options: SocketFactoryOptions,
) => GatewaySocket | Promise<GatewaySocket>;
