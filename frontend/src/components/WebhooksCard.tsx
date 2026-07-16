import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, Trash2 } from 'lucide-react';
import type { WdWebhookDelivery } from '@wavedesk/api-client';

import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

const STATUS_COLOR: Record<WdWebhookDelivery['status'], string> = {
  delivered: 'text-emerald-600',
  pending: 'text-muted-foreground',
  failed: 'text-amber-600',
  dead: 'text-destructive',
};

/**
 * Outbound webhooks (P5): manager-only HMAC-signed event delivery. Create
 * endpoints subscribed to event types, watch recent deliveries, and redeliver
 * anything in the failed/dead-letter state.
 */
export default function WebhooksCard({ canManage }: { canManage: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const endpoints = useQuery({
    queryKey: ['webhook-endpoints'],
    queryFn: () => client.listWebhookEndpoints(),
  });
  const catalog = useQuery({
    queryKey: ['webhook-events'],
    queryFn: () => client.webhookEventCatalog(),
  });
  const deliveries = useQuery({
    queryKey: ['webhook-deliveries'],
    queryFn: () => client.listWebhookDeliveries({ limit: 10 }),
  });

  const [label, setLabel] = useState('');
  const [url, setUrl] = useState('');
  const [events, setEvents] = useState<string[]>([]);

  const invalidate = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['webhook-endpoints'] });
    void queryClient.invalidateQueries({ queryKey: ['webhook-deliveries'] });
  };

  const create = useMutation({
    mutationFn: () => client.createWebhookEndpoint(label.trim(), url.trim(), events),
    onSuccess: () => {
      setLabel('');
      setUrl('');
      setEvents([]);
      invalidate();
    },
  });
  const toggle = useMutation({
    mutationFn: (e: { name: string; enabled: boolean }) =>
      client.updateWebhookEndpoint(e.name, { enabled: !e.enabled }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (name: string) => client.deleteWebhookEndpoint(name),
    onSuccess: invalidate,
  });
  const redeliver = useMutation({
    mutationFn: (name: string) => client.redeliverWebhook(name),
    onSuccess: invalidate,
  });

  const toggleEvent = (evt: string): void => {
    setEvents((prev) => (prev.includes(evt) ? prev.filter((e) => e !== evt) : [...prev, evt]));
  };

  return (
    <section className="rounded-lg border p-4" data-testid="webhooks-card">
      <h3 className="font-semibold">Webhooks</h3>
      <p className="mb-3 text-sm text-muted-foreground">
        Receive HMAC-signed events at your own URL (message received, chat resolved, ticket
        created, broadcast completed…). Failed deliveries retry with backoff.
      </p>

      <ul className="mb-3 space-y-1" data-testid="webhook-endpoint-list">
        {(endpoints.data ?? []).map((e) => (
          <li key={e.name} className="flex items-center gap-2 text-sm">
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={e.enabled}
                disabled={!canManage}
                onChange={() => toggle.mutate(e)}
                aria-label={`Toggle ${e.label}`}
              />
            </label>
            <span className="font-medium">{e.label}</span>
            <span className="truncate text-xs text-muted-foreground">{e.url}</span>
            <span className="ml-auto shrink-0 text-xs text-muted-foreground">
              {e.events.length} event{e.events.length === 1 ? '' : 's'}
            </span>
            {canManage && (
              <button
                type="button"
                aria-label={`Delete ${e.label}`}
                onClick={() => remove.mutate(e.name)}
              >
                <Trash2 className="h-3.5 w-3.5 text-destructive" />
              </button>
            )}
          </li>
        ))}
        {endpoints.data?.length === 0 && (
          <li className="text-xs text-muted-foreground">No webhook endpoints yet.</li>
        )}
      </ul>

      {canManage && (
        <div className="mb-3 space-y-2">
          <div className="flex gap-2">
            <Input
              aria-label="Webhook label"
              placeholder="Label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
            <Input
              aria-label="Webhook URL"
              placeholder="https://example.com/hook"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          <div className="flex flex-wrap gap-2" data-testid="webhook-events">
            {(catalog.data ?? []).map((evt) => (
              <label key={evt} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={events.includes(evt)}
                  onChange={() => toggleEvent(evt)}
                  aria-label={evt}
                />
                <span className="font-mono">{evt}</span>
              </label>
            ))}
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={!label.trim() || !url.trim() || events.length === 0 || create.isPending}
            onClick={() => create.mutate()}
          >
            Add webhook
          </Button>
        </div>
      )}

      {(deliveries.data ?? []).length > 0 && (
        <div data-testid="webhook-deliveries">
          <h4 className="mb-1 text-xs font-medium text-muted-foreground">Recent deliveries</h4>
          <ul className="space-y-1">
            {(deliveries.data ?? []).map((d) => (
              <li key={d.name} className="flex items-center gap-2 text-xs">
                <span className="font-mono">{d.event_type}</span>
                <span className={STATUS_COLOR[d.status]}>{d.status}</span>
                {d.response_code ? <span className="text-muted-foreground">{d.response_code}</span> : null}
                {canManage && (d.status === 'failed' || d.status === 'dead') && (
                  <button
                    type="button"
                    className="ml-auto inline-flex items-center gap-1 text-primary"
                    aria-label={`Redeliver ${d.name}`}
                    onClick={() => redeliver.mutate(d.name)}
                  >
                    <RefreshCw className="h-3 w-3" /> retry
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(create.isError || toggle.isError || remove.isError || redeliver.isError) && (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {errorText(create.error ?? toggle.error ?? remove.error ?? redeliver.error)}
        </p>
      )}
    </section>
  );
}
