import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import type { WdAiFlagRule } from '@wavedesk/api-client';

import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

/**
 * AI message flagging rules (P4.4): per-workspace custom flag prompts that run on
 * inbound messages via the mini-tier. Each rule flags the message and optionally
 * opens a ticket. Manager-only; runs only while the AI add-on is active.
 */
export default function AiFlaggingCard({ canManage }: { canManage: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const rules = useQuery({ queryKey: ['flag-rules'], queryFn: () => client.listFlagRules() });

  const [flagKey, setFlagKey] = useState('');
  const [label, setLabel] = useState('');
  const [prompt, setPrompt] = useState('');
  const [action, setAction] = useState<'flag' | 'ticket'>('flag');

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['flag-rules'] });

  const create = useMutation({
    mutationFn: () => client.createFlagRule(flagKey, prompt, { label, action }),
    onSuccess: () => {
      setFlagKey('');
      setLabel('');
      setPrompt('');
      setAction('flag');
      invalidate();
    },
  });
  const toggle = useMutation({
    mutationFn: (r: WdAiFlagRule) => client.updateFlagRule(r.name, { enabled: !r.enabled }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (rule: string) => client.deleteFlagRule(rule),
    onSuccess: invalidate,
  });

  return (
    <section className="rounded-lg border p-4" data-testid="ai-flagging-card">
      <h3 className="font-semibold">AI Message Flagging</h3>
      <p className="mb-3 text-sm text-muted-foreground">
        Flag inbound messages by custom criteria (purchase intent, angry customer, payment
        confirmed…). Runs while the AI add-on is active.
      </p>

      <ul className="mb-3 space-y-1" data-testid="flag-rule-list">
        {(rules.data ?? []).map((r) => (
          <li key={r.name} className="flex items-center gap-2 text-sm">
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={r.enabled}
                disabled={!canManage}
                onChange={() => toggle.mutate(r)}
                aria-label={`Toggle ${r.flag_key}`}
              />
            </label>
            <span className="font-mono text-xs text-primary">{r.flag_key}</span>
            <span className="truncate text-muted-foreground">— {r.prompt}</span>
            <span className="ml-auto shrink-0 text-xs text-muted-foreground">{r.action}</span>
            {canManage && (
              <button
                type="button"
                aria-label={`Delete ${r.flag_key}`}
                onClick={() => remove.mutate(r.name)}
              >
                <Trash2 className="h-3.5 w-3.5 text-destructive" />
              </button>
            )}
          </li>
        ))}
        {rules.data?.length === 0 && (
          <li className="text-xs text-muted-foreground">No flag rules yet.</li>
        )}
      </ul>

      {canManage && (
        <div className="space-y-1">
          <div className="flex gap-2">
            <Input
              aria-label="Flag key"
              placeholder="flag_key"
              value={flagKey}
              onChange={(e) => setFlagKey(e.target.value)}
            />
            <Input
              aria-label="Flag label"
              placeholder="Label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
            <select
              aria-label="Flag action"
              className="h-9 shrink-0 rounded-md border border-input bg-transparent px-2 text-sm"
              value={action}
              onChange={(e) => setAction(e.target.value as 'flag' | 'ticket')}
            >
              <option value="flag">Flag</option>
              <option value="ticket">Ticket</option>
            </select>
          </div>
          <Input
            aria-label="Flag criteria"
            placeholder="Criteria, e.g. Customer expresses intent to buy"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={!flagKey.trim() || !prompt.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            Add flag rule
          </Button>
        </div>
      )}

      {(create.isError || toggle.isError || remove.isError) && (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {errorText(create.error ?? toggle.error ?? remove.error)}
        </p>
      )}
    </section>
  );
}
