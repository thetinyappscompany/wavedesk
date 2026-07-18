import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, X } from 'lucide-react';
import type { WdContactProfile } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

function timeLabel(value: string | null): string {
  if (!value) {
    return '';
  }
  return new Date(value.replace(' ', 'T')).toLocaleDateString([], {
    day: '2-digit',
    month: 'short',
  });
}

function AttributeEditor({
  attributes,
  onSave,
  saving,
}: {
  attributes: Record<string, string>;
  onSave: (next: Record<string, string>) => void;
  saving: boolean;
}): React.JSX.Element {
  const [newKey, setNewKey] = useState('');
  const [newValue, setNewValue] = useState('');

  const addAttribute = (): void => {
    const key = newKey.trim();
    if (!key) {
      return;
    }
    onSave({ ...attributes, [key]: newValue.trim() });
    setNewKey('');
    setNewValue('');
  };

  return (
    <div className="space-y-1">
      {Object.entries(attributes).map(([key, value]) => (
        <div key={key} className="flex items-center gap-1 text-sm">
          <span className="w-24 truncate text-muted-foreground" title={key}>
            {key}
          </span>
          <span className="min-w-0 flex-1 truncate" title={value}>
            {value}
          </span>
          <button
            type="button"
            aria-label={`Remove ${key}`}
            className="rounded p-0.5 text-muted-foreground hover:text-destructive"
            disabled={saving}
            onClick={() => {
              const next = { ...attributes };
              delete next[key];
              onSave(next);
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      <div className="flex items-center gap-1">
        <Input
          aria-label="Attribute name"
          placeholder="Attribute"
          className="h-7 w-24 text-xs"
          value={newKey}
          onChange={(e) => {
            setNewKey(e.target.value);
          }}
        />
        <Input
          aria-label="Attribute value"
          placeholder="Value"
          className="h-7 flex-1 text-xs"
          value={newValue}
          onChange={(e) => {
            setNewValue(e.target.value);
          }}
        />
        <Button
          aria-label="Add attribute"
          variant="outline"
          size="icon"
          className="h-7 w-7"
          disabled={!newKey.trim() || saving}
          onClick={addAttribute}
        >
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

/** Internal notes pinned to a contact (Chatwoot parity). */
function ContactNotes({ contactName }: { contactName: string }): React.JSX.Element {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState('');
  const notes = useQuery({
    queryKey: ['contact-notes', contactName],
    queryFn: () => client.listContactNotes(contactName),
  });
  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['contact-notes', contactName] });
  };
  const add = useMutation({
    mutationFn: () => client.addContactNote(contactName, draft.trim()),
    onSuccess: () => {
      setDraft('');
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (note: string) => client.deleteContactNote(note),
    onSuccess: refresh,
  });
  return (
    <section data-testid="contact-notes">
      <h4 className="mb-1 text-xs font-medium uppercase text-muted-foreground">Notes</h4>
      <div className="space-y-1">
        {(notes.data?.notes ?? []).map((note) => (
          <div
            key={note.name}
            data-testid="contact-note-row"
            className="rounded-md border border-amber-400/30 bg-amber-500/10 px-2 py-1.5 text-xs"
          >
            <div className="flex items-start justify-between gap-1">
              <p className="min-w-0 whitespace-pre-wrap break-words">{note.content}</p>
              <button
                type="button"
                aria-label="Delete note"
                className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-destructive"
                disabled={remove.isPending}
                onClick={() => {
                  remove.mutate(note.name);
                }}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
            <p className="mt-0.5 text-[10px] text-muted-foreground">
              {note.author_name ?? 'Unknown'} · {timeLabel(note.creation)}
            </p>
          </div>
        ))}
        {notes.data?.notes.length === 0 && (
          <p className="text-xs text-muted-foreground">No notes yet.</p>
        )}
        <div className="flex items-center gap-1">
          <Input
            aria-label="New contact note"
            placeholder="Add a note…"
            className="h-7 flex-1 text-xs"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && draft.trim() && !add.isPending) {
                add.mutate();
              }
            }}
          />
          <Button
            aria-label="Add note"
            variant="outline"
            size="icon"
            className="h-7 w-7"
            disabled={!draft.trim() || add.isPending}
            onClick={() => {
              add.mutate();
            }}
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>
        {remove.isError && (
          <p role="alert" className="text-xs text-destructive">
            Could not delete — only the author or a manager may delete a note.
          </p>
        )}
      </div>
    </section>
  );
}

/** Right-hand contact profile drawer (Phase 1 feature 4): editable
 * name/email, custom attributes, and every conversation with this
 * contact across all connected numbers. */
export default function ContactDrawer({
  contactName,
  activeChat,
  onOpenChat,
  onClose,
}: {
  contactName: string;
  activeChat: string | null;
  onOpenChat: (chat: string) => void;
  onClose: () => void;
}): React.JSX.Element {
  const queryClient = useQueryClient();
  const profile = useQuery({
    queryKey: ['contact', contactName],
    queryFn: () => client.getContact(contactName),
  });

  const [draftName, setDraftName] = useState('');
  const [draftEmail, setDraftEmail] = useState('');
  useEffect(() => {
    if (profile.data) {
      setDraftName(profile.data.full_name ?? '');
      setDraftEmail(profile.data.email ?? '');
    }
  }, [profile.data]);

  const update = useMutation({
    mutationFn: (changes: Parameters<typeof client.updateContact>[1]) =>
      client.updateContact(contactName, changes),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['contact', contactName] });
      void queryClient.invalidateQueries({ queryKey: ['chats'] });
      void queryClient.invalidateQueries({ queryKey: ['contacts'] });
    },
  });

  const [confirmErase, setConfirmErase] = useState(false);
  const erase = useMutation({
    mutationFn: () => client.eraseContact(contactName),
    onSuccess: () => {
      setConfirmErase(false);
      void queryClient.invalidateQueries({ queryKey: ['contact', contactName] });
      void queryClient.invalidateQueries({ queryKey: ['contacts'] });
    },
  });

  const data: WdContactProfile | undefined = profile.data;
  const dirty =
    data && (draftName !== (data.full_name ?? '') || draftEmail !== (data.email ?? ''));

  return (
    <aside
      data-testid="contact-drawer"
      className="flex w-72 shrink-0 flex-col border-l bg-muted/20"
    >
      <header className="flex items-center justify-between border-b px-3 py-3">
        <h3 className="text-sm font-semibold">Contact</h3>
        <button
          type="button"
          aria-label="Close contact drawer"
          className="rounded p-1 text-muted-foreground hover:bg-accent"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
        {profile.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {profile.isError && (
          <p role="alert" className="text-sm text-destructive">
            Failed to load contact.
          </p>
        )}
        {data && (
          <>
            <section className="space-y-2">
              <Input
                aria-label="Contact name"
                placeholder="Name"
                value={draftName}
                onChange={(e) => {
                  setDraftName(e.target.value);
                }}
              />
              <p className="px-1 text-sm text-muted-foreground">+{data.phone}</p>
              <Input
                aria-label="Contact email"
                placeholder="Email"
                value={draftEmail}
                onChange={(e) => {
                  setDraftEmail(e.target.value);
                }}
              />
              {dirty && (
                <Button
                  size="sm"
                  className="w-full"
                  disabled={update.isPending}
                  onClick={() => {
                    update.mutate({ full_name: draftName, email: draftEmail });
                  }}
                >
                  Save
                </Button>
              )}
              {update.isError && (
                <p role="alert" className="text-xs text-destructive">
                  {update.error.message.includes('409') ||
                  update.error.message.toLowerCase().includes('duplicate')
                    ? 'Another contact already uses that email.'
                    : 'Could not save — check the values.'}
                </p>
              )}
            </section>

            <section>
              <h4 className="mb-1 text-xs font-medium uppercase text-muted-foreground">
                Attributes
              </h4>
              <AttributeEditor
                attributes={data.custom_attributes}
                saving={update.isPending}
                onSave={(next) => {
                  update.mutate({ custom_attributes: next });
                }}
              />
            </section>

            <ContactNotes contactName={contactName} />

            <section>
              <h4 className="mb-1 text-xs font-medium uppercase text-muted-foreground">
                Conversations
              </h4>
              <div className="space-y-1">
                {data.chats.map((chat) => (
                  <button
                    key={chat.name}
                    type="button"
                    data-testid="contact-chat-row"
                    onClick={() => {
                      onOpenChat(chat.name);
                    }}
                    className={cn(
                      'flex w-full items-center justify-between rounded-md border px-2 py-1.5 text-left text-xs hover:bg-accent',
                      chat.name === activeChat && 'border-primary/50 bg-accent',
                    )}
                  >
                    <span className="min-w-0 truncate">
                      {chat.number_name ?? chat.number_phone ?? 'Unknown number'}
                      <span className="ml-1 text-muted-foreground">· {chat.status}</span>
                    </span>
                    <span className="ml-2 shrink-0 text-muted-foreground">
                      {timeLabel(chat.last_message_at)}
                    </span>
                  </button>
                ))}
                {data.chats.length === 0 && (
                  <p className="text-xs text-muted-foreground">No conversations yet.</p>
                )}
              </div>
            </section>

            <section className="border-t pt-3" data-testid="contact-erase">
              <h4 className="mb-1 text-xs font-medium uppercase text-destructive">Right to erasure</h4>
              <p className="mb-2 text-xs text-muted-foreground">
                Permanently scrubs this contact's name, phone, email, and message content
                (DPDP/GDPR). This can't be undone.
              </p>
              {confirmErase ? (
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={erase.isPending}
                    onClick={() => erase.mutate()}
                  >
                    Confirm erase
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setConfirmErase(false)}>
                    Cancel
                  </Button>
                </div>
              ) : (
                <Button size="sm" variant="outline" onClick={() => setConfirmErase(true)}>
                  Erase contact (GDPR)
                </Button>
              )}
              {erase.isError && (
                <p role="alert" className="mt-1 text-xs text-destructive">
                  {erase.error instanceof Error ? erase.error.message : 'Erase failed'}
                </p>
              )}
            </section>
          </>
        )}
      </div>
    </aside>
  );
}
