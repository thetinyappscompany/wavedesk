import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Navigate } from 'react-router';
import type {
  WdAdminUser,
  WdAdminWorkspace,
  WdPasswordResetIssued,
  WdPlatformStats,
} from '@wavedesk/api-client';

import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

function StatCard({ label, value }: { label: string; value: number }): React.JSX.Element {
  return (
    <div className="rounded-lg border bg-card px-3 py-2" data-testid="admin-stat">
      <div className="text-lg font-semibold tabular-nums">{value.toLocaleString()}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

/** SaaS-provider overview strip: platform totals + status/plan breakdowns. */
function PlatformOverview({ stats }: { stats: WdPlatformStats }): React.JSX.Element {
  const { totals, trial_vs_paid, operational, by_plan } = stats;
  return (
    <div className="mb-5" data-testid="admin-overview">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard label="Workspaces" value={totals.workspaces} />
        <StatCard label="Users" value={totals.users} />
        <StatCard label="Messages" value={totals.messages} />
        <StatCard label="Contacts" value={totals.contacts} />
        <StatCard label="Numbers" value={totals.numbers} />
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>
          <span className="font-medium text-emerald-600">{trial_vs_paid.paid}</span> paid
        </span>
        <span>
          <span className="font-medium text-foreground">{trial_vs_paid.trial}</span> trial
        </span>
        <span>
          <span className="font-medium text-amber-600">{trial_vs_paid.past_due}</span> past due
        </span>
        <span>
          <span className="font-medium text-destructive">{operational.suspended}</span> suspended
        </span>
        <span className="text-border">|</span>
        {by_plan.map((p) => (
          <span key={p.plan}>
            {p.plan}: <span className="font-medium text-foreground">{p.count}</span>
          </span>
        ))}
      </div>
    </div>
  );
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
  const [creditAmount, setCreditAmount] = useState('');
  const credit = useMutation({
    // one idempotency key per submit — a network retry can never double-credit
    mutationFn: (amount: number) =>
      client.adminCreditWallet(ws.name, amount, 'admin panel top-up', crypto.randomUUID()),
    onSuccess: () => {
      setCreditAmount('');
      onChange();
    },
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
        <div className="flex items-center justify-end gap-1">
          <input
            type="number"
            min={1}
            placeholder="₹"
            value={creditAmount}
            aria-label={`Credit wallet for ${ws.workspace_name}`}
            className="h-7 w-20 rounded border border-input bg-transparent px-1 text-right text-xs"
            onChange={(e) => {
              setCreditAmount(e.target.value);
            }}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={credit.isPending || Number(creditAmount) <= 0}
            onClick={() => credit.mutate(Number(creditAmount))}
          >
            Credit
          </Button>
        </div>
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

function UserRow({ user }: { user: WdAdminUser }): React.JSX.Element {
  const [issued, setIssued] = useState<WdPasswordResetIssued | null>(null);
  const sendReset = useMutation({
    mutationFn: () => client.adminSendPasswordReset(user.name),
    onSuccess: setIssued,
  });

  return (
    <tr className="border-b align-top" data-testid="admin-user-row">
      <td className="py-1.5">
        <div className="font-medium">{user.full_name ?? user.email}</div>
        <div className="text-xs text-muted-foreground">{user.email}</div>
        {issued && (
          <div className="mt-1 text-xs" data-testid="reset-result">
            {issued.delivered ? (
              <span className="text-emerald-600">
                Reset link emailed — expires in {issued.expires_in_minutes} min.
              </span>
            ) : (
              <div className="grid gap-1">
                <span className="text-amber-600">
                  Email isn&apos;t configured, so nothing was sent. Hand this link over
                  yourself — it works once:
                </span>
                <input
                  readOnly
                  aria-label={`Reset link for ${user.email}`}
                  value={issued.link ?? ''}
                  className="w-full rounded border border-input bg-muted px-1 py-0.5 font-mono text-[11px]"
                  onFocus={(e) => {
                    e.target.select();
                  }}
                />
              </div>
            )}
          </div>
        )}
      </td>
      <td className="text-xs">
        {user.workspaces.length === 0 ? (
          <span className="text-muted-foreground">no workspace</span>
        ) : (
          user.workspaces.map((w) => (
            <div key={`${w.workspace_name}-${w.role}`}>
              {w.workspace_name} <span className="text-muted-foreground">({w.role})</span>
            </div>
          ))
        )}
      </td>
      <td className="text-center text-xs">
        {user.is_platform_admin && (
          <span className="rounded bg-primary/15 px-1.5 text-primary">admin</span>
        )}
        {!user.enabled && (
          <span className="ml-1 rounded bg-destructive/15 px-1.5 text-destructive">
            disabled
          </span>
        )}
      </td>
      <td className="text-right">
        <Button
          size="sm"
          variant="outline"
          disabled={sendReset.isPending}
          onClick={() => sendReset.mutate()}
        >
          {sendReset.isPending ? 'Sending…' : 'Send reset link'}
        </Button>
        {sendReset.isError && (
          <p role="alert" className="text-xs text-destructive">
            {errorText(sendReset.error)}
          </p>
        )}
      </td>
    </tr>
  );
}

/** Every account on the platform + operator-triggered password recovery. The
 * link always goes to the user's own inbox — the operator never sees or sets a
 * password (the only exception is when SMTP isn't configured yet). */
function UsersPanel(): React.JSX.Element {
  const [search, setSearch] = useState('');
  const users = useQuery({
    queryKey: ['admin-users', search],
    queryFn: () => client.adminListUsers(search || undefined),
  });

  return (
    <section className="mt-8" data-testid="admin-users">
      <h2 className="mb-1 text-lg font-semibold">Accounts</h2>
      <p className="mb-3 text-sm text-muted-foreground">
        Every user on the platform. &ldquo;Send reset link&rdquo; emails a single-use
        recovery link to that person — it never reveals or changes their password.
      </p>
      <Input
        aria-label="Search accounts"
        placeholder="Search by name or email…"
        className="mb-3 max-w-sm"
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
        }}
      />
      {users.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorText(users.error)}
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="py-1.5 font-medium">User</th>
              {/* not "Workspaces" — that label already names the section above */}
              <th className="font-medium">Member of</th>
              <th className="text-center font-medium">Flags</th>
              <th className="text-right font-medium">Recovery</th>
            </tr>
          </thead>
          <tbody>
            {(users.data ?? []).map((u) => (
              <UserRow key={u.name} user={u} />
            ))}
          </tbody>
        </table>
        {users.data?.length === 0 && (
          <p className="mt-3 text-sm text-muted-foreground">No accounts found.</p>
        )}
      </div>
    </section>
  );
}

/** Platform superadmin console (P5): cross-workspace list + abuse controls.
 * Guarded by adminWhoami() — non-operators are redirected to the inbox. */
export default function AdminPage(): React.JSX.Element {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const admin = useQuery({ queryKey: ['admin-whoami'], queryFn: () => client.adminWhoami() });
  const stats = useQuery({
    queryKey: ['admin-platform-stats'],
    queryFn: () => client.adminPlatformStats(),
    enabled: admin.data === true,
  });
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

      {stats.data && <PlatformOverview stats={stats.data} />}

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
              <th className="text-right font-medium">Wallet</th>
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

      <UsersPanel />
    </div>
  );
}
