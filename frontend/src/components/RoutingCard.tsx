import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import type { WdRouting, WdTeam, WdWorkspaceSettings } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const ROUTING_OPTIONS: { value: WdRouting; label: string }[] = [
  { value: 'manual', label: 'Manual (assign by hand)' },
  { value: 'round_robin', label: 'Round-robin (rotate)' },
  { value: 'load_based', label: 'Load-based (fewest chats)' },
];

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

/** Auto-assignment & routing config (P3.2): per-team routing mode + capacity,
 * plus the workspace-wide default team new chats land on. */
export default function RoutingCard({
  canManage,
  settings,
}: {
  canManage: boolean;
  settings: WdWorkspaceSettings | undefined;
}): React.JSX.Element {
  const queryClient = useQueryClient();
  const teams = useQuery({ queryKey: ['teams'], queryFn: () => client.listTeams() });
  const [newName, setNewName] = useState('');

  const invalidate = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['teams'] });
    void queryClient.invalidateQueries({ queryKey: ['workspace-settings'] });
  };

  const update = useMutation({
    mutationFn: (change: { team: string; routing?: WdRouting; capacityPerAgent?: number }) =>
      client.updateTeam(change.team, {
        ...(change.routing !== undefined ? { routing: change.routing } : {}),
        ...(change.capacityPerAgent !== undefined
          ? { capacityPerAgent: change.capacityPerAgent }
          : {}),
      }),
    onSuccess: invalidate,
  });
  const create = useMutation({
    mutationFn: () => client.createTeam(newName.trim(), { routing: 'round_robin' }),
    onSuccess: () => {
      setNewName('');
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: (team: string) => client.deleteTeam(team),
    onSuccess: invalidate,
  });
  const setDefault = useMutation({
    mutationFn: (team: string) =>
      client.updateWorkspaceSettings({ default_routing_team: team || null }),
    onSuccess: invalidate,
  });

  const rows = teams.data ?? [];

  return (
    <section aria-label="Routing" className="rounded-lg border p-4">
      <h2 className="font-semibold">Auto-assignment &amp; routing</h2>
      <p className="mb-3 text-sm text-muted-foreground">
        Choose how each team distributes new chats to available agents. Agents at capacity or
        offline are skipped.
      </p>

      <ul className="mb-3 space-y-2">
        {rows.map((team: WdTeam) => (
          <li
            key={team.name}
            data-testid="routing-team-row"
            className="flex flex-wrap items-center gap-2 rounded border px-3 py-2 text-sm"
          >
            <span className="min-w-0 flex-1 truncate font-medium">{team.team_name}</span>
            <select
              aria-label={`Routing for ${team.team_name}`}
              value={team.routing}
              disabled={!canManage || update.isPending}
              onChange={(e) => {
                update.mutate({ team: team.name, routing: e.target.value as WdRouting });
              }}
              className="h-8 rounded-md border border-input bg-transparent px-1 text-xs"
            >
              {ROUTING_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-1 text-xs text-muted-foreground">
              cap
              <Input
                aria-label={`Capacity for ${team.team_name}`}
                type="number"
                min={0}
                className="h-8 w-16"
                key={team.capacity_per_agent}
                defaultValue={team.capacity_per_agent}
                disabled={!canManage}
                onBlur={(e) => {
                  const cap = Number(e.target.value);
                  if (canManage && cap >= 0 && cap !== team.capacity_per_agent) {
                    update.mutate({ team: team.name, capacityPerAgent: cap });
                  }
                }}
              />
            </label>
            {canManage && (
              <button
                type="button"
                aria-label={`Delete team ${team.team_name}`}
                className="rounded p-1 text-destructive hover:bg-accent"
                onClick={() => {
                  remove.mutate(team.name);
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </li>
        ))}
        {rows.length === 0 && (
          <li className="px-1 text-sm text-muted-foreground">No teams yet.</li>
        )}
      </ul>

      {canManage && (
        <>
          <form
            className="mb-3 flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (newName.trim()) {
                create.mutate();
              }
            }}
          >
            <Input
              aria-label="New team name"
              placeholder="e.g. Sales"
              value={newName}
              onChange={(e) => {
                setNewName(e.target.value);
              }}
            />
            <Button type="submit" disabled={!newName.trim() || create.isPending}>
              Add team
            </Button>
          </form>

          <label className="block text-sm" htmlFor="default-routing-team">
            Default team for new chats
            <span className="block text-xs text-muted-foreground">
              New conversations auto-route through this team.
            </span>
          </label>
          <select
            id="default-routing-team"
            aria-label="Default routing team"
            className="mt-1 h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm"
            value={settings?.default_routing_team ?? ''}
            onChange={(e) => {
              setDefault.mutate(e.target.value);
            }}
          >
            <option value="">None</option>
            {rows.map((team) => (
              <option key={team.name} value={team.name}>
                {team.team_name}
              </option>
            ))}
          </select>
        </>
      )}
      {(update.isError || create.isError || setDefault.isError) && (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {errorText(update.error ?? create.error ?? setDefault.error)}
        </p>
      )}
    </section>
  );
}
