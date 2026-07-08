import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { io, type Socket } from 'socket.io-client';

/** Frappe's socketio (same-origin /socket.io, session-cookie auth via the
 * dev proxy / nginx). Events arrive on the logged-in user's room — the server
 * fans out per workspace member (wavedesk/realtime.py). */
let socket: Socket | null = null;

export function getSocket(): Socket {
  socket ??= io({ path: '/socket.io', withCredentials: true, transports: ['websocket', 'polling'] });
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
    sock.on('wd:message', onMessage);
    sock.on('wd:message_status', onStatus);
    return () => {
      sock.off('wd:message', onMessage);
      sock.off('wd:message_status', onStatus);
    };
  }, [queryClient]);
}
