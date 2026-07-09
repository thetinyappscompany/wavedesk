import { useEffect, useState } from 'react';
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query';
import { Crown, Send } from 'lucide-react';
import { client } from '@/lib/client';
import GroupDrawer from '@/components/GroupDrawer';
import { useWorkspaceEvents } from '@/lib/realtime';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const PAGE_SIZE = 100;

function timeLabel(iso: string | null): string {
  if (!iso) {
    return '—';
  }
  const date = new Date(iso.replace(' ', 'T'));
  const today = new Date();
  return date.toDateString() === today.toDateString()
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString([], { day: '2-digit', month: 'short' });
}

/** Group registry (Phase 2 feature 1): searchable table with bulk select.
 * Bulk actions (message N groups, participant management) land with P2.3 —
 * the selection scaffold is here so that epic plugs straight in. */
export default function GroupsPage(): React.JSX.Element {
  useWorkspaceEvents(); // wd:group keeps the registry live
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkBody, setBulkBody] = useState('');
  const [bulkResult, setBulkResult] = useState<string | null>(null);

  const settings = useQuery({
    queryKey: ['workspace-settings'],
    queryFn: () => client.getWorkspaceSettings(),
  });
  const canManage = settings.data ? settings.data.role !== 'Agent' : false;

  const rollup = useQuery({
    queryKey: ['workspace-analytics'],
    queryFn: () => client.workspaceAnalytics(),
    refetchInterval: 60_000,
  });

  const bulkSend = useMutation({
    mutationFn: () => client.sendToGroups([...selected], bulkBody.trim()),
    onSuccess: (result) => {
      setBulkResult(`Queued for ${String(result.queued_groups)} groups — sends are paced 3–8s apart.`);
      setBulkOpen(false);
      setBulkBody('');
      setSelected(new Set());
    },
  });

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
    }, 300);
    return () => {
      clearTimeout(timer);
    };
  }, [search]);

  const groups = useQuery({
    queryKey: ['groups', debouncedSearch],
    queryFn: () =>
      client.listGroups({ search: debouncedSearch || undefined, limit: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000, // fallback — wd:group drives updates
  });
  const rows = groups.data?.groups ?? [];

  const toggle = (name: string): void => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };
  const allSelected = rows.length > 0 && rows.every((row) => selected.has(row.name));
  const toggleAll = (): void => {
    setSelected(allSelected ? new Set() : new Set(rows.map((row) => row.name)));
  };

  return (
    <div className="flex h-full flex-col p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Groups</h1>
        <Input
          className="max-w-xs"
          placeholder="Search groups…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
        />
        {groups.data && (
          <span className="text-sm text-muted-foreground">
            {groups.data.total} group{groups.data.total === 1 ? '' : 's'}
          </span>
        )}
        {selected.size > 0 && (
          <span
            data-testid="bulk-bar"
            className="flex items-center gap-2 rounded-md bg-primary/10 px-2 py-1 text-sm font-medium text-primary"
          >
            {selected.size} selected
            {canManage && (
              <Button
                size="sm"
                className="h-7"
                onClick={() => {
                  setBulkOpen(true);
                  setBulkResult(null);
                }}
              >
                <Send className="mr-1 h-3.5 w-3.5" />
                Message {selected.size} group{selected.size === 1 ? '' : 's'}
              </Button>
            )}
          </span>
        )}
        {bulkResult && (
          <span data-testid="bulk-result" className="text-sm text-primary">
            {bulkResult}
          </span>
        )}
      </div>

      {rollup.data && (
        <div
          data-testid="rollup"
          className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4"
        >
          {[
            { label: 'Groups', value: rollup.data.groups },
            { label: `Messages · ${String(rollup.data.days)}d`, value: rollup.data.messages },
            { label: 'Inbound', value: rollup.data.inbound_messages },
            { label: 'Unanswered', value: rollup.data.unanswered_now },
          ].map((stat) => (
            <div key={stat.label} className="rounded-md border p-2">
              <div className="text-xs text-muted-foreground">{stat.label}</div>
              <div className="text-lg font-semibold">{stat.value}</div>
            </div>
          ))}
        </div>
      )}

      {bulkOpen && (
        <div className="mb-3 rounded-lg border p-3" data-testid="bulk-dialog">
          <label className="block text-sm font-medium" htmlFor="bulk-body">
            Message to {selected.size} selected group{selected.size === 1 ? '' : 's'}
          </label>
          <textarea
            id="bulk-body"
            value={bulkBody}
            rows={3}
            placeholder="Namaste! …"
            onChange={(e) => {
              setBulkBody(e.target.value);
            }}
            className="mt-1 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          <div className="mt-2 flex items-center gap-2">
            <Button
              size="sm"
              disabled={!bulkBody.trim() || bulkSend.isPending}
              onClick={() => {
                bulkSend.mutate();
              }}
            >
              Send
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setBulkOpen(false);
              }}
            >
              Cancel
            </Button>
            <span className="text-xs text-muted-foreground">
              Queued through the rate-limited pipeline with randomized 3–8s gaps.
            </span>
          </div>
          {bulkSend.isError && (
            <p role="alert" className="mt-1 text-xs text-destructive">
              {bulkSend.error.message}
            </p>
          )}
        </div>
      )}

      {groups.isLoading && <p className="text-sm text-muted-foreground">Loading groups…</p>}
      {groups.isError && (
        <p role="alert" className="text-sm text-destructive">
          Failed to load groups.
        </p>
      )}
      {groups.data && rows.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No groups yet — they sync automatically when a connected number participates in
          WhatsApp groups.
        </p>
      )}

      {rows.length > 0 && (
        <div className="flex min-h-0 flex-1 gap-0 overflow-hidden rounded-lg border">
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-muted/60 text-left text-xs text-muted-foreground">
              <tr>
                <th className="w-8 px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label="Select all groups"
                    checked={allSelected}
                    onChange={toggleAll}
                  />
                </th>
                <th className="px-3 py-2">Group</th>
                <th className="px-3 py-2">Number</th>
                <th className="px-3 py-2 text-right">Members</th>
                <th className="px-3 py-2 text-right">Msgs today</th>
                <th className="px-3 py-2">Unanswered</th>
                <th className="px-3 py-2 text-right">Unread</th>
                <th className="px-3 py-2">Last activity</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((group) => (
                <tr key={group.name} data-testid="group-row" className="border-t hover:bg-accent/50">
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label={`Select ${group.subject}`}
                      checked={selected.has(group.name)}
                      onChange={() => {
                        toggle(group.name);
                      }}
                    />
                  </td>
                  <td className="max-w-64 px-3 py-2">
                    <button
                      type="button"
                      data-testid="group-open"
                      className="block w-full text-left"
                      onClick={() => {
                        setOpenGroup(group.name);
                      }}
                    >
                      <span className="flex items-center gap-1.5">
                        <span className="truncate font-medium hover:underline">
                          {group.subject}
                        </span>
                        {group.owned_by_us && (
                          <Crown
                            aria-label="We are admin"
                            className="h-3.5 w-3.5 shrink-0 text-amber-500"
                          />
                        )}
                      </span>
                      {group.description && (
                        <span className="block truncate text-xs text-muted-foreground">
                          {group.description}
                        </span>
                      )}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {group.number_name ?? '—'}
                  </td>
                  <td className="px-3 py-2 text-right">{group.member_count}</td>
                  <td className="px-3 py-2 text-right">{group.msgs_today}</td>
                  <td className="px-3 py-2">
                    {group.needs_reply ? (
                      <span
                        data-testid="group-needs-reply"
                        className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-xs font-medium text-amber-600"
                      >
                        needs reply
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {group.unread_count > 0 ? (
                      <span className="rounded-full bg-primary px-1.5 py-0.5 text-xs font-medium text-primary-foreground">
                        {group.unread_count}
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {timeLabel(group.last_message_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {openGroup && (
          <GroupDrawer
            groupName={openGroup}
            canManage={canManage}
            onClose={() => {
              setOpenGroup(null);
            }}
          />
        )}
        </div>
      )}
    </div>
  );
}
