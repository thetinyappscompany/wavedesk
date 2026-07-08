import { useEffect, useRef, useState } from 'react';
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCheck,
  Clock,
  RotateCcw,
  SendHorizontal,
  Tag,
  UserRound,
} from 'lucide-react';
import type { WdCannedResponse, WdChat, WdMessage } from '@wavedesk/api-client';
import { substituteVariables } from '@/lib/canned';
import { client } from '@/lib/client';
import { useChatPresence } from '@/lib/realtime';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/** Snooze presets keep Phase 1 free of a datetime picker. */
const SNOOZE_PRESETS = [
  { key: '1h', label: 'Snooze 1 hour', hours: 1 },
  { key: '4h', label: 'Snooze 4 hours', hours: 4 },
  { key: '24h', label: 'Snooze until tomorrow', hours: 24 },
] as const;

/** Frappe expects 'YYYY-MM-DD HH:mm:ss' (site-local clock). */
function frappeDatetime(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, '0');
  return (
    `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
}

const PRESENCE_HEARTBEAT_MS = 10_000;
const TYPING_PING_MIN_GAP_MS = 4_000;

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
  showSender,
  onRetry,
}: {
  message: WdMessage;
  /** Group chats show who sent each inbound message (P2.2). */
  showSender?: boolean;
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
        {showSender && !outbound && message.sender_display && (
          <p data-testid="sender-name" className="mb-0.5 text-xs font-medium text-primary">
            {message.sender_display}
          </p>
        )}
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

function LabelPicker({
  chatName,
  chat,
}: {
  chatName: string;
  chat: WdChat | undefined;
}): React.JSX.Element {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const labels = useQuery({
    queryKey: ['labels'],
    queryFn: () => client.listLabels(),
    enabled: open,
  });
  const applied = (chat?.labels ?? []).map((chip) => chip.label);
  const setLabels = useMutation({
    mutationFn: (next: string[]) => client.setChatLabels(chatName, next),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['chats'] });
    },
  });
  const toggle = (name: string): void => {
    const next = applied.includes(name)
      ? applied.filter((item) => item !== name)
      : [...applied, name];
    setLabels.mutate(next);
  };

  return (
    <div className="relative">
      <Button
        aria-label="Labels"
        variant="outline"
        size="icon"
        className="h-8 w-8"
        onClick={() => {
          setOpen((value) => !value);
        }}
      >
        <Tag className="h-4 w-4" />
      </Button>
      {open && (
        <div
          role="menu"
          aria-label="Chat labels"
          className="absolute right-0 top-9 z-20 w-52 rounded-md border bg-background p-1 shadow-md"
        >
          {labels.isLoading && (
            <p className="px-2 py-1.5 text-xs text-muted-foreground">Loading labels…</p>
          )}
          {labels.data?.length === 0 && (
            <p className="px-2 py-1.5 text-xs text-muted-foreground">
              No labels yet — create them in Settings.
            </p>
          )}
          {(labels.data ?? []).map((label) => (
            <label
              key={label.name}
              className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent"
            >
              <input
                type="checkbox"
                checked={applied.includes(label.name)}
                onChange={() => {
                  toggle(label.name);
                }}
              />
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: label.color }}
              />
              <span className="truncate">{label.title}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function HeaderControls({
  chatName,
  chat,
}: {
  chatName: string;
  chat: WdChat | undefined;
}): React.JSX.Element {
  const queryClient = useQueryClient();
  const members = useQuery({ queryKey: ['members'], queryFn: () => client.listMembers() });
  const refreshChats = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['chats'] });
  };
  const assign = useMutation({
    mutationFn: (agent: string | null) => client.assignChat(chatName, agent),
    onSuccess: refreshChats,
  });
  const setStatus = useMutation({
    mutationFn: (change: { status: WdChat['status']; snoozedUntil?: string }) =>
      client.setChatStatus(chatName, change.status, change.snoozedUntil),
    onSuccess: refreshChats,
  });

  const status = chat?.status ?? 'open';
  const onStatusChange = (value: string): void => {
    const preset = SNOOZE_PRESETS.find((p) => `snooze-${p.key}` === value);
    if (preset) {
      const until = new Date(Date.now() + preset.hours * 3_600_000);
      setStatus.mutate({ status: 'snoozed', snoozedUntil: frappeDatetime(until) });
      return;
    }
    setStatus.mutate({ status: value as WdChat['status'] });
  };

  return (
    <div className="flex items-center gap-2">
      <select
        aria-label="Assignee"
        className="h-8 rounded-md border border-input bg-transparent px-2 text-xs"
        value={chat?.assigned_agent ?? ''}
        onChange={(e) => {
          assign.mutate(e.target.value || null);
        }}
      >
        <option value="">Unassigned</option>
        {(members.data ?? []).map((member) => (
          <option key={member.user} value={member.user}>
            {member.full_name ?? member.user}
          </option>
        ))}
      </select>
      <select
        aria-label="Status"
        className="h-8 rounded-md border border-input bg-transparent px-2 text-xs"
        value={status}
        onChange={(e) => {
          onStatusChange(e.target.value);
        }}
      >
        <option value="open">Open</option>
        <option value="pending">Pending</option>
        <option value="resolved">Resolved</option>
        {status === 'snoozed' && <option value="snoozed">Snoozed</option>}
        {SNOOZE_PRESETS.map((preset) => (
          <option key={preset.key} value={`snooze-${preset.key}`}>
            {preset.label}
          </option>
        ))}
      </select>
      {status !== 'resolved' && (
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setStatus.mutate({ status: 'resolved' });
          }}
        >
          Resolve
        </Button>
      )}
    </div>
  );
}

export default function ConversationPane({
  chatName,
  title,
  chat,
  onToggleContact,
  onBack,
}: {
  chatName: string;
  title: string;
  chat?: WdChat;
  onToggleContact?: () => void;
  /** Mobile master-detail: return to the chat list (hidden on md+). */
  onBack?: () => void;
}): React.JSX.Element {
  const queryClient = useQueryClient();

  // --- presence: heartbeat own state, render others' ---
  const me = useQuery({ queryKey: ['logged-user'], queryFn: () => client.getLoggedUser() });
  const others = useChatPresence(chatName, me.data ?? null);
  const lastTypingPing = useRef(0);
  useEffect(() => {
    const ping = (): void => {
      client.presencePing(chatName, 'viewing').catch(() => undefined);
    };
    ping();
    const timer = setInterval(ping, PRESENCE_HEARTBEAT_MS);
    return () => {
      clearInterval(timer);
    };
  }, [chatName]);
  const pingTyping = (): void => {
    const now = Date.now();
    if (now - lastTypingPing.current < TYPING_PING_MIN_GAP_MS) {
      return;
    }
    lastTypingPing.current = now;
    client.presencePing(chatName, 'typing').catch(() => undefined);
  };

  const messages = useInfiniteQuery({
    queryKey: ['messages', chatName],
    queryFn: ({ pageParam }) => client.listMessages(chatName, pageParam ?? undefined),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => (lastPage.has_more ? lastPage.next_before : null),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000, // fallback only — realtime events drive updates
  });

  const [draft, setDraft] = useState('');

  // --- canned responses: `/` opens the menu instantly (minChars 0) ---
  const cannedOpen = draft.startsWith('/');
  const cannedTerm = cannedOpen ? draft.slice(1).trim() : '';
  const canned = useQuery({
    queryKey: ['canned-search', cannedTerm],
    queryFn: () => client.searchCanned(cannedTerm),
    enabled: cannedOpen,
    placeholderData: keepPreviousData,
  });
  const cannedItems = cannedOpen ? (canned.data ?? []) : [];
  const [cannedIndex, setCannedIndex] = useState(0);
  useEffect(() => {
    setCannedIndex(0);
  }, [cannedTerm, cannedOpen]);
  const members = useQuery({ queryKey: ['members'], queryFn: () => client.listMembers() });
  const insertCanned = (item: WdCannedResponse): void => {
    const meMember = members.data?.find((member) => member.user === me.data);
    const agentName = meMember?.full_name ?? me.data ?? '';
    setDraft(
      substituteVariables(item.content, {
        'contact.name': chat?.contact_name,
        'contact.first_name': chat?.contact_name?.split(' ')[0],
        'contact.phone': chat?.contact_phone,
        'agent.name': agentName,
        'agent.first_name': agentName.split(' ')[0],
        'agent.email': me.data,
      }),
    );
  };

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
      {/* flex-wrap: on narrow screens the controls drop to a second row
          instead of crushing the title to zero width */}
      <header className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
        {onBack && (
          <Button
            aria-label="Back to chat list"
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0 md:hidden"
            onClick={onBack}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
        )}
        <div className="min-w-0 flex-1 basis-32">
          <h2 className="truncate font-semibold">{title}</h2>
          {others.length > 0 && (
            <p data-testid="presence-indicator" className="truncate text-xs text-muted-foreground">
              {others
                .map((o) => `${o.fullName} is ${o.state === 'typing' ? 'typing…' : 'viewing'}`)
                .join(' · ')}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <HeaderControls chatName={chatName} chat={chat} />
          <LabelPicker chatName={chatName} chat={chat} />
          {chat?.contact && onToggleContact && (
            <Button
              aria-label="Contact details"
              variant="outline"
              size="icon"
              className="h-8 w-8"
              onClick={onToggleContact}
            >
              <UserRound className="h-4 w-4" />
            </Button>
          )}
        </div>
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
          <Bubble
            key={message.name}
            message={message}
            showSender={chat?.chat_type === 'group'}
            onRetry={(name) => retry.mutate(name)}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      <footer className="border-t p-3">
        {cannedOpen && cannedItems.length > 0 && (
          <div
            data-testid="canned-menu"
            className="mb-2 max-h-48 overflow-y-auto rounded-md border bg-background shadow-md"
          >
            {cannedItems.map((item, index) => (
              <button
                key={item.name}
                type="button"
                data-testid="canned-item"
                className={cn(
                  'flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-sm hover:bg-accent',
                  index === cannedIndex && 'bg-accent',
                )}
                // mousedown (not click) so the textarea never loses focus
                onMouseDown={(e) => {
                  e.preventDefault();
                  insertCanned(item);
                }}
              >
                <span className="shrink-0 font-mono text-xs text-primary">/{item.shortcode}</span>
                <span className="truncate text-xs text-muted-foreground">{item.content}</span>
              </button>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2">
          <textarea
            aria-label="Message"
            placeholder="Type a message… ( / for canned responses, Enter to send )"
            value={draft}
            rows={Math.min(draft.split('\n').length, 5)}
            onChange={(e) => {
              setDraft(e.target.value);
              if (e.target.value) {
                pingTyping();
              }
            }}
            onKeyDown={(e) => {
              if (cannedOpen && cannedItems.length > 0) {
                // menu owns the keyboard: Enter selects instead of sending
                if (e.key === 'ArrowDown') {
                  e.preventDefault();
                  setCannedIndex((i) => (i + 1) % cannedItems.length);
                  return;
                }
                if (e.key === 'ArrowUp') {
                  e.preventDefault();
                  setCannedIndex((i) => (i - 1 + cannedItems.length) % cannedItems.length);
                  return;
                }
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  const item = cannedItems[cannedIndex] ?? cannedItems[0];
                  if (item) {
                    insertCanned(item);
                  }
                  return;
                }
                if (e.key === 'Escape') {
                  e.preventDefault();
                  setDraft('');
                  return;
                }
              }
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
