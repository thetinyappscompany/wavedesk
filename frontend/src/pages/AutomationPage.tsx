import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, X } from 'lucide-react';
import type {
  WdAutomationAction,
  WdAutomationCondition,
  WdAutomationRule,
  WdAutomationTrigger,
} from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { useWorkspaceEvents } from '@/lib/realtime';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const TRIGGERS: { value: WdAutomationTrigger; label: string }[] = [
  { value: 'message_received', label: 'Message received' },
  { value: 'chat_created', label: 'New chat' },
  { value: 'status_change', label: 'Status changed' },
];

const CONDITION_TYPES: WdAutomationCondition['type'][] = [
  'keyword',
  'is_group',
  'is_dm',
  'has_label',
  'number',
  'first_time_contact',
];
const CONDITION_NEEDS_VALUE = new Set(['keyword', 'has_label', 'number']);

const ACTION_TYPES: WdAutomationAction['type'][] = [
  'auto_reply',
  'assign_agent',
  'assign_team',
  'add_label',
  'create_ticket',
  'set_status',
  'snooze',
  'notify_slack',
  'send_webhook',
];

/** Free-text param field per action type (kept simple for v1 — the builder
 * writes the raw JSON the engine consumes). */
const ACTION_PARAM: Partial<Record<WdAutomationAction['type'], { key: string; ph: string }>> = {
  auto_reply: { key: 'body', ph: 'Reply message' },
  assign_agent: { key: 'agent', ph: 'agent@email' },
  assign_team: { key: 'team', ph: 'Team id' },
  add_label: { key: 'label', ph: 'Label id' },
  create_ticket: { key: 'priority', ph: 'priority (low/medium/high/urgent)' },
  set_status: { key: 'status', ph: 'open/pending/resolved' },
  snooze: { key: 'minutes', ph: 'minutes' },
  notify_slack: { key: 'url', ph: 'Slack webhook URL' },
  send_webhook: { key: 'url', ph: 'Webhook URL' },
};

