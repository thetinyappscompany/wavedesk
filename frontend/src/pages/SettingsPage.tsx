import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Pencil, Trash2 } from 'lucide-react';
import type { WdCannedResponse, WdLabel } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import InvitePanel from '@/components/InvitePanel';
import MonitoringCard from '@/components/MonitoringCard';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const DEFAULT_COLOR = '#1f93ff';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

function LabelsCard({ canManage }: { canManage: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const labels = useQuery({ queryKey: ['labels'], queryFn: () => client.listLabels() });
  const [editing, setEditing] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [color, setColor] = useState(DEFAULT_COLOR);

  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['labels'] });
    void queryClient.invalidateQueries({ queryKey: ['chats'] });
    setEditing(null);
    setTitle('');
    setColor(DEFAULT_COLOR);
  };
  const save = useMutation({
    mutationFn: () =>
      editing
        ? client.updateLabel(editing, { title, color })
        : client.createLabel(title, color),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (name: string) => client.deleteLabel(name),
    onSuccess: refresh,
  });

  const startEdit = (label: WdLabel): void => {
    setEditing(label.name);
    setTitle(label.title);
    setColor(label.color);
  };

  return (
    <section aria-label="Labels" className="rounded-lg border p-4">
      <h2 className="font-semibold">Labels</h2>
      <p className="mb-3 text-sm text-muted-foreground">
        Tag conversations for filtering and saved views. Lowercase letters, digits, - and _.
      </p>
      <ul className="mb-3 space-y-1">
        {(labels.data ?? []).map((label) => (
          <li
            key={label.name}
            data-testid="label-row"
            className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-accent"
          >
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: label.color }}
            />
            <span className="flex-1 truncate">{label.title}</span>
            {canManage && (
              <>
                <button
                  type="button"
                  aria-label={`Edit label ${label.title}`}
                  className="rounded p-1 text-muted-foreground hover:bg-background"
                  onClick={() => {
                    startEdit(label);
                  }}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  aria-label={`Delete label ${label.title}`}
                  className="rounded p-1 text-destructive hover:bg-background"
                  onClick={() => {
                    remove.mutate(label.name);
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </li>
        ))}
        {labels.data?.length === 0 && (
          <li className="px-2 py-1 text-sm text-muted-foreground">No labels yet.</li>
        )}
      </ul>
      {canManage && (
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim()) {
              save.mutate();
            }
          }}
        >
          <Input
            aria-label="Label title"
            placeholder="e.g. vip-lead"
            value={title}
            onChange={(e) => {
              setTitle(e.target.value);
            }}
          />
          <input
            aria-label="Label color"
            type="color"
            value={color}
            onChange={(e) => {
              setColor(e.target.value);
            }}
            className="h-9 w-9 shrink-0 cursor-pointer rounded-md border border-input bg-transparent p-1"
          />
          <Button type="submit" disabled={!title.trim() || save.isPending}>
            {editing ? 'Save' : 'Add'}
          </Button>
          {editing && (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setEditing(null);
                setTitle('');
                setColor(DEFAULT_COLOR);
              }}
            >
              Cancel
            </Button>
          )}
        </form>
      )}
      {save.isError && (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {errorText(save.error)}
        </p>
      )}
    </section>
  );
}

function CannedCard({ canManage }: { canManage: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const canned = useQuery({ queryKey: ['canned'], queryFn: () => client.listCanned() });
  const [editing, setEditing] = useState<string | null>(null);
  const [shortcode, setShortcode] = useState('');
  const [content, setContent] = useState('');

  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['canned'] });
    void queryClient.invalidateQueries({ queryKey: ['canned-search'] });
    setEditing(null);
    setShortcode('');
    setContent('');
  };
  const save = useMutation({
    mutationFn: () =>
      editing
        ? client.updateCanned(editing, { shortcode, content })
        : client.createCanned(shortcode, content),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (name: string) => client.deleteCanned(name),
    onSuccess: refresh,
  });

  const startEdit = (row: WdCannedResponse): void => {
    setEditing(row.name);
    setShortcode(row.shortcode);
    setContent(row.content);
  };

  return (
    <section aria-label="Canned responses" className="rounded-lg border p-4">
      <h2 className="font-semibold">Canned responses</h2>
      <p className="mb-3 text-sm text-muted-foreground">
        Type / in the composer to insert one. Variables like {'{{contact.name}}'} fill in at
        insert time.
      </p>
      <ul className="mb-3 space-y-1">
        {(canned.data ?? []).map((row) => (
          <li
            key={row.name}
            data-testid="canned-row"
            className="flex items-baseline gap-2 rounded px-2 py-1 text-sm hover:bg-accent"
          >
            <span className="shrink-0 font-mono text-xs text-primary">/{row.shortcode}</span>
            <span className="flex-1 truncate text-muted-foreground">{row.content}</span>
            {canManage && (
              <>
                <button
                  type="button"
                  aria-label={`Edit canned response ${row.shortcode}`}
                  className="rounded p-1 text-muted-foreground hover:bg-background"
                  onClick={() => {
                    startEdit(row);
                  }}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  aria-label={`Delete canned response ${row.shortcode}`}
                  className="rounded p-1 text-destructive hover:bg-background"
                  onClick={() => {
                    remove.mutate(row.name);
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </li>
        ))}
        {canned.data?.length === 0 && (
          <li className="px-2 py-1 text-sm text-muted-foreground">No canned responses yet.</li>
        )}
      </ul>
      {canManage && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (shortcode.trim() && content.trim()) {
              save.mutate();
            }
          }}
        >
          <Input
            aria-label="Canned shortcode"
            placeholder="e.g. greet"
            value={shortcode}
            onChange={(e) => {
              setShortcode(e.target.value);
            }}
          />
          <textarea
            aria-label="Canned content"
            placeholder="Namaste {{contact.name}}! How can we help?"
            value={content}
            rows={3}
            onChange={(e) => {
              setContent(e.target.value);
            }}
            className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          <div className="flex gap-2">
            <Button
              type="submit"
              disabled={!shortcode.trim() || !content.trim() || save.isPending}
            >
              {editing ? 'Save' : 'Add'}
            </Button>
            {editing && (
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setEditing(null);
                  setShortcode('');
                  setContent('');
                }}
              >
                Cancel
              </Button>
            )}
          </div>
        </form>
      )}
      {save.isError && (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {errorText(save.error)}
        </p>
      )}
    </section>
  );
}

