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

export interface GatewaySocket {
  onConnectionUpdate(cb: (update: ConnectionUpdate) => void): void;
  onCredsUpdate(cb: () => void): void;
  onMessagesUpsert(cb: (upsert: { messages: InboundMessage[]; type: string }) => void): void;
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
