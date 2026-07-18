import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, Zap } from 'lucide-react';
import type { WdMacroAction, WdMacroActionType } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const ACTION_LABELS: Record<WdMacroActionType, string> = {
  set_status: 'Set status',
  set_priority: 'Set priority',
  assign_agent: 'Assign agent (id)',
  assign_team: 'Assign team (id)',
  add_label: 'Add label',
  send_message: 'Send message',
  add_private_note: 'Add private note',
};

const VALUE_PLACEHOLDER: Record<WdMacroActionType, string> = {
  set_status: 'open | pending | resolved',
  set_priority: 'low | medium | high | urgent',
  assign_agent: 'agent user id',
  assign_team: 'team id',
  add_label: 'label title',
  send_message: 'message text',
  add_private_note: 'note text',
};

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : 'Something went wrong';
}

/** Settings card: create/delete one-click macros (Chatwoot parity). Agents
 * manage their own personal macros; managers can publish global ones. */
export function MacrosCard({ canManage }: { canManage: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const macros = useQuery({ queryKey: ['macros'], queryFn: () => client.listMacros() });

  const [name, setName] = useState('');
  const [visibility, setVisibility] = useState<'personal' | 'global'>(
    canManage ? 'global' : 'personal',
  );
  const [actions, setActions] = useState<WdMacroAction[]>([{ type: 'set_status', value: '' }]);

  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['macros'] });
  };
  const create = useMutation({
    mutationFn: () => client.createMacro(name.trim(), actions, visibility),
    onSuccess: () => {
      setName('');
      setActions([{ type: 'set_status', value: '' }]);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (macro: string) => client.deleteMacro(macro),
    onSuccess: refresh,
  });

  const setAction = (index: number, patch: Partial<WdMacroAction>): void => {
    setActions((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  return (
    <section aria-label="Macros" className="rounded-lg border p-4">
      <h2 className="inline-flex items-center gap-1.5 font-semibold">
        <Zap className="h-4 w-4" /> Macros
      </h2>
      <p className="text-xs text-muted-foreground">
        One-click action bundles agents run on a conversation (assign, label, reply, note).
      </p>

      <div className="mt-3 space-y-1">
        {(macros.data?.macros ?? []).map((macro) => (
          <div
            key={macro.name}
            data-testid="macro-row"
            className="flex items-center justify-between gap-2 rounded-md border px-2 py-1.5 text-sm"
          >
            <div className="min-w-0">
              <span className="font-medium">{macro.macro_name}</span>
              <span className="ml-2 text-xs text-muted-foreground">
                {macro.visibility} · {macro.actions.length} action
                {macro.actions.length === 1 ? '' : 's'} · run {macro.run_count}×
              </span>
            </div>
            <button
              type="button"
              aria-label={`Delete macro ${macro.macro_name}`}
              className="shrink-0 rounded p-1 text-muted-foreground hover:text-destructive"
              disabled={remove.isPending}
              onClick={() => {
                remove.mutate(macro.name);
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        {macros.data?.macros.length === 0 && (
          <p className="text-xs text-muted-foreground">No macros yet.</p>
        )}
      </div>

      <div className="mt-4 space-y-2 border-t pt-3">
        <div className="flex items-center gap-2">
          <Input
            aria-label="Macro name"
            placeholder="Macro name (e.g. VIP intake)"
            className="h-8 flex-1 text-sm"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
          <select
            aria-label="Macro visibility"
            className="h-8 rounded-md border border-input bg-transparent px-2 text-xs"
            value={visibility}
            onChange={(e) => {
              setVisibility(e.target.value as 'personal' | 'global');
            }}
          >
            <option value="personal">Personal</option>
            {canManage && <option value="global">Everyone</option>}
          </select>
        </div>
        {actions.map((action, index) => (
          <div key={index} className="flex items-center gap-1">
            <select
              aria-label={`Action ${String(index + 1)} type`}
              className="h-8 w-44 rounded-md border border-input bg-transparent px-2 text-xs"
              value={action.type}
              onChange={(e) => {
                setAction(index, { type: e.target.value as WdMacroActionType, value: '' });
              }}
            >
              {(Object.keys(ACTION_LABELS) as WdMacroActionType[]).map((type) => (
                <option key={type} value={type}>
                  {ACTION_LABELS[type]}
                </option>
              ))}
            </select>
            <Input
              aria-label={`Action ${String(index + 1)} value`}
              placeholder={VALUE_PLACEHOLDER[action.type]}
              className="h-8 flex-1 text-xs"
              value={action.value ?? ''}
              onChange={(e) => {
                setAction(index, { value: e.target.value });
              }}
            />
            <button
              type="button"
              aria-label={`Remove action ${String(index + 1)}`}
              className="rounded p-1 text-muted-foreground hover:text-destructive"
              disabled={actions.length === 1}
              onClick={() => {
                setActions((rows) => rows.filter((_, i) => i !== index));
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setActions((rows) => [...rows, { type: 'set_status', value: '' }]);
            }}
          >
            <Plus className="mr-1 h-3.5 w-3.5" /> Add action
          </Button>
          <Button
            size="sm"
            disabled={!name.trim() || create.isPending}
            onClick={() => {
              create.mutate();
            }}
          >
            Create macro
          </Button>
        </div>
        {create.isError && (
          <p role="alert" className="text-xs text-destructive">
            {errorText(create.error)}
          </p>
        )}
      </div>
    </section>
  );
}