export default function SettingsPage(): React.JSX.Element {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ['workspace-settings'],
    queryFn: () => client.getWorkspaceSettings(),
  });
  // system users report role null and hold every right server-side
  const canManage = settings.data ? settings.data.role !== 'Agent' : false;

  const toggleMask = useMutation({
    mutationFn: (maskNumbers: boolean) =>
      client.updateWorkspaceSettings({ mask_numbers: maskNumbers }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['workspace-settings'] });
      void queryClient.invalidateQueries({ queryKey: ['chats'] });
      void queryClient.invalidateQueries({ queryKey: ['contacts'] });
    },
  });
  const saveThreshold = useMutation({
    mutationFn: (minutes: number) =>
      client.updateWorkspaceSettings({ needs_reply_minutes: minutes }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['workspace-settings'] });
      void queryClient.invalidateQueries({ queryKey: ['chats'] });
      void queryClient.invalidateQueries({ queryKey: ['groups'] });
    },
  });

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-6">
      <div>
        <h1 className="text-lg font-semibold">Settings</h1>
        {settings.data?.workspace_name && (
          <p className="text-sm text-muted-foreground">{settings.data.workspace_name}</p>
        )}
      </div>

      <section aria-label="Privacy" className="rounded-lg border p-4">
        <h2 className="font-semibold">Privacy</h2>
        <label className="mt-2 flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            aria-label="Mask customer numbers for agents"
            className="mt-0.5"
            checked={settings.data?.mask_numbers ?? false}
            disabled={!canManage || toggleMask.isPending}
            onChange={(e) => {
              toggleMask.mutate(e.target.checked);
            }}
          />
          <span>
            Mask customer numbers for agents
            <span className="block text-xs text-muted-foreground">
              Agents see +91••••••1234 instead of full numbers. Owners and admins always see
              full numbers; sending still uses the real number.
            </span>
          </span>
        </label>
        {toggleMask.isError && (
          <p role="alert" className="mt-2 text-xs text-destructive">
            {errorText(toggleMask.error)}
          </p>
        )}
      </section>

      <section aria-label="Inbox rules" className="rounded-lg border p-4">
        <h2 className="font-semibold">Inbox rules</h2>
        <label className="mt-2 block text-sm" htmlFor="needs-reply-minutes">
          Needs Reply after (minutes)
          <span className="block text-xs text-muted-foreground">
            An unanswered question in a group enters the Needs Reply queue after this long.
          </span>
        </label>
        <div className="mt-2 flex items-center gap-2">
          <Input
            id="needs-reply-minutes"
            type="number"
            min={1}
            max={1440}
            className="w-24"
            key={settings.data?.needs_reply_minutes}
            defaultValue={settings.data?.needs_reply_minutes ?? 10}
            disabled={!canManage}
            onBlur={(e) => {
              const minutes = Number(e.target.value);
              if (
                canManage &&
                minutes >= 1 &&
                minutes <= 1440 &&
                minutes !== settings.data?.needs_reply_minutes
              ) {
                saveThreshold.mutate(minutes);
              }
            }}
          />
          <span className="text-xs text-muted-foreground">minutes</span>
        </div>
        {saveThreshold.isError && (
          <p role="alert" className="mt-2 text-xs text-destructive">
            {errorText(saveThreshold.error)}
          </p>
        )}
      </section>

      <section aria-label="Team" className="rounded-lg border p-4">
        <h2 className="mb-3 font-semibold">Team</h2>
        <InvitePanel canManage={canManage} />
      </section>

      <MonitoringCard canManage={canManage} />
      <LabelsCard canManage={canManage} />
      <CannedCard canManage={canManage} />
    </div>
  );
}
