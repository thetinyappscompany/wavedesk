import { useEffect, useRef, useState } from 'react';
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';
import { AlertCircle, Check, CheckCheck, Clock, RotateCcw, SendHorizontal } from 'lucide-react';
import type { WdMessage } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const MEDIA_LABEL: Record<string, string> = {
  image: '📷 Photo',
  video: '🎬 Video',
  audio: '🎙 Voice message',
  document: '📄 Document',
  sticker: 'Sticker',
  location: '📍 Location',
  contact_card: '👤 Contact card',
  reaction: 'Reaction',
  system: 'System message',
};

function StatusTicks({ status }: { status: WdMessage['status'] }): React.JSX.Element | null {
  switch (status) {
    case 'queued':
      return <Clock aria-label="queued" className="h-3.5 w-3.5" />;
    case 'sent':
      return <Check aria-label="sent" className="h-3.5 w-3.5" />;
    case 'delivered':
      return <CheckCheck aria-label="delivered" className="h-3.5 w-3.5" />;
    case 'read':
      return <CheckCheck aria-label="read" className="h-3.5 w-3.5 text-sky-500" />;
    case 'failed':
      return <AlertCircle aria-label="failed" className="h-3.5 w-3.5 text-destructive" />;
    default:
      return null;
  }
}

function timeLabel(creation: string): string {
  const date = new Date(creation.replace(' ', 'T'));
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function Bubble({
  message,
  onRetry,
}: {
  message: WdMessage;
  onRetry: (name: string) => void;
}): React.JSX.Element {
  const outbound = message.direction === 'out';
  return (
    <div
      data-testid="message-bubble"
      data-direction={message.direction}
      className={cn('flex w-full', outbound ? 'justify-end' : 'justify-start')}
    >
      <div
        className={cn(
          'max-w-[70%] rounded-lg px-3 py-2 text-sm shadow-sm',
          outbound ? 'bg-primary/15' : 'bg-muted',
        )}
      >
        {message.quoted_body && (
          <div className="mb-1 rounded border-l-2 border-primary/60 bg-background/60 px-2 py-1 text-xs text-muted-foreground">
            {message.quoted_body}
          </div>
        )}
        {message.message_type === 'text' ? (
          <p className="whitespace-pre-wrap break-words">{message.body}</p>
        ) : (
          <p className="italic text-muted-foreground">
            {MEDIA_LABEL[message.message_type] ?? message.message_type}
            {message.body ? ` — ${message.body}` : ''}
            <span className="block text-xs">(media preview lands with the media pipeline)</span>
          </p>
        )}
        <div className="mt-1 flex items-center justify-end gap-1 text-xs text-muted-foreground">
          <span>{timeLabel(message.creation)}</span>
          {outbound && <StatusTicks status={message.status} />}
          {outbound && message.status === 'failed' && (
            <button
              type="button"
              aria-label="Retry send"
              className="ml-1 rounded p-0.5 text-destructive hover:bg-destructive/10"
              onClick={() => {
                onRetry(message.name);
              }}
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ConversationPane({
  chatName,
  title,
}: {
  chatName: string;
  title: string;
}): React.JSX.Element {
  const queryClient = useQueryClient();

  const messages = useInfiniteQuery({
    queryKey: ['messages', chatName],
    queryFn: ({ pageParam }) => client.listMessages(chatName, pageParam ?? undefined),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => (lastPage.has_more ? lastPage.next_before : null),
    placeholderData: keepPreviousData,
    refetchInterval: 5000, // polling until the realtime epic (P1.6)
  });

  const [draft, setDraft] = useState('');
  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['messages', chatName] });
    void queryClient.invalidateQueries({ queryKey: ['chats'] });
  };

  const send = useMutation({
    mutationFn: (body: string) => client.sendMessage(chatName, body),
    onSuccess: refresh,
  });
  const retry = useMutation({
    mutationFn: (name: string) => client.retryMessage(name),
    onSuccess: refresh,
  });

  const submit = (): void => {
    const body = draft.trim();
    if (!body || send.isPending) {
      return;
    }
    setDraft('');
    send.mutate(body);
  };

  const markRead = useMutation({
    mutationFn: () => client.markChatRead(chatName),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['chats'] }),
  });
  const markReadMutate = markRead.mutate;
  useEffect(() => {
    markReadMutate();
  }, [chatName, markReadMutate]);

  // Pages arrive newest-first; each page's messages are ascending.
  const ordered: WdMessage[] = [...(messages.data?.pages ?? [])]
    .reverse()
    .flatMap((page) => page.messages);

  const bottomRef = useRef<HTMLDivElement>(null);
  const lastMessage = ordered.at(-1)?.name;
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [lastMessage, chatName]);

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <header className="border-b px-4 py-3">
        <h2 className="font-semibold">{title}</h2>
      </header>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-4" data-testid="message-scroll">
        {messages.hasNextPage && (
          <div className="flex justify-center">
            <Button
              variant="outline"
              size="sm"
              disabled={messages.isFetchingNextPage}
              onClick={() => void messages.fetchNextPage()}
            >
              {messages.isFetchingNextPage ? 'Loading…' : 'Load earlier messages'}
            </Button>
          </div>
        )}
        {messages.isLoading && (
          <p className="text-center text-sm text-muted-foreground">Loading conversation…</p>
        )}
        {messages.isError && (
          <p role="alert" className="text-center text-sm text-destructive">
            Failed to load messages.
          </p>
        )}
        {ordered.map((message) => (
          <Bubble key={message.name} message={message} onRetry={(name) => retry.mutate(name)} />
        ))}
        <div ref={bottomRef} />
      </div>

      <footer className="border-t p-3">
        <div className="flex items-end gap-2">
          <textarea
            aria-label="Message"
            placeholder="Type a message… (Enter to send, Shift+Enter for a new line)"
            value={draft}
            rows={Math.min(draft.split('\n').length, 5)}
            onChange={(e) => {
              setDraft(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            className="min-h-9 flex-1 resize-none rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          <Button
            aria-label="Send"
            size="icon"
            disabled={!draft.trim() || send.isPending}
            onClick={submit}
          >
            <SendHorizontal className="h-4 w-4" />
          </Button>
        </div>
        {send.isError && (
          <p role="alert" className="mt-1 text-xs text-destructive">
            Send failed — {send.error.message}
          </p>
        )}
      </footer>
    </div>
  );
}
