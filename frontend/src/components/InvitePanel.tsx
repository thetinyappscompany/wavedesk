import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, X } from 'lucide-react';
import type { WdInvite } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

/** Members list + pending invites + invite-by-email form. Used by the
 * onboarding wizard (step 3) and the Settings page — same behavior. */
export default function InvitePanel({ canManage }: { canManage: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const members = useQuery({ queryKey: ['members'], queryFn: () => client.listMembers() });
  const invites = useQuery({
    queryKey: ['invites'],
    queryFn: () => client.listInvites(),
    enabled: canManage, // the invite link is a secret — managers only
  });
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<WdInvite['role']>('Agent');
  const [copied, setCopied] = useState<string | null>(null);

  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['invites'] });
    void queryClient.invalidateQueries({ queryKey: ['members'] });
  };
  const invite = useMutation({
    mutationFn: () => client.inviteMember(email.trim(), role),
    onSuccess: () => {
      setEmail('');
      refresh();
    },
  });
  const revoke = useMutation({
    mutationFn: (name: string) => client.revokeInvite(name),
    onSuccess: refresh,
  });

  const copyLink = (row: WdInvite): void => {
    void navigator.clipboard?.writeText(row.invite_url).then(() => {
      setCopied(row.name);
      setTimeout(() => {
        setCopied(null);
      }, 2000);
    });
  };

  return (
    <div>
      <h3 className="text-sm font-medium text-muted-foreground">Members</h3>
      <ul className="mb-3 mt-1 space-y-1">
        {(members.data ?? []).map((member) => (
          <li
            key={member.user}
            data-testid="member-row"
            className="flex items-center gap-2 rounded px-2 py-1 text-sm"
          >
            <span className="flex-1 truncate">{member.full_name ?? member.user}</span>
            <span className="rounded border px-1.5 text-xs text-muted-foreground">
              {member.role}
            </span>
          </li>
        ))}
      </ul>

      {canManage && (
        <>
          {(invites.data?.length ?? 0) > 0 && (
            <>
              <h3 className="text-sm font-medium text-muted-foreground">Pending invites</h3>
              <ul className="mb-3 mt-1 space-y-1">
                {(invites.data ?? []).map((row) => (
                  <li
                    key={row.name}
                    data-testid="invite-row"
                    className="flex items-center gap-2 rounded px-2 py-1 text-sm"
                  >
                    <span className="flex-1 truncate">{row.email}</span>
                    <span className="rounded border px-1.5 text-xs text-muted-foreground">
                      {row.role}
                    </span>
                    <button
                      type="button"
                      aria-label={`Copy invite link for ${row.email}`}
                      className="rounded p-1 text-muted-foreground hover:bg-accent"
                      onClick={() => {
                        copyLink(row);
                      }}
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </button>
                    {copied === row.name && <span className="text-xs text-primary">Copied</span>}
                    <button
                      type="button"
                      aria-label={`Revoke invite for ${row.email}`}
                      className="rounded p-1 text-destructive hover:bg-accent"
                      onClick={() => {
                        revoke.mutate(row.name);
                      }}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (email.trim()) {
                invite.mutate();
              }
            }}
          >
            <Input
              aria-label="Invite email"
              type="email"
              placeholder="teammate@company.com"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
              }}
            />
            <select
              aria-label="Invite role"
              value={role}
              onChange={(e) => {
                setRole(e.target.value as WdInvite['role']);
              }}
              className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
            >
              <option value="Agent">Agent</option>
              <option value="Admin">Admin</option>
            </select>
            <Button type="submit" disabled={!email.trim() || invite.isPending}>
              Invite
            </Button>
          </form>
          {invite.isError && (
            <p role="alert" className="mt-2 text-xs text-destructive">
              {invite.error.message}
            </p>
          )}
          <p className="mt-2 text-xs text-muted-foreground">
            Invitees get an email with a 7-day link — or copy the link and share it yourself.
          </p>
        </>
      )}
    </div>
  );
}
