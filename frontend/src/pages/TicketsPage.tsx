import { useState } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import type {
  TicketListParams,
  WdTicket,
  WdTicketPriority,
  WdTicketStatus,
} from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { useWorkspaceEvents } from '@/lib/realtime';
import { cn } from '@/lib/utils';

const STATUS_TABS: { key: '' | WdTicketStatus; label: string }[] = [
  { key: '', label: 'All' },
  { key: 'open', label: 'Open' },
  { key: 'in_progress', label: 'In progress' },
  { key: 'resolved', label: 'Resolved' },
  { key: 'closed', label: 'Closed' },
];

const PRIORITY_STYLE: Record<WdTicketPriority, string> = {
  low: 'bg-muted text-muted-foreground',
  medium: 'bg-sky-500/15 text-sky-600',
  high: 'bg-amber-500/15 text-amber-600',
  urgent: 'bg-destructive/15 text-destructive',
};

function StatusPicker({ ticket }: { ticket: WdTicket }): React.JSX.Element {
  const queryClient = useQueryClient();
  const update = useMutation({
    mutationFn: (status: WdTicketStatus) => client.updateTicket(ticket.name, { status }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tickets'] });
    },
  });
  return (
    <select
      aria-label={`Status of ${ticket.title}`}
      value={ticket.status}
      onClick={(e) => {
        e.stopPropagation();
      }}
      onChange={(e) => {
        update.mutate(e.target.value as WdTicketStatus);
      }}
      className="h-7 rounded-md border border-input bg-transparent px-1 text-xs"
    >
      <option value="open">Open</option>
      <option value="in_progress">In progress</option>
      <option value="resolved">Resolved</option>
      <option value="closed">Closed</option>
    </select>
  );
}

export default function TicketsPage(): React.JSX.Element {
  useWorkspaceEvents(); // wd:ticket keeps the list live
  const navigate = useNavigate();
  const [status, setStatus] = useState<'' | WdTicketStatus>('');
  const [assignee, setAssignee] = useState<'' | 'me' | 'unassigned'>('');

  const tickets = useQuery({
    queryKey: ['tickets', status, assignee],
    queryFn: () =>
      client.listTickets({
        ...(status ? { status } : {}),
        ...(assignee ? { assignee } : {}),
      } as TicketListParams),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
  const rows = tickets.data?.tickets ?? [];

  return (
    <div className="mx-auto max-w-4xl p-6">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Tickets</h1>
        {tickets.data && (
          <span className="text-sm text-muted-foreground">{tickets.data.total}</span>
        )}
        <div role="tablist" aria-label="Ticket status" className="flex gap-1">
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
        <select
          aria-label="Assignee filter"
          value={assignee}
          onChange={(e) => {
            setAssignee(e.target.value as '' | 'me' | 'unassigned');
          }}
          className="h-7 rounded-md border border-input bg-transparent px-1 text-xs"
        >
          <option value="">Anyone</option>
          <option value="me">Mine</option>
          <option value="unassigned">Unassigned</option>
        </select>
      </div>

      {tickets.isLoading && <p className="text-sm text-muted-foreground">Loading tickets…</p>}
      {tickets.data && rows.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No tickets. Convert a conversation into one from the inbox.
        </p>
      )}

      <ul className="divide-y rounded-lg border">
        {rows.map((ticket) => (
          <li
            key={ticket.name}
            data-testid="ticket-row"
            className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-accent/50"
            onClick={() => {
              if (ticket.chat) {
                void navigate('/inbox');
              }
            }}
          >
            <span
              data-testid="priority-badge"
              className={cn(
                'shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium',
                PRIORITY_STYLE[ticket.priority],
              )}
            >
              {ticket.priority}
            </span>
            <span className="min-w-0 flex-1 truncate text-sm">{ticket.title}</span>
            {ticket.assigned_agent && (
              <span className="shrink-0 text-xs text-muted-foreground">
                {ticket.assigned_agent.split('@')[0]}
              </span>
            )}
            <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
              {ticket.name}
            </span>
            <StatusPicker ticket={ticket} />
          </li>
        ))}
      </ul>
    </div>
  );
}
