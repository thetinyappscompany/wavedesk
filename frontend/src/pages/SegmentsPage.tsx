import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Filter, Plus, Trash2, Users, X } from 'lucide-react';
import type { WdSegmentCondition, WdSegmentConditionType } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const CONDITIONS: WdSegmentConditionType[] = [
  'has_tag',
  'attribute',
  'opted_out',
  'has_email',
  'name_contains',
  'phone_prefix',
  'last_seen_days',
  'in_group',
];
const NEEDS_KEY = new Set<WdSegmentConditionType>(['attribute']);
const BOOL_TYPES = new Set<WdSegmentConditionType>(['opted_out', 'has_email']);

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

function PreviewCount({ segment }: { segment: string }): React.JSX.Element {
  const preview = useQuery({
    queryKey: ['segment-preview', segment],
    queryFn: () => client.previewSegment(segment),
  });
  return (
    <span className="flex items-center gap-1 text-xs text-muted-foreground">
      <Users className="h-3.5 w-3.5" />
      {preview.data ? `${String(preview.data.count)} contacts` : '…'}
    </span>
  );
}

function Builder({ onDone }: { onDone: () => void }): React.JSX.Element {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [matchType, setMatchType] = useState<'all' | 'any'>('all');
  const [filters, setFilters] = useState<WdSegmentCondition[]>([{ type: 'has_tag', value: '' }]);

  const create = useMutation({
    mutationFn: () =>
      client.createSegment({ segmentName: name.trim(), matchType, filters }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['segments'] });
      onDone();
    },
  });

  const setFilter = (i: number, patch: Partial<WdSegmentCondition>): void => {
    setFilters((f) => f.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  };

  return (
    <form
      className="space-y-3 rounded-lg border p-4"
      data-testid="segment-builder"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) {
          create.mutate();
        }
      }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="Segment name"
          placeholder="e.g. Mumbai VIPs"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
        <select
          aria-label="Match type"
          value={matchType}
          onChange={(e) => {
            setMatchType(e.target.value as 'all' | 'any');
          }}
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
        >
          <option value="all">Match all</option>
          <option value="any">Match any</option>
        </select>
        <button
          type="button"
          aria-label="Add filter"
          className="rounded p-1 hover:bg-accent"
          onClick={() => {
            setFilters((f) => [...f, { type: 'has_tag', value: '' }]);
          }}
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>

      {filters.map((cond, i) => (
        <div key={i} className="flex flex-wrap items-center gap-1" data-testid="filter-row">
          <select
            aria-label={`Filter ${String(i + 1)} type`}
            value={cond.type}
            onChange={(e) => {
              setFilter(i, { type: e.target.value as WdSegmentConditionType, key: undefined });
            }}
            className="h-8 rounded-md border border-input bg-transparent px-1 text-xs"
          >
            {CONDITIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          {NEEDS_KEY.has(cond.type) && (
            <Input
              aria-label={`Filter ${String(i + 1)} key`}
              placeholder="attribute key"
              className="h-8 w-32"
              value={String(cond.key ?? '')}
              onChange={(e) => {
                setFilter(i, { key: e.target.value });
              }}
            />
          )}
          {BOOL_TYPES.has(cond.type) ? (
            <select
              aria-label={`Filter ${String(i + 1)} value`}
              value={cond.value ? 'true' : 'false'}
              onChange={(e) => {
                setFilter(i, { value: e.target.value === 'true' });
              }}
              className="h-8 rounded-md border border-input bg-transparent px-1 text-xs"
            >
              <option value="true">yes</option>
              <option value="false">no</option>
            </select>
          ) : (
            <Input
              aria-label={`Filter ${String(i + 1)} value`}
              className="h-8 w-40"
              value={String(cond.value ?? '')}
              onChange={(e) => {
                setFilter(i, { value: e.target.value });
              }}
            />
          )}
          <button
            type="button"
            aria-label={`Remove filter ${String(i + 1)}`}
            className="rounded p-1 text-destructive hover:bg-accent"
            onClick={() => {
              setFilters((f) => f.filter((_, j) => j !== i));
            }}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}

      <div className="flex gap-2">
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          Save segment
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

export default function SegmentsPage(): React.JSX.Element {
  const queryClient = useQueryClient();
  const [building, setBuilding] = useState(false);
  const segments = useQuery({ queryKey: ['segments'], queryFn: () => client.listSegments() });
  const remove = useMutation({
    mutationFn: (name: string) => client.deleteSegment(name),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['segments'] }),
  });

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div className="flex items-center gap-3">
        <Filter className="h-5 w-5" />
        <h1 className="text-lg font-semibold">Segments</h1>
        {!building && (
          <Button size="sm" onClick={() => setBuilding(true)}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            New segment
          </Button>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        Dynamic groups of contacts, evaluated live — use them as a broadcast audience or in
        automation rules.
      </p>

      {building && (
        <Builder
          onDone={() => {
            setBuilding(false);
          }}
        />
      )}

      <ul className="space-y-2">
        {(segments.data ?? []).map((seg) => (
          <li
            key={seg.name}
            data-testid="segment-row"
            className="flex items-center gap-2 rounded-lg border px-3 py-2"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate font-medium">{seg.segment_name}</span>
                <span className="rounded border px-1 text-[10px] text-muted-foreground">
                  match {seg.match_type}
                </span>
              </div>
              <div className="truncate text-xs text-muted-foreground">
                {seg.filters.map((f) => f.type).join(', ') || 'all contacts'}
              </div>
            </div>
            <PreviewCount segment={seg.name} />
            <button
              type="button"
              aria-label={`Delete ${seg.segment_name}`}
              className="rounded p-1 text-destructive hover:bg-accent"
              onClick={() => {
                remove.mutate(seg.name);
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </li>
        ))}
        {segments.data?.length === 0 && !building && (
          <li className="rounded-lg border px-3 py-6 text-center text-sm text-muted-foreground">
            No segments yet — create one to target a subset of your contacts.
          </li>
        )}
      </ul>
    </div>
  );
}
