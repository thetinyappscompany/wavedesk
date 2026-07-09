import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import type { WdMonitoringRuleType } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const RULE_TYPES: { value: WdMonitoringRuleType; label: string }[] = [
  { value: 'keyword', label: 'Keywords' },
  { value: 'link', label: 'Link posted' },
  { value: 'phone_number', label: 'Phone number posted' },
  { value: 'member_change', label: 'Member joined/left' },
];

/** Monitoring rules (P2.4): keyword/link/phone/member alerts per group,
 * delivered in-app and optionally to Slack / a webhook. */
export default function MonitoringCard({ canManage }: { canManage: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const rules = useQuery({
    queryKey: ['monitoring-rules'],
    queryFn: () => client.listMonitoringRules(),
  });
  const [ruleName, setRuleName] = useState('');
  const [ruleType, setRuleType] = useState<WdMonitoringRuleType>('keyword');
  const [keywords, setKeywords] = useState('');
  const [slackUrl, setSlackUrl] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');

  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['monitoring-rules'] });
  };
  const create = useMutation({
    mutationFn: () =>
      client.createMonitoringRule({
        rule_name: ruleName.trim(),
        rule_type: ruleType,
        ...(ruleType === 'keyword' ? { keywords } : {}),
        ...(slackUrl.trim() ? { notify_slack_url: slackUrl.trim() } : {}),
        ...(webhookUrl.trim() ? { notify_webhook_url: webhookUrl.trim() } : {}),
      }),
    onSuccess: () => {
      setRuleName('');
      setKeywords('');
      setSlackUrl('');
      setWebhookUrl('');
      refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: (change: { rule: string; enabled: boolean }) =>
      client.updateMonitoringRule(change.rule, { enabled: change.enabled }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (rule: string) => client.deleteMonitoringRule(rule),
    onSuccess: refresh,
  });

  const typeLabel = (value: WdMonitoringRuleType): string =>
    RULE_TYPES.find((t) => t.value === value)?.label ?? value;

  return (
    <section aria-label="Monitoring rules" className="rounded-lg border p-4">
      <h2 className="font-semibold">Monitoring rules</h2>
      <p className="mb-3 text-sm text-muted-foreground">
        Watch group messages for keywords, links, or dropped phone numbers, and get notified
        when members join or leave. Alerts land on the Alerts page — and in Slack or a webhook
        if configured.
      </p>
      <ul className="mb-3 space-y-1">
        {(rules.data ?? []).map((rule) => (
          <li
            key={rule.name}
            data-testid="monitoring-rule-row"
            className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-accent"
          >
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium">{rule.rule_name}</span>
              <span className="ml-2 rounded border px-1 text-xs text-muted-foreground">
                {typeLabel(rule.rule_type)}
              </span>
              {rule.keywords && (
                <span className="ml-2 truncate text-xs text-muted-foreground">
                  {rule.keywords}
                </span>
              )}
            </span>
            {canManage && (
              <>
                <label className="flex items-center gap-1 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    aria-label={`Enable rule ${rule.rule_name}`}
                    checked={rule.enabled}
                    onChange={(e) => {
                      toggle.mutate({ rule: rule.name, enabled: e.target.checked });
                    }}
                  />
                  on
                </label>
                <button
                  type="button"
                  aria-label={`Delete rule ${rule.rule_name}`}
                  className="rounded p-1 text-destructive hover:bg-background"
                  onClick={() => {
                    remove.mutate(rule.name);
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </li>
        ))}
        {rules.data?.length === 0 && (
          <li className="px-2 py-1 text-sm text-muted-foreground">No rules yet.</li>
        )}
      </ul>

      {canManage && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (ruleName.trim() && (ruleType !== 'keyword' || keywords.trim())) {
              create.mutate();
            }
          }}
        >
          <div className="flex gap-2">
            <Input
              aria-label="Rule name"
              placeholder="e.g. Competitor watch"
              value={ruleName}
              onChange={(e) => {
                setRuleName(e.target.value);
              }}
            />
            <select
              aria-label="Rule type"
              value={ruleType}
              onChange={(e) => {
                setRuleType(e.target.value as WdMonitoringRuleType);
              }}
              className="h-9 shrink-0 rounded-md border border-input bg-transparent px-2 text-sm"
            >
              {RULE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          {ruleType === 'keyword' && (
            <Input
              aria-label="Rule keywords"
              placeholder="scam, competitor name, refund"
              value={keywords}
              onChange={(e) => {
                setKeywords(e.target.value);
              }}
            />
          )}
          <div className="flex gap-2">
            <Input
              aria-label="Slack webhook URL"
              placeholder="Slack webhook URL (optional)"
              value={slackUrl}
              onChange={(e) => {
                setSlackUrl(e.target.value);
              }}
            />
            <Input
              aria-label="Webhook URL"
              placeholder="Webhook URL (optional)"
              value={webhookUrl}
              onChange={(e) => {
                setWebhookUrl(e.target.value);
              }}
            />
          </div>
          <Button
            type="submit"
            disabled={
              !ruleName.trim() ||
              (ruleType === 'keyword' && !keywords.trim()) ||
              create.isPending
            }
          >
            Add rule
          </Button>
          {create.isError && (
            <p role="alert" className="text-xs text-destructive">
              {create.error.message}
            </p>
          )}
        </form>
      )}
    </section>
  );
}
