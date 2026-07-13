import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

/**
 * Per-vertical starter packs (P5): apply a curated set of labels, canned
 * responses, and automation rules for a business type. Idempotent — safe to
 * apply more than once. Manager-only.
 */
export default function StarterTemplatesCard({ canManage }: { canManage: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const verticals = useQuery({ queryKey: ['verticals'], queryFn: () => client.listVerticals() });
  const [selected, setSelected] = useState<string>('');
  const [applied, setApplied] = useState<string | null>(null);

  const apply = useMutation({
    mutationFn: () => client.applyVertical(selected),
    onSuccess: (res) => {
      const a = res.added;
      setApplied(`Added ${a.labels} labels, ${a.canned} canned replies, ${a.automation} rules.`);
      void queryClient.invalidateQueries({ queryKey: ['labels'] });
      void queryClient.invalidateQueries({ queryKey: ['canned'] });
    },
  });

  const active = (verticals.data ?? []).find((v) => v.key === selected);

  return (
    <section className="rounded-lg border p-4" data-testid="starter-templates-card">
      <h3 className="font-semibold">Starter Templates</h3>
      <p className="mb-3 text-sm text-muted-foreground">
        Seed labels, canned responses, and automation rules tailored to your business type.
        Safe to apply anytime — existing items are kept.
      </p>

      {canManage && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2" data-testid="vertical-options">
            {(verticals.data ?? []).map((v) => (
              <button
                key={v.key}
                type="button"
                aria-label={v.label}
                onClick={() => {
                  setSelected(v.key);
                  setApplied(null);
                }}
                className={
                  'rounded-md border px-3 py-1.5 text-sm ' +
                  (selected === v.key
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-accent')
                }
              >
                {v.label}
              </button>
            ))}
          </div>

          {active && (
            <div className="rounded border p-2 text-xs text-muted-foreground" data-testid="vertical-preview">
              <p className="mb-1">{active.description}</p>
              <p>
                <span className="font-medium">Labels:</span> {active.labels.join(', ')}
              </p>
              <p>
                <span className="font-medium">Canned:</span> /{active.canned.join(', /')}
              </p>
              <p>
                <span className="font-medium">Rules:</span> {active.automation.join(', ')}
              </p>
            </div>
          )}

          <Button
            size="sm"
            variant="outline"
            disabled={!selected || apply.isPending}
            onClick={() => apply.mutate()}
          >
            Apply pack
          </Button>
        </div>
      )}

      {applied && (
        <p className="mt-2 text-xs text-emerald-600" data-testid="apply-result">
          {applied}
        </p>
      )}
      {apply.isError && (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {errorText(apply.error)}
        </p>
      )}
    </section>
  );
}
