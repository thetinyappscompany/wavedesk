import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Navigate } from 'react-router';
import type { WdAdminWorkspace } from '@wavedesk/api-client';

import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

function WorkspaceRow({ ws, onChange }: { ws: WdAdminWorkspace; onChange: () => void }): React.JSX.Element {
  const suspend = useMutation({
    mutationFn: () =>
      ws.suspended
        ? client.adminUnsuspendWorkspace(ws.name)
        : client.adminSuspendWorkspace(ws.name, 'suspended by operator'),
    onSuccess: onChange,
  });
  const clamp = useMutation({
    mutationFn: (value: number) => client.adminSetSendRateClamp(ws.name, value),
    onSuccess: onChange,
  });

  return (
    <tr className="border-b" data-testid="admin-workspace-row">
      <td className="py-1.5">
        <div className="font-medium">{ws.workspace_name}</div>
        <div className="font-mono text-xs text-muted-foreground">{ws.name}</div>
      </td>
      <td className="text-xs">{ws.subscription_status ?? '—'}</td>
      <td className="text-right text-xs">{ws.members}</td>
      <td className="text-right text-xs">{ws.messages_total}</td>
      <td className="text-center">
        {ws.suspended ? (
          <span className="rounded bg-destructive/15 px-1.5 text-xs text-destructive">suspended</span>
        ) : (
          <span className="text-xs text-emerald-600">active</span>
        )}
      </td>
      <td className="text-right">
        <input
          type="number"
          min={0}
          defaultValue={ws.send_rate_clamp}
          aria-label={`Send clamp for ${ws.workspace_name}`}
          className="h-7 w-20 rounded border border-input bg-transparent px-1 text-right text-xs"
          onBlur={(e) => {
            const v = Number(e.target.value);
            if (v !== ws.send_rate_clamp) clamp.mutate(v);
          }}
        />
      </td>
      <td className="text-right">
        <Button
          size="sm"
          variant={ws.suspended ? 'outline' : 'destructive'}
          disabled={suspend.isPending}
          onClick={() => suspend.mutate()}
        >
          {ws.suspended ? 'Unsuspend' : 'Suspend'}
        </Button>
      </td>
    </tr>
  );
}

/** Platform superadmin console (P5): cross-workspace list + abuse controls.
 * Guarded by adminWhoami() — non-operators are redirected to the inbox. */
export default function AdminPage(): React.JSX.Element {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const admin = useQuery({ queryKey: ['admin-whoami'], queryFn: () => client.adminWhoami() });
  const workspaces = useQuery({
    queryKey: ['admin-workspaces', search],
    queryFn: () => client.adminListWorkspaces(search || undefined),
    enabled: admin.data === true,
  });

  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['admin-workspaces'] });
  };

  if (admin.isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  }
  if (admin.data !== true) {
    return <Navigate to="/inbox" replace />;
  }

  return (
    <div className="p-6" data-testid="admin-page">
      <h1 className="mb-1 text-xl font-semibold">Platform Admin</h1>
      <p className="mb-4 text-sm text-muted-foreground">
        Every workspace on the platform. Suspend abusers (read-only + no sends) or clamp a
        workspace's daily outbound volume. Actions are audited.
      </p>

      <Input
        aria-label="Search workspaces"
        placeholder="Search workspaces…"
        className="mb-3 max-w-sm"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {workspaces.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorText(workspaces.error)}
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="py-1.5 font-medium">Workspace</th>
              <th className="font-medium">Subscription</th>
              <th className="text-right font-medium">Members</th>
              <th className="text-right font-medium">Messages</th>
              <th className="text-center font-medium">Status</th>
              <th className="text-right font-medium">Clamp/day</th>
              <th className="text-right font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {(workspaces.data ?? []).map((ws) => (
              <WorkspaceRow key={ws.name} ws={ws} onChange={refresh} />
            ))}
          </tbody>
        </table>
        {workspaces.data?.length === 0 && (
          <p className="mt-3 text-sm text-muted-foreground">No workspaces found.</p>
        )}
      </div>
    </div>
  );
}
