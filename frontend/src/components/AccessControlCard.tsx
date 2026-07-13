import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

/**
 * IP allowlist (P5, Business plan): restrict API access to specific IPs / CIDR
 * ranges. Empty = no restriction. Manager-only. Enforced on the public REST API.
 */
export default function AccessControlCard({ canManage }: { canManage: boolean }): React.JSX.Element {
  const allowlist = useQuery({ queryKey: ['ip-allowlist'], queryFn: () => client.getIpAllowlist() });
  const [text, setText] = useState('');
  useEffect(() => {
    if (allowlist.data) setText(allowlist.data.join('\n'));
  }, [allowlist.data]);

  const save = useMutation({
    mutationFn: () =>
      client.setIpAllowlist(
        text
          .split('\n')
          .map((l) => l.trim())
          .filter(Boolean),
      ),
    onSuccess: (res) => setText(res.ip_allowlist.join('\n')),
  });

  return (
    <section className="rounded-lg border p-4" data-testid="access-control-card">
      <h3 className="font-semibold">IP Allowlist</h3>
      <p className="mb-3 text-sm text-muted-foreground">
        Restrict public-API access to specific IPs or CIDR ranges (Business plan). One per line.
        Leave empty to allow all.
      </p>

      <textarea
        aria-label="IP allowlist"
        className="mb-2 h-24 w-full rounded-md border border-input bg-transparent p-2 font-mono text-xs"
        placeholder={'203.0.113.5\n10.0.0.0/8'}
        value={text}
        disabled={!canManage}
        onChange={(e) => setText(e.target.value)}
      />

      {canManage && (
        <Button size="sm" variant="outline" disabled={save.isPending} onClick={() => save.mutate()}>
          Save allowlist
        </Button>
      )}

      {save.isError && (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {errorText(save.error)}
        </p>
      )}
    </section>
  );
}
