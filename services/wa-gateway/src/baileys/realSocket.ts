/** Real Baileys socket factory. Version PINNED at 6.7.23 (root guide pitfall #3):
 * bumps happen deliberately, tested on canary numbers — never via semver range. */
import makeWASocket from '@whiskeysockets/baileys';
import type { GatewaySocket, SocketFactory } from './socket.js';

export const realSocketFactory: SocketFactory = ({ state }) => {
  const sock = makeWASocket({
    auth: state,
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
