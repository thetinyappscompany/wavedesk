import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Megaphone, Pause, Play, Plus, RotateCcw, Trash2, X } from 'lucide-react';
import type { WdAudienceType, WdBroadcast } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { useWorkspaceEvents } from '@/lib/realtime';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const AUDIENCE: { value: WdAudienceType; label: string }[] = [
  { value: 'all_contacts', label: 'All contacts' },
  { value: 'csv', label: 'CSV (phone,name per line)' },
  { value: 'group_members', label: "A group's members" },
];

const STATUS_TONE: Record<WdBroadcast['status'], string> = {
  draft: 'bg-muted text-muted-foreground',
  sending: 'bg-blue-500/15 text-blue-600',
  paused: 'bg-amber-500/15 text-amber-600',
  completed: 'bg-emerald-500/15 text-emerald-600',
  cancelled: 'bg-destructive/15 text-destructive',
};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

function parseCsv(text: string): { phone: string; name?: string }[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [phone, ...rest] = line.split(',');
      return { phone: (phone ?? '').trim(), name: rest.join(',').trim() || undefined };
    })
    .filter((r) => r.phone);
}

function Composer({ onDone }: { onDone: () => void }): React.JSX.Element {
  const queryClient = useQueryClient();
  const numbers = useQuery({ queryKey: ['numbers'], queryFn: () => client.listNumbers() });
  const [name, setName] = useState('');
  const [number, setNumber] = useState('');
  const [audienceType, setAudienceType] = useState<WdAudienceType>('all_contacts');
  const [csv, setCsv] = useState('');
  const [groupRef, setGroupRef] = useState('');
  const [message, setMessage] = useState('');
  const [dailyCap, setDailyCap] = useState('0');

  const create = useMutation({
    mutationFn: () =>
      client.createBroadcast({
        broadcastName: name.trim(),
        number,
        messageTemplate: message,
        audienceType,
        ...(audienceType === 'csv' ? { audience: parseCsv(csv) } : {}),
        ...(audienceType === 'group_members' ? { audienceRef: groupRef.trim() } : {}),
        dailyCap: Number(dailyCap) || 0,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['broadcasts'] });
      onDone();
    },
  });

  const canSave = name.trim() && number && message.trim();

  return (
    <form
      className="space-y-3 rounded-lg border p-4"
      data-testid="broadcast-composer"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSave) {
          create.mutate();
        }
      }}
    >
      <Input
        aria-label="Broadcast name"
        placeholder="e.g. Diwali offer"
        value={name}
        onChange={(e) => {
          setName(e.target.value);
        }}
      />
      <div className="flex flex-wrap gap-2">
        <select
          aria-label="Sending number"
          value={number}
          onChange={(e) => {
            setNumber(e.target.value);
          }}
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
        >
          <option value="">Select number…</option>
          {(numbers.data ?? []).map((n) => (
            <option key={n.name} value={n.name}>
              {n.phone ?? n.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Audience"
          value={audienceType}
          onChange={(e) => {
            setAudienceType(e.target.value as WdAudienceType);
          }}
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
        >
          {AUDIENCE.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </select>
      </div>

      {audienceType === 'csv' && (
        <textarea
          aria-label="CSV recipients"
          placeholder={'919900000001,Asha\n919900000002,Riya'}
          value={csv}
          rows={3}
          onChange={(e) => {
            setCsv(e.target.value);
          }}
          className="w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs"
        />
      )}
      {audienceType === 'group_members' && (
        <Input
          aria-label="Group id"
          placeholder="WD Group id (from the Groups page)"
          value={groupRef}
          onChange={(e) => {
            setGroupRef(e.target.value);
          }}
        />
      )}

      <textarea
        aria-label="Message template"
        placeholder="Namaste {{name}}! Our Diwali sale is live 🎉"
        value={message}
        rows={3}
        onChange={(e) => {
          setMessage(e.target.value);
        }}
        className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
      />
      <p className="text-xs text-muted-foreground">
        Variables: {'{{name}}'} and {'{{phone}}'} fill in per recipient.
      </p>

      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        Daily cap (0 = unlimited)
        <Input
          aria-label="Daily cap"
          type="number"
          min={0}
          className="h-8 w-24"
          value={dailyCap}
          onChange={(e) => {
            setDailyCap(e.target.value);
          }}
        />
      </label>

      <div className="flex gap-2">
        <Button type="submit" disabled={!canSave || create.isPending}>
          Create broadcast
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
      {create.isError && (
        <p role="alert" className="text-xs text-destructive">
          {errorText(create.error)}
        </p>
      )}
    </form>
  );
}

function Report({ broadcast }: { broadcast: string }): React.JSX.Element {
  const report = useQuery({
    queryKey: ['broadcast-report', broadcast],
    queryFn: () => client.broadcastReport(broadcast),
    refetchInterval: 5000,
  });
  const data = report.data;
  if (!data) {
    return <p className="p-3 text-sm text-muted-foreground">Loading report…</p>;
  }
  return (
    <div className="space-y-2 p-3" data-testid="broadcast-report">
      <div className="flex flex-wrap gap-2 text-xs">
        {Object.entries(data.counts).map(([k, v]) => (
          <span key={k} className="rounded border px-2 py-0.5">
            {k}: <span className="font-medium">{v}</span>
          </span>
        ))}
      </div>
      <ul className="max-h-64 space-y-1 overflow-auto">
        {data.recipients.map((r) => (
          <li
            key={r.name}
            data-testid="recipient-row"
            className="flex items-center gap-2 rounded border px-2 py-1 text-xs"
          >
            <span className="w-28 shrink-0 font-mono">{r.phone}</span>
            <span className="flex-1 truncate">{r.recipient_name}</span>
            <span className="text-muted-foreground">{r.message_status ?? r.status}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function BroadcastsPage(): React.JSX.Element {
  useWorkspaceEvents();
  const queryClient = useQueryClient();
  const [building, setBuilding] = useState(false);
  const [openReport, setOpenReport] = useState<string | null>(null);
  const broadcasts = useQuery({
    queryKey: ['broadcasts'],
    queryFn: () => client.listBroadcasts(),
    refetchInterval: 5000,
  });

  const onSuccess = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['broadcasts'] });
  };
  const start = useMutation({ mutationFn: (n: string) => client.startBroadcast(n), onSuccess });
  const pause = useMutation({ mutationFn: (n: string) => client.pauseBroadcast(n), onSuccess });
  const resume = useMutation({ mutationFn: (n: string) => client.resumeBroadcast(n), onSuccess });
  const cancel = useMutation({ mutationFn: (n: string) => client.cancelBroadcast(n), onSuccess });
  const retry = useMutation({ mutationFn: (n: string) => client.retryBroadcast(n), onSuccess });
  const remove = useMutation({ mutationFn: (n: string) => client.deleteBroadcast(n), onSuccess });

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div className="flex items-center gap-3">
        <Megaphone className="h-5 w-5" />
        <h1 className="text-lg font-semibold">Broadcasts</h1>
        {!building && (
          <Button size="sm" onClick={() => setBuilding(true)}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            New broadcast
          </Button>
        )}
      </div>

      {building && (
        <Composer
          onDone={() => {
            setBuilding(false);
          }}
        />
      )}

      <ul className="space-y-2">
        {(broadcasts.data ?? []).map((b) => (
          <li key={b.name} data-testid="broadcast-row" className="rounded-lg border">
            <div className="flex flex-wrap items-center gap-2 px-3 py-2">
              <span className="min-w-0 flex-1 truncate font-medium">{b.broadcast_name}</span>
              <span className={`rounded px-1.5 py-0.5 text-[10px] ${STATUS_TONE[b.status]}`}>
                {b.status}
              </span>
              <span className="text-xs text-muted-foreground">
                {b.sent_count}/{b.total_recipients} sent
                {b.failed_count > 0 && ` · ${String(b.failed_count)} failed`}
              </span>
              {(b.status === 'draft' || b.status === 'paused') && (
                <button
                  type="button"
                  aria-label={`${b.status === 'paused' ? 'Resume' : 'Start'} ${b.broadcast_name}`}
                  className="rounded p-1 text-emerald-600 hover:bg-accent"
                  onClick={() => {
                    (b.status === 'paused' ? resume : start).mutate(b.name);
                  }}
                >
                  <Play className="h-3.5 w-3.5" />
                </button>
              )}
              {b.status === 'sending' && (
                <button
                  type="button"
                  aria-label={`Pause ${b.broadcast_name}`}
                  className="rounded p-1 text-amber-600 hover:bg-accent"
                  onClick={() => {
                    pause.mutate(b.name);
                  }}
                >
                  <Pause className="h-3.5 w-3.5" />
                </button>
              )}
              {b.failed_count > 0 && (
                <button
                  type="button"
                  aria-label={`Retry failed ${b.broadcast_name}`}
                  className="rounded p-1 text-muted-foreground hover:bg-accent"
                  onClick={() => {
                    retry.mutate(b.name);
                  }}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                </button>
              )}
              {(b.status === 'sending' || b.status === 'paused' || b.status === 'draft') && (
                <button
                  type="button"
                  aria-label={`Cancel ${b.broadcast_name}`}
                  className="rounded p-1 text-destructive hover:bg-accent"
                  onClick={() => {
                    cancel.mutate(b.name);
                  }}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
              {(b.status === 'completed' || b.status === 'cancelled') && (
                <button
                  type="button"
                  aria-label={`Delete ${b.broadcast_name}`}
                  className="rounded p-1 text-destructive hover:bg-accent"
                  onClick={() => {
                    remove.mutate(b.name);
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
              <button
                type="button"
                className="text-xs text-primary hover:underline"
                onClick={() => {
                  setOpenReport((cur) => (cur === b.name ? null : b.name));
                }}
              >
                {openReport === b.name ? 'Hide' : 'Report'}
              </button>
            </div>
            {openReport === b.name && <Report broadcast={b.name} />}
          </li>
        ))}
        {broadcasts.data?.length === 0 && !building && (
          <li className="rounded-lg border px-3 py-6 text-center text-sm text-muted-foreground">
            No broadcasts yet — create one to message an audience safely.
          </li>
        )}
      </ul>
    </div>
  );
}
