/** Real Baileys socket factory. Version PINNED at 6.7.23 (root guide pitfall #3):
 * bumps happen deliberately, tested on canary numbers — never via semver range. */
import makeWASocket, { fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import type { GatewaySocket, SocketFactory } from './socket.js';

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
