import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen } from '@testing-library/react';
import { EventEmitter } from 'node:events';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useChatPresence, useWorkspaceEvents, type WdPresenceEvent } from './realtime';

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

  it('invalidates the chat list on wd:chat (assignment/status change)', () => {
    emitter.emit('wd:chat', { chat: 'CHAT-3' });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['chats'] });
  });
});

function PresenceProbe({ chat, me }: { chat: string; me: string | null }): React.JSX.Element {
  const others = useChatPresence(chat, me);
  return (
    <div data-testid="presence">
      {others.map((o) => `${o.fullName}:${o.state}`).join(',')}
    </div>
  );
}

describe('useChatPresence', () => {
  beforeEach(() => {
    emitter.removeAllListeners();
  });

  const emit = (event: Partial<WdPresenceEvent>): void => {
    act(() => {
      emitter.emit('wd:presence', {
        chat: 'CHAT-1',
        user: 'riya@x.test',
        full_name: 'Riya',
        state: 'viewing',
        ...event,
      });
    });
  };

  it('tracks other agents in the same chat, excluding self', () => {
    render(<PresenceProbe chat="CHAT-1" me="me@x.test" />);
    emit({});
    emit({ user: 'me@x.test', full_name: 'Me' });
    expect(screen.getByTestId('presence')).toHaveTextContent('Riya:viewing');
    expect(screen.getByTestId('presence')).not.toHaveTextContent('Me');
  });

  it('upgrades to typing and ignores other chats', () => {
    render(<PresenceProbe chat="CHAT-1" me={null} />);
    emit({ state: 'typing' });
    emit({ chat: 'CHAT-OTHER', user: 'sam@x.test', full_name: 'Sam' });
    expect(screen.getByTestId('presence')).toHaveTextContent('Riya:typing');
    expect(screen.getByTestId('presence')).not.toHaveTextContent('Sam');
  });
});