function RuleBuilder({ onDone }: { onDone: () => void }): React.JSX.Element {
  const queryClient = useQueryClient();
  const [ruleName, setRuleName] = useState('');
  const [trigger, setTrigger] = useState<WdAutomationTrigger>('message_received');
  const [conditions, setConditions] = useState<WdAutomationCondition[]>([]);
  const [actions, setActions] = useState<WdAutomationAction[]>([{ type: 'auto_reply' }]);

  const create = useMutation({
    mutationFn: () =>
      client.createAutomationRule({
        rule_name: ruleName.trim(),
        trigger_event: trigger,
        conditions,
        actions,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['automation-rules'] });
      onDone();
    },
  });

  return (
    <form
      className="space-y-3 rounded-lg border p-4"
      data-testid="rule-builder"
      onSubmit={(e) => {
        e.preventDefault();
        if (ruleName.trim() && actions.length > 0) {
          create.mutate();
        }
      }}
    >
      <div className="flex gap-2">
        <Input
          aria-label="Rule name"
          placeholder="e.g. Auto-greet new chats"
          value={ruleName}
          onChange={(e) => {
            setRuleName(e.target.value);
          }}
        />
        <select
          aria-label="Trigger"
          value={trigger}
          onChange={(e) => {
            setTrigger(e.target.value as WdAutomationTrigger);
          }}
          className="h-9 shrink-0 rounded-md border border-input bg-transparent px-2 text-sm"
        >
          {TRIGGERS.map((t) => (
            <option key={t.value} value={t.value}>
              When: {t.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <div className="mb-1 flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">Conditions (all match)</span>
          <button
            type="button"
            aria-label="Add condition"
            className="rounded p-0.5 hover:bg-accent"
            onClick={() => {
              setConditions((c) => [...c, { type: 'keyword', value: '' }]);
            }}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
        {conditions.map((cond, i) => (
          <div key={i} className="mb-1 flex items-center gap-1" data-testid="condition-row">
            <select
              aria-label={`Condition ${String(i + 1)} type`}
              value={cond.type}
              onChange={(e) => {
                setConditions((c) =>
                  c.map((x, j) =>
                    j === i ? { type: e.target.value as WdAutomationCondition['type'] } : x,
                  ),
                );
              }}
              className="h-8 rounded-md border border-input bg-transparent px-1 text-xs"
            >
              {CONDITION_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            {CONDITION_NEEDS_VALUE.has(cond.type) && (
              <Input
                aria-label={`Condition ${String(i + 1)} value`}
                className="h-8"
                value={cond.value ?? ''}
                onChange={(e) => {
                  setConditions((c) =>
                    c.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)),
                  );
                }}
              />
            )}
            <button
              type="button"
              aria-label={`Remove condition ${String(i + 1)}`}
              className="rounded p-1 text-destructive hover:bg-accent"
              onClick={() => {
                setConditions((c) => c.filter((_, j) => j !== i));
              }}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>

      <div>
        <div className="mb-1 flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">Actions</span>
          <button
            type="button"
            aria-label="Add action"
            className="rounded p-0.5 hover:bg-accent"
            onClick={() => {
              setActions((a) => [...a, { type: 'set_status' }]);
            }}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
        {actions.map((action, i) => {
          const param = ACTION_PARAM[action.type];
          return (
            <div key={i} className="mb-1 flex items-center gap-1" data-testid="action-row">
              <select
                aria-label={`Action ${String(i + 1)} type`}
                value={action.type}
                onChange={(e) => {
                  setActions((a) =>
                    a.map((x, j) =>
                      j === i ? { type: e.target.value as WdAutomationAction['type'] } : x,
                    ),
                  );
                }}
                className="h-8 rounded-md border border-input bg-transparent px-1 text-xs"
              >
                {ACTION_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              {param && (
                <Input
                  aria-label={`Action ${String(i + 1)} value`}
                  className="h-8"
                  placeholder={param.ph}
                  value={(action[param.key] as string | undefined) ?? ''}
                  onChange={(e) => {
                    setActions((a) =>
                      a.map((x, j) => (j === i ? { ...x, [param.key]: e.target.value } : x)),
                    );
                  }}
                />
              )}
              <button
                type="button"
                aria-label={`Remove action ${String(i + 1)}`}
                className="rounded p-1 text-destructive hover:bg-accent"
                onClick={() => {
                  setActions((a) => a.filter((_, j) => j !== i));
                }}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>

      <div className="flex gap-2">
        <Button type="submit" disabled={!ruleName.trim() || actions.length === 0 || create.isPending}>
          Save rule
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
      {create.isError && (
        <p role="alert" className="text-xs text-destructive">
          {create.error.message}
        </p>
      )}
    </form>
  );
}

export default function AutomationPage(): React.JSX.Element {
  useWorkspaceEvents();
  const queryClient = useQueryClient();
  const [building, setBuilding] = useState(false);
  const rules = useQuery({
    queryKey: ['automation-rules'],
    queryFn: () => client.listAutomationRules(),
  });
  const logs = useQuery({
    queryKey: ['automation-logs'],
    queryFn: () => client.listAutomationLogs(),
    refetchInterval: 30_000,
  });
  const toggle = useMutation({
    mutationFn: (change: { rule: string; enabled: boolean }) =>
      client.updateAutomationRule(change.rule, { enabled: change.enabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['automation-rules'] });
    },
  });
  const remove = useMutation({
    mutationFn: (rule: string) => client.deleteAutomationRule(rule),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['automation-rules'] });
    },
  });

  const summarize = (rule: WdAutomationRule): string => {
    const conds = rule.conditions.map((c) => c.type).join(' & ');
    const acts = rule.actions.map((a) => a.type).join(', ');
    return `${conds ? `if ${conds} → ` : ''}${acts}`;
  };

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">Automation</h1>
        {!building && (
          <Button size="sm" onClick={() => setBuilding(true)}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            New rule
          </Button>
        )}
      </div>

      {building && (
        <RuleBuilder
          onDone={() => {
            setBuilding(false);
          }}
        />
      )}

      <section aria-label="Rules" className="rounded-lg border">
        <ul className="divide-y">
          {(rules.data ?? []).map((rule) => (
            <li key={rule.name} data-testid="rule-row" className="flex items-center gap-2 px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{rule.rule_name}</span>
                  <span className="rounded border px-1 text-[10px] text-muted-foreground">
                    {rule.trigger_event}
                  </span>
                  <span className="text-xs text-muted-foreground">· fired {rule.run_count}×</span>
                </div>
                <div className="truncate text-xs text-muted-foreground">{summarize(rule)}</div>
              </div>
              <label className="flex items-center gap-1 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  aria-label={`Enable ${rule.rule_name}`}
                  checked={rule.enabled}
                  onChange={(e) => {
                    toggle.mutate({ rule: rule.name, enabled: e.target.checked });
                  }}
                />
                on
              </label>
              <button
                type="button"
                aria-label={`Delete ${rule.rule_name}`}
                className="rounded p-1 text-destructive hover:bg-accent"
                onClick={() => {
                  remove.mutate(rule.name);
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
          {rules.data?.length === 0 && (
            <li className="px-3 py-2 text-sm text-muted-foreground">
              No rules yet — create one to auto-reply, assign, label, or ticket conversations.
            </li>
          )}
        </ul>
      </section>

      <section aria-label="Execution log">
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">Recent activity</h2>
        <ul className="space-y-1">
          {(logs.data ?? []).map((log) => (
            <li
              key={log.name}
              data-testid="log-row"
              className="flex items-center gap-2 rounded border px-2 py-1 text-xs"
            >
              <span
                className={
                  log.outcome === 'error'
                    ? 'rounded bg-destructive/15 px-1 text-destructive'
                    : 'rounded bg-primary/15 px-1 text-primary'
                }
              >
                {log.outcome}
              </span>
              <span className="font-medium">{log.rule_name}</span>
              <span className="text-muted-foreground">{log.trigger_event}</span>
            </li>
          ))}
          {logs.data?.length === 0 && (
            <li className="text-sm text-muted-foreground">Nothing has fired yet.</li>
          )}
        </ul>
      </section>
    </div>
  );
}
