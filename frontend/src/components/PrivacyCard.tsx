import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download } from 'lucide-react';

import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

/**
 * DPDP/GDPR data controls (P5): retention window + data-portability export.
 * Manager-only. Contact right-to-erasure lives on the contact drawer.
 */
export default function PrivacyCard({ canManage }: { canManage: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const retention = useQuery({ queryKey: ['retention'], queryFn: () => client.getRetention() });
  const exports = useQuery({ queryKey: ['data-exports'], queryFn: () => client.listDataExports() });

  const [days, setDays] = useState('0');
  useEffect(() => {
    if (retention.data !== undefined) setDays(String(retention.data));
  }, [retention.data]);

  const saveRetention = useMutation({
    mutationFn: () => client.setRetention(Number(days) || 0),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['retention'] }),
  });
  const requestExport = useMutation({
    mutationFn: () => client.requestDataExport(),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['data-exports'] }),
  });

  return (
    <section className="rounded-lg border p-4" data-testid="privacy-card">
      <h3 className="font-semibold">Data &amp; Privacy</h3>
      <p className="mb-3 text-sm text-muted-foreground">
        DPDP/GDPR controls: set a retention window (older messages are purged nightly) and
        export this workspace's data. Erase an individual contact from their profile drawer.
      </p>

      <div className="mb-4 flex items-end gap-2">
        <label className="text-sm">
          <span className="mb-1 block text-xs text-muted-foreground">Message retention (days, 0 = keep forever)</span>
          <Input
            type="number"
            min={0}
            aria-label="Retention days"
            className="w-40"
            value={days}
            disabled={!canManage}
            onChange={(e) => setDays(e.target.value)}
          />
        </label>
        {canManage && (
          <Button
            size="sm"
            variant="outline"
            disabled={saveRetention.isPending || days === String(retention.data ?? '')}
            onClick={() => saveRetention.mutate()}
          >
            Save
          </Button>
        )}
      </div>

      {canManage && (
        <div className="mb-3">
          <Button
            size="sm"
            variant="outline"
            disabled={requestExport.isPending}
            onClick={() => requestExport.mutate()}
          >
            Request data export
          </Button>
        </div>
      )}

      {(exports.data ?? []).length > 0 && (
        <ul className="space-y-1" data-testid="data-export-list">
          {(exports.data ?? []).map((e) => (
            <li key={e.name} className="flex items-center gap-2 text-xs">
              <span className="font-mono">{e.name}</span>
              <span
                className={
                  e.status === 'ready'
                    ? 'text-emerald-600'
                    : e.status === 'failed'
                      ? 'text-destructive'
                      : 'text-muted-foreground'
                }
              >
                {e.status}
              </span>
              {e.status === 'ready' && e.file_url && (
                <a
                  href={e.file_url}
                  className="ml-auto inline-flex items-center gap-1 text-primary"
                  download
                >
                  <Download className="h-3 w-3" /> download
                </a>
              )}
            </li>
          ))}
        </ul>
      )}

      {(saveRetention.isError || requestExport.isError) && (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {errorText(saveRetention.error ?? requestExport.error)}
        </p>
      )}
    </section>
  );
}
