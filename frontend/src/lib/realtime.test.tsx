import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { EventEmitter } from 'node:events';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useWorkspaceEvents } from './realtime';

const emitter = new EventEmitter();
vi.mock('socket.io-client', () => ({
  io: () => ({
    on: (event: string, cb: (...args: unknown[]) => void) => emitter.on(event, cb),
    off: (event: string, cb: (...args: unknown[]) => void) => emitter.off(event, cb),
  }),
}));

function Probe(): null {
  useWorkspaceEvents();
  return null;
}

describe('useWorkspaceEvents', () => {
  let queryClient: QueryClient;
  let invalidate: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    emitter.removeAllListeners();
    queryClient = new QueryClient();
    invalidate = vi.fn();
    queryClient.invalidateQueries = invalidate as typeof queryClient.invalidateQueries;
    render(
      <QueryClientProvider client={queryClient}>
        <Probe />
      </QueryClientProvider>,
    );
  });

  it('invalidates chats + the chat thread on wd:message', () => {
    emitter.emit('wd:message', { chat: 'CHAT-7', message: 'M1', direction: 'in' });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['chats'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['messages', 'CHAT-7'] });
  });

  it('invalidates the chat thread on wd:message_status', () => {
    emitter.emit('wd:message_status', { chat: 'CHAT-9', message: 'M2', status: 'sent' });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['messages', 'CHAT-9'] });
  });
});
