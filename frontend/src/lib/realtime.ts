import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { io, type Socket } from 'socket.io-client';

/** Frappe's socketio (same-origin /socket.io, session-cookie auth via the
 * dev proxy / nginx). Events arrive on the logged-in user's room — the server
 * fans out per workspace member (wavedesk/realtime.py). */
let socket: Socket | null = null;

/** Frappe's realtime server namespaces sockets BY SITE and only routes events
 * into `/<site>` — a root-namespace connection is silently event-less. Mirror
 * the server's site resolution (realtime/middlewares/authenticate.js):
 * localhost → default_site, anything else → the host itself. */
function siteNamespace(): string {
  const host = window.location.hostname;
  if (host === 'localhost' || host === '127.0.0.1') {
    return (import.meta.env.VITE_FRAPPE_SITE as string | undefined) ?? 'dev.localhost';
  }
  return host;
}

export function getSocket(): Socket {
  socket ??= io(`/${siteNamespace()}`, {
    path: '/socket.io',
    withCredentials: true,
    transports: ['websocket', 'polling'],
  });
  return socket;
}

interface WdMessageEvent {
  chat: string;
  message: string;
  direction: 'in' | 'out';
}

interface WdStatusEvent {
  chat: string;
  message: string;
  status: string;
}

interface WdChatEvent {
  chat: string;
}

export interface WdPresenceEvent {
  chat: string;
  user: string;
  full_name: string;
  state: 'viewing' | 'typing';
}

/** Live cache invalidation: 'No refresh, ever' (master doc Phase 1 feature 2). */
export function useWorkspaceEvents(): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    const sock = getSocket();
    const onMessage = (event: WdMessageEvent): void => {
      void queryClient.invalidateQueries({ queryKey: ['chats'] });
      void queryClient.invalidateQueries({ queryKey: ['messages', event.chat] });
    };
    const onStatus = (event: WdStatusEvent): void => {
      void queryClient.invalidateQueries({ queryKey: ['messages', event.chat] });
    };
    const onChat = (event: WdChatEvent): void => {
      void event;
      void queryClient.invalidateQueries({ queryKey: ['chats'] });
    };
    const onGroup = (): void => {
      // registry changed — subjects surface in the chat list too
      void queryClient.invalidateQueries({ queryKey: ['groups'] });
      void queryClient.invalidateQueries({ queryKey: ['chats'] });
    };
    const onAlert = (): void => {
      void queryClient.invalidateQueries({ queryKey: ['alerts'] });
    };
    const onTicket = (): void => {
      void queryClient.invalidateQueries({ queryKey: ['tickets'] });
    };
    sock.on('wd:message', onMessage);
    sock.on('wd:message_status', onStatus);
    sock.on('wd:chat', onChat);
    sock.on('wd:group', onGroup);
    sock.on('wd:alert', onAlert);
    sock.on('wd:ticket', onTicket);
    return () => {
      sock.off('wd:message', onMessage);
      sock.off('wd:message_status', onStatus);
      sock.off('wd:chat', onChat);
      sock.off('wd:group', onGroup);
      sock.off('wd:alert', onAlert);
      sock.off('wd:ticket', onTicket);
    };
  }, [queryClient]);
}

/** How long a presence signal stays visible without a fresh ping.
 * Server heartbeats every 10s with a 15s Redis TTL — match that. */
const PRESENCE_STALE_MS = 15_000;

interface PresenceEntry {
  fullName: string;
  state: 'viewing' | 'typing';
  at: number;
}

/** Other agents' live presence in one chat ("Riya is typing…").
 * excludeUser filters out the current agent's own heartbeats. */
export function useChatPresence(
  chat: string,
  excludeUser: string | null,
): { fullName: string; state: 'viewing' | 'typing' }[] {
  const [entries, setEntries] = useState<Record<string, PresenceEntry>>({});

  useEffect(() => {
    setEntries({});
    const sock = getSocket();
    const onPresence = (event: WdPresenceEvent): void => {
      if (event.chat !== chat) {
        return;
      }
      setEntries((prev) => ({
        ...prev,
        [event.user]: { fullName: event.full_name, state: event.state, at: Date.now() },
      }));
    };
    const prune = setInterval(() => {
      setEntries((prev) => {
        const cutoff = Date.now() - PRESENCE_STALE_MS;
        const fresh = Object.fromEntries(
          Object.entries(prev).filter(([, entry]) => entry.at >= cutoff),
        );
        return Object.keys(fresh).length === Object.keys(prev).length ? prev : fresh;
      });
    }, 5_000);
    sock.on('wd:presence', onPresence);
    return () => {
      sock.off('wd:presence', onPresence);
      clearInterval(prune);
    };
  }, [chat]);

  return Object.entries(entries)
    .filter(([user]) => user !== excludeUser)
    .map(([, entry]) => ({ fullName: entry.fullName, state: entry.state }));
}
