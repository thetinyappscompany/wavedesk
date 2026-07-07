import { EventEmitter } from 'node:events';
import type { AuthenticationState } from '@whiskeysockets/baileys';
import type {
  ConnectionUpdate,
  GatewaySocket,
  InboundMessage,
  SocketFactory,
} from '../../src/baileys/socket.js';

export interface MockSocket extends GatewaySocket {
  /** Test controls */
  emitConnection(update: ConnectionUpdate): void;
  emitMessages(messages: InboundMessage[]): void;
  emitCreds(): void;
  readonly sent: { jid: string; content: { text: string } }[];
  readonly hadCredsAtCreation: boolean;
  ended: boolean;
  loggedOut: boolean;
}

/** Mimics Baileys just enough for lifecycle tests: emits a QR only when the
 * auth state carries no registered creds (i.e. a fresh, never-paired session). */
export function makeMockSocketFactory(): {
  factory: SocketFactory;
  sockets: MockSocket[];
} {
  const sockets: MockSocket[] = [];

  const factory: SocketFactory = ({ state }) => {
    const em = new EventEmitter();
    // Baileys marks paired sessions via creds.registered / creds.me — our mock
    // treats a session with `me` set as previously paired.
    const hadCreds = Boolean(
      (state.creds as { me?: unknown; registered?: boolean }).me ??
        state.creds.registered,
    );

    const socket: MockSocket = {
      hadCredsAtCreation: hadCreds,
      sent: [],
      ended: false,
      loggedOut: false,
      onConnectionUpdate(cb) {
        em.on('connection.update', cb);
      },
      onCredsUpdate(cb) {
        em.on('creds.update', cb);
      },
      onMessagesUpsert(cb) {
        em.on('messages.upsert', cb);
      },
      sendMessage(jid, content) {
        this.sent.push({ jid, content });
        return Promise.resolve({ key: { id: `MOCK-${String(this.sent.length)}`, remoteJid: jid } });
      },
      end() {
        this.ended = true;
      },
      logout() {
        this.loggedOut = true;
        return Promise.resolve();
      },
      emitConnection(update) {
        em.emit('connection.update', update);
      },
      emitMessages(messages) {
        em.emit('messages.upsert', { messages, type: 'notify' });
      },
      emitCreds() {
        em.emit('creds.update');
      },
    };

    // Simulate the pairing dance asynchronously, like the real socket does.
    // Macrotask (not microtask): the real QR arrives over the network well after
    // create() resolves, so subscribers attached afterwards must still see it.
    setImmediate(() => {
      if (!hadCreds) {
        socket.emitConnection({ qr: 'mock-qr-payload' });
      }
      socket.emitConnection({ connection: 'open' });
    });

    sockets.push(socket);
    return socket;
  };

  return { factory, sockets };
}

/** Marks the auth state as "paired" the way a real QR scan would. */
export function simulatePairing(state: AuthenticationState): void {
  (state.creds as { me?: unknown }).me = { id: '919999900000:1@s.whatsapp.net' };
  state.creds.registered = true;
}
