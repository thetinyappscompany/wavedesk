import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Trash2 } from 'lucide-react';
import type { WdApiKeyCreated } from '@wavedesk/api-client';

import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

/**
 * Public REST API keys (P5): manager-only scoped credentials for the /api/v1 API.
 * The full key is shown exactly once at creation — only its hash is stored — so we
 * surface a copyable one-time reveal panel and never display it again.
 */
export default function ApiKeysCard({ canManage }: { canManage: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const keys = useQuery({ queryKey: ['api-keys'], queryFn: () => client.listApiKeys() });
  const scopes = useQuery({ queryKey: ['api-key-scopes'], queryFn: () => client.apiKeyScopes() });

  const [label, setLabel] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [reveal, setReveal] = useState<WdApiKeyCreated | null>(null);

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['api-keys'] });

  const create = useMutation({
    mutationFn: () => client.createApiKey(label.trim(), selected),
    onSuccess: (created) => {
      setReveal(created);
      setLabel('');
      setSelected([]);
      invalidate();
    },
  });
  const revoke = useMutation({
    mutationFn: (name: string) => client.revokeApiKey(name),
    onSuccess: invalidate,
  });

  const toggleScope = (scope: string): void => {
    setSelected((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  };

  return (
    <section className="rounded-lg border p-4" data-testid="api-keys-card">
      <h3 className="font-semibold">API Keys</h3>
      <p className="mb-3 text-sm text-muted-foreground">
        Scoped credentials for the public REST API (<code>/api/method/wavedesk.api.v1.*</code>).
        Send messages, read chats, manage contacts and tickets programmatically.
      </p>

      {reveal && (
        <div
          data-testid="api-key-reveal"
          className="mb-3 rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm"
        >
          <p className="mb-1 font-medium">Copy your key now — it won’t be shown again.</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 truncate rounded bg-background/70 px-2 py-1 text-xs">
              {reveal.full_key}
            </code>
            <button
              type="button"
              aria-label="Copy API key"
              onClick={() => void navigator.clipboard?.writeText(reveal.full_key)}
            >
              <Copy className="h-4 w-4" />
            </button>
            <button type="button" className="text-xs underline" onClick={() => setReveal(null)}>
              Done
            </button>
          </div>
        </div>
      )}

      <ul className="mb-3 space-y-1" data-testid="api-key-list">
        {(keys.data ?? []).map((k) => (
          <li key={k.name} className="flex items-center gap-2 text-sm">
            <span className="font-medium">{k.label}</span>
            <span className="font-mono text-xs text-muted-foreground">{k.key_prefix}…</span>
            <span className="truncate text-xs text-muted-foreground">
              {k.scopes.join(', ')}
            </span>
            <span className="ml-auto shrink-0 text-xs">
              {k.enabled ? (
                <span className="text-emerald-600">active</span>
              ) : (
                <span className="text-muted-foreground">revoked</span>
              )}
            </span>
            {canManage && k.enabled && (
              <button
                type="button"
                aria-label={`Revoke ${k.label}`}
                onClick={() => revoke.mutate(k.name)}
              >
                <Trash2 className="h-3.5 w-3.5 text-destructive" />
              </button>
            )}
          </li>
        ))}
        {keys.data?.length === 0 && (
          <li className="text-xs text-muted-foreground">No API keys yet.</li>
        )}
      </ul>

      {canManage && (
        <div className="space-y-2">
          <Input
            aria-label="API key label"
            placeholder="Key label, e.g. CRM sync"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <div className="flex flex-wrap gap-2" data-testid="api-key-scopes">
            {(scopes.data ?? []).map((scope) => (
              <label key={scope} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={selected.includes(scope)}
                  onChange={() => toggleScope(scope)}
                  aria-label={scope}
                />
                <span className="font-mono">{scope}</span>
              </label>
            ))}
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={!label.trim() || selected.length === 0 || create.isPending}
            onClick={() => create.mutate()}
          >
            Create API key
          </Button>
        </div>
      )}

      {(create.isError || revoke.isError) && (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {errorText(create.error ?? revoke.error)}
        </p>
      )}
    </section>
  );
}
