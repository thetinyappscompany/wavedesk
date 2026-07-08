import { useEffect, useRef, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useVirtualizer } from '@tanstack/react-virtual';
import type { WdChat } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import ContactDrawer from '@/components/ContactDrawer';
import ConversationPane from '@/components/ConversationPane';
import { useWorkspaceEvents } from '@/lib/realtime';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

const STATUS_TABS = [
  { key: '', label: 'All' },
  { key: 'open', label: 'Open' },
  { key: 'pending', label: 'Pending' },
  { key: 'resolved', label: 'Resolved' },
] as const;

const VIEW_TABS = [
  { key: '', label: 'All' },
  { key: 'me', label: 'Mine' },
  { key: 'unassigned', label: 'Unassigned' },
] as const;

const ROW_HEIGHT = 72;
const PAGE_SIZE = 100;

function timeLabel(iso: string | null): string {
  if (!iso) {
    return '';
  }
  const date = new Date(iso.replace(' ', 'T'));
  const today = new Date();
  return date.toDateString() === today.toDateString()
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString([], { day: '2-digit', month: 'short' });
}

function ChatRow({ chat, selected, onSelect }: {
  chat: WdChat;
  selected: boolean;
  onSelect: (name: string) => void;
}): React.JSX.Element {
  const title = chat.contact_name ?? chat.contact_phone ?? chat.wa_chat_id;
  const chips = chat.labels.slice(0, 2);
  return (
    <button
      type="button"
      data-testid="chat-row"
      onClick={() => onSelect(chat.name)}
      className={cn(
        'flex w-full items-center justify-between gap-2 border-b px-3 py-3 text-left hover:bg-accent',
        selected && 'bg-accent',
      )}
      style={{ height: ROW_HEIGHT }}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">{title}</span>
          {chat.chat_type === 'group' && (
            <span className="rounded border px-1 text-xs text-muted-foreground">group</span>
          )}
          {chips.map((chip) => (
            <span
              key={chip.label}
              data-testid="label-chip"
              className="shrink-0 rounded px-1 text-[10px] font-medium"
              style={{ backgroundColor: `${chip.color}22`, color: chip.color }}
            >
              {chip.title}
            </span>
          ))}
          {chat.labels.length > 2 && (
            <span className="shrink-0 text-[10px] text-muted-foreground">
              +{chat.labels.length - 2}
            </span>
          )}
        </div>
        <div className="truncate text-sm text-muted-foreground">
          {chat.contact_phone ?? chat.wa_chat_id}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <span className="text-xs text-muted-foreground">{timeLabel(chat.last_message_at)}</span>
        {chat.unread_count > 0 && (
          <span
            data-testid="unread-badge"
            className="rounded-full bg-primary px-1.5 py-0.5 text-xs font-medium text-primary-foreground"
          >
            {chat.unread_count}
          </span>
        )}
      </div>
    </button>
  );
}

export default function InboxPage(): React.JSX.Element {
  useWorkspaceEvents(); // socket-driven cache invalidation — polling is a fallback
  const [status, setStatus] = useState<string>('');
  const [assignee, setAssignee] = useState<string>('');
  const [label, setLabel] = useState<string>('');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [contactOpen, setContactOpen] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
    }, 300);
    return () => {
      clearTimeout(timer);
    };
  }, [search]);

  const labels = useQuery({ queryKey: ['labels'], queryFn: () => client.listLabels() });

  const chats = useQuery({
    queryKey: ['chats', status, assignee, label, debouncedSearch],
    queryFn: () =>
      client.listChats({
        status: status || undefined,
        assignee: assignee || undefined,
        label: label || undefined,
        search: debouncedSearch || undefined,
        limit: PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000, // fallback only — realtime events drive updates
  });

  const rows = chats.data?.chats ?? [];
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  });

  return (
    <div className="flex h-full">
      {/* Chat list pane */}
      <section className="flex w-80 shrink-0 flex-col border-r">
        <div className="space-y-2 border-b p-3">
          <h1 className="text-lg font-semibold">Inbox</h1>
          <Input
            placeholder="Search name or phone…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
          />
          <div role="tablist" aria-label="Status" className="flex gap-1">
            {STATUS_TABS.map((tab) => (
              <button
                key={tab.key}
                role="tab"
                aria-selected={status === tab.key}
                onClick={() => {
                  setStatus(tab.key);
                }}
                className={cn(
                  'rounded-md px-2 py-1 text-xs',
                  status === tab.key
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-accent',
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div role="tablist" aria-label="Assignee" className="flex gap-1">
            {VIEW_TABS.map((tab) => (
              <button
                key={tab.key}
                role="tab"
                aria-selected={assignee === tab.key}
                onClick={() => {
                  setAssignee(tab.key);
                }}
                className={cn(
                  'rounded-md px-2 py-1 text-xs',
                  assignee === tab.key
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-accent',
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
          {(labels.data?.length ?? 0) > 0 && (
            <select
              aria-label="Label filter"
              value={label}
              onChange={(e) => {
                setLabel(e.target.value);
              }}
              className="h-7 w-full rounded-md border border-input bg-transparent px-2 text-xs"
            >
              <option value="">All labels</option>
              {(labels.data ?? []).map((row) => (
                <option key={row.name} value={row.name}>
                  {row.title}
                </option>
              ))}
            </select>
          )}
        </div>

        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto" data-testid="chat-scroll">
          {chats.isLoading && (
            <p className="p-4 text-sm text-muted-foreground">Loading chats…</p>
          )}
          {chats.isError && (
            <p role="alert" className="p-4 text-sm text-destructive">
              Failed to load chats — are you logged in?
            </p>
          )}
          {chats.data && rows.length === 0 && (
            <p className="p-4 text-sm text-muted-foreground">
              No conversations yet. Messages to your connected numbers appear here.
            </p>
          )}
          <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((item) => {
              const chat = rows[item.index];
              if (!chat) {
                return null;
              }
              return (
                <div
                  key={chat.name}
                  className="absolute left-0 top-0 w-full"
                  style={{ transform: `translateY(${String(item.start)}px)` }}
                >
                  <ChatRow chat={chat} selected={selected === chat.name} onSelect={setSelected} />
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {selected ? (
        (() => {
          const chat = rows.find((row) => row.name === selected);
          return (
            <>
              <ConversationPane
                chatName={selected}
                title={chat?.contact_name ?? chat?.contact_phone ?? chat?.wa_chat_id ?? selected}
                chat={chat}
                onToggleContact={() => {
                  setContactOpen((open) => !open);
                }}
              />
              {contactOpen && chat?.contact && (
                <ContactDrawer
                  contactName={chat.contact}
                  activeChat={selected}
                  onOpenChat={setSelected}
                  onClose={() => {
                    setContactOpen(false);
                  }}
                />
              )}
            </>
          );
        })()
      ) : (
        <section className="flex min-w-0 flex-1 items-center justify-center text-muted-foreground">
          <p className="text-sm">Select a conversation</p>
        </section>
      )}
    </div>
  );
}
