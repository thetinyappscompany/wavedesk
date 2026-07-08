import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowDownCircle, ArrowUpCircle, Copy, RefreshCcw, UserMinus, X } from 'lucide-react';
import type { WdParticipantAction } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

/** Group detail drawer (P2.3): metadata edit, invite link management, and
 * participant actions — every action is audit-logged server-side. */
export default function GroupDrawer({
  groupName,
  canManage,
  onClose,
}: {
  groupName: string;
  canManage: boolean;
  onClose: () => void;
}): React.JSX.Element {
  const queryClient = useQueryClient();
  const group = useQuery({
    queryKey: ['group', groupName],
    queryFn: () => client.getGroup(groupName),
  });

  const [subject, setSubject] = useState('');
  const [description, setDescription] = useState('');
  const [newParticipant, setNewParticipant] = useState('');
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (group.data) {
      setSubject(group.data.subject);
      setDescription(group.data.description ?? '');
    }
  }, [group.data]);

  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['group', groupName] });
    void queryClient.invalidateQueries({ queryKey: ['groups'] });
  };
  const saveMeta = useMutation({
    mutationFn: () =>
      client.updateGroup(groupName, {
        ...(subject.trim() !== group.data?.subject ? { subject: subject.trim() } : {}),
        ...(description.trim() !== (group.data?.description ?? '')
          ? { description: description.trim() }
          : {}),
      }),
    onSuccess: refresh,
  });
  const participants = useMutation({
    mutationFn: (change: { targets: string[]; action: WdParticipantAction }) =>
      client.groupParticipants(groupName, change.targets, change.action),
    onSuccess: refresh,
  });
  const revoke = useMutation({
    mutationFn: () => client.revokeGroupInvite(groupName),
    onSuccess: refresh,
  });

  const dirty =
    group.data !== undefined &&
    (subject.trim() !== group.data.subject ||
      description.trim() !== (group.data.description ?? ''));
  const actionError = saveMeta.error ?? participants.error ?? revoke.error;

  return (
    <aside
      data-testid="group-drawer"
      className="flex w-96 shrink-0 flex-col overflow-y-auto border-l bg-background"
    >
      <header className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="font-semibold">Group details</h2>
        <Button aria-label="Close group details" variant="ghost" size="icon" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </header>

      {group.isLoading && (
        <p className="p-4 text-sm text-muted-foreground">Loading group…</p>
      )}
      {group.isError && (
        <p role="alert" className="p-4 text-sm text-destructive">
          Failed to load the group.
        </p>
      )}

      {group.data && (
        <div className="space-y-5 p-4">
          <div className="space-y-2">
            <label className="block text-sm font-medium" htmlFor="group-subject">
              Subject
            </label>
            <Input
              id="group-subject"
              value={subject}
              disabled={!canManage}
              onChange={(e) => {
                setSubject(e.target.value);
              }}
            />
            <label className="block text-sm font-medium" htmlFor="group-description">
              Description
            </label>
            <textarea
              id="group-description"
              value={description}
              disabled={!canManage}
              rows={2}
              onChange={(e) => {
                setDescription(e.target.value);
              }}
              className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
            {canManage && (
              <Button
                size="sm"
                disabled={!dirty || !subject.trim() || saveMeta.isPending}
                onClick={() => {
                  saveMeta.mutate();
                }}
              >
                Save
              </Button>
            )}
          </div>

          <div>
            <h3 className="text-sm font-medium text-muted-foreground">Invite link</h3>
            {group.data.invite_link ? (
              <div className="mt-1 flex items-center gap-1">
                <span className="min-w-0 flex-1 truncate text-xs">{group.data.invite_link}</span>
                <button
                  type="button"
                  aria-label="Copy invite link"
                  className="rounded p-1 text-muted-foreground hover:bg-accent"
                  onClick={() => {
                    void navigator.clipboard?.writeText(group.data.invite_link ?? '').then(() => {
                      setCopied(true);
                      setTimeout(() => {
                        setCopied(false);
                      }, 2000);
                    });
                  }}
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
                {copied && <span className="text-xs text-primary">Copied</span>}
              </div>
            ) : (
              <p className="mt-1 text-xs text-muted-foreground">
                No link stored — available where our number is admin.
              </p>
            )}
            {canManage && group.data.owned_by_us && (
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                disabled={revoke.isPending}
                onClick={() => {
                  revoke.mutate();
                }}
              >
                <RefreshCcw className="mr-1 h-3.5 w-3.5" />
                Revoke &amp; regenerate
              </Button>
            )}
          </div>

          <div>
            <h3 className="text-sm font-medium text-muted-foreground">
              Members ({group.data.member_count})
            </h3>
            <ul className="mt-1 space-y-1">
              {group.data.members.map((member) => (
                <li
                  key={member.name}
                  data-testid="group-member-row"
                  className="flex items-center gap-2 rounded px-1 py-1 text-sm"
                >
                  <span className="min-w-0 flex-1 truncate">
                    {member.contact_name ?? member.display}
                  </span>
                  {member.role === 'admin' && (
                    <span className="rounded border px-1 text-[10px] text-muted-foreground">
                      admin
                    </span>
                  )}
                  {canManage && group.data?.owned_by_us && (
                    <>
                      <button
                        type="button"
                        aria-label={`${member.role === 'admin' ? 'Demote' : 'Promote'} ${member.display}`}
                        className="rounded p-1 text-muted-foreground hover:bg-accent"
                        onClick={() => {
                          participants.mutate({
                            targets: [member.display],
                            action: member.role === 'admin' ? 'demote' : 'promote',
                          });
                        }}
                      >
                        {member.role === 'admin' ? (
                          <ArrowDownCircle className="h-3.5 w-3.5" />
                        ) : (
                          <ArrowUpCircle className="h-3.5 w-3.5" />
                        )}
                      </button>
                      <button
                        type="button"
                        aria-label={`Remove ${member.display}`}
                        className="rounded p-1 text-destructive hover:bg-accent"
                        onClick={() => {
                          participants.mutate({ targets: [member.display], action: 'remove' });
                        }}
                      >
                        <UserMinus className="h-3.5 w-3.5" />
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
            {canManage && group.data.owned_by_us && (
              <form
                className="mt-2 flex items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (newParticipant.trim()) {
                    participants.mutate({ targets: [newParticipant.trim()], action: 'add' });
                    setNewParticipant('');
                  }
                }}
              >
                <Input
                  aria-label="Add participant phone"
                  placeholder="91XXXXXXXXXX"
                  value={newParticipant}
                  onChange={(e) => {
                    setNewParticipant(e.target.value);
                  }}
                />
                <Button type="submit" size="sm" disabled={!newParticipant.trim()}>
                  Add
                </Button>
              </form>
            )}
          </div>

          {actionError && (
            <p role="alert" className="text-xs text-destructive">
              {actionError.message}
            </p>
          )}
        </div>
      )}
    </aside>
  );
}
