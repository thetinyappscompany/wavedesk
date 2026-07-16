import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, X } from 'lucide-react';
import type { WdSlaEscalationStep, WdSlaTarget } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const TARGETS: WdSlaTarget[] = ['agent', 'team', 'owner', 'slack', 'webhook'];
const NEEDS_URL = new Set<WdSlaTarget>(['slack', 'webhook']);

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

/** SLA policy management (P3.3): first-response + resolution targets and an
 * escalation chain. Attach policies to chats via automation rules (set_sla). */
export default function SlaCard({ canManage }: { canManage: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const policies = useQuery({ queryKey: ['sla-policies'], queryFn: () => client.listSlaPolicies() });
  const [name, setName] = useState('');
  const [fr, setFr] = useState('10');
  const [res, setRes] = useState('0');
  const [chain, setChain] = useState<WdSlaEscalationStep[]>([]);

  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['sla-policies'] });
    setName('');
    setFr('10');
    setRes('0');
    setChain([]);
  };
  const create = useMutation({
    mutationFn: () =>
      client.createSlaPolicy({
        policyName: name.trim(),
        firstResponseMins: Number(fr) || 0,
        resolutionMins: Number(res) || 0,
        escalationChain: chain,
      }),
    onSuccess: refresh,
  });
  const toggle = useMutation({
    mutationFn: (change: { policy: string; enabled: boolean }) =>
      client.updateSlaPolicy(change.policy, { enabled: change.enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sla-policies'] }),
  });
  const remove = useMutation({
    mutationFn: (policy: string) => client.deleteSlaPolicy(policy),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sla-policies'] }),
  });

  const rows = policies.data ?? [];

  return (
    <section aria-label="SLA policies" className="rounded-lg border p-4">
      <h2 className="font-semibold">SLA policies</h2>
      <p className="mb-3 text-sm text-muted-foreground">
        First-response and resolution targets with an escalation chain. Attach a policy to
        conversations with an automation rule (Set SLA action).
      </p>

      <ul className="mb-3 space-y-1">
        {rows.map((policy) => (
          <li
            key={policy.name}
            data-testid="sla-policy-row"
            className="flex items-center gap-2 rounded border px-3 py-2 text-sm"
          >
            <div className="min-w-0 flex-1">
              <span className="font-medium">{policy.policy_name}</span>
              <span className="ml-2 text-xs text-muted-foreground">
                {policy.first_response_mins > 0 && `FR ${String(policy.first_response_mins)}m`}
                {policy.first_response_mins > 0 && policy.resolution_mins > 0 && ' · '}
                {policy.resolution_mins > 0 && `Res ${String(policy.resolution_mins)}m`}
                {policy.escalation_chain.length > 0 &&
                  ` · ${String(policy.escalation_chain.length)} escalation${policy.escalation_chain.length > 1 ? 's' : ''}`}
              </span>
            </div>
            {canManage && (
              <>
                <label className="flex items-center gap-1 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    aria-label={`Enable ${policy.policy_name}`}
                    checked={policy.enabled}
                    onChange={(e) => {
                      toggle.mutate({ policy: policy.name, enabled: e.target.checked });
                    }}
                  />
                  on
                </label>
                <button
                  type="button"
                  aria-label={`Delete ${policy.policy_name}`}
                  className="rounded p-1 text-destructive hover:bg-accent"
                  onClick={() => {
                    remove.mutate(policy.name);
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </li>
        ))}
        {rows.length === 0 && (
          <li className="px-1 text-sm text-muted-foreground">No SLA policies yet.</li>
        )}
      </ul>

      {canManage && (
        <form
          className="space-y-2 border-t pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && (Number(fr) > 0 || Number(res) > 0)) {
              create.mutate();
            }
          }}
        >
          <Input
            aria-label="SLA policy name"
            placeholder="e.g. Gold support"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
          <div className="flex gap-2">
            <label className="text-xs text-muted-foreground">
              First response (min)
              <Input
                aria-label="First response minutes"
                type="number"
                min={0}
                className="mt-1 w-28"
                value={fr}
                onChange={(e) => {
                  setFr(e.target.value);
                }}
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Resolution (min)
              <Input
                aria-label="Resolution minutes"
                type="number"
                min={0}
                className="mt-1 w-28"
                value={res}
                onChange={(e) => {
                  setRes(e.target.value);
                }}
              />
            </label>
          </div>

          <div>
            <div className="mb-1 flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground">Escalation chain</span>
              <button
                type="button"
                aria-label="Add escalation step"
                className="rounded p-0.5 hover:bg-accent"
                onClick={() => {
                  setChain((c) => [...c, { after_mins: 0, target: 'agent' }]);
                }}
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
            {chain.map((step, i) => (
              <div key={i} className="mb-1 flex items-center gap-1" data-testid="escalation-row">
                <Input
                  aria-label={`Step ${String(i + 1)} after minutes`}
                  type="number"
                  min={0}
                  className="h-8 w-20"
                  value={step.after_mins}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    setChain((c) => c.map((s, j) => (j === i ? { ...s, after_mins: v } : s)));
                  }}
                />
                <span className="text-xs text-muted-foreground">min →</span>
                <select
                  aria-label={`Step ${String(i + 1)} target`}
                  value={step.target}
                  onChange={(e) => {
                    const target = e.target.value as WdSlaTarget;
                    setChain((c) => c.map((s, j) => (j === i ? { ...s, target } : s)));
                  }}
                  className="h-8 rounded-md border border-input bg-transparent px-1 text-xs"
                >
                  {TARGETS.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                {NEEDS_URL.has(step.target) && (
                  <Input
                    aria-label={`Step ${String(i + 1)} url`}
                    placeholder="https://…"
                    className="h-8"
                    value={step.url ?? ''}
                    onChange={(e) => {
                      setChain((c) => c.map((s, j) => (j === i ? { ...s, url: e.target.value } : s)));
                    }}
                  />
                )}
                <button
                  type="button"
                  aria-label={`Remove escalation step ${String(i + 1)}`}
                  className="rounded p-1 text-destructive hover:bg-accent"
                  onClick={() => {
                    setChain((c) => c.filter((_, j) => j !== i));
                  }}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>

          <Button
            type="submit"
            disabled={!name.trim() || (Number(fr) <= 0 && Number(res) <= 0) || create.isPending}
          >
            Add policy
          </Button>
          {create.isError && (
            <p role="alert" className="text-xs text-destructive">
              {errorText(create.error)}
            </p>
          )}
        </form>
      )}
    </section>
  );
}
