import { useQuery } from '@tanstack/react-query';
import { client } from '@/lib/client';

const STATUS_STYLES: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  trialing: 'bg-blue-100 text-blue-800',
  past_due: 'bg-amber-100 text-amber-800',
  cancelled: 'bg-red-100 text-red-800',
  suspended: 'bg-red-100 text-red-800',
};

/** Settings → Billing: plan, subscription status and prepaid wallet balance.
 * Managers only — the backend 403s agents, so we don't even ask. */
export default function BillingCard({
  canManage,
}: {
  canManage: boolean;
}): React.JSX.Element {
  const billing = useQuery({
    queryKey: ['billing-summary'],
    queryFn: () => client.billingSummary(),
    enabled: canManage,
  });
  const ai = useQuery({
    queryKey: ['ai-usage-meter'],
    queryFn: () => client.aiUsageMeter(),
    enabled: canManage,
  });

  if (!canManage) {
    return (
      <section aria-label="Billing" className="rounded-lg border p-4">
        <h2 className="font-semibold">Billing</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Only workspace owners and admins can view billing.
        </p>
      </section>
    );
  }

  const b = billing.data;
  return (
    <section aria-label="Billing" className="rounded-lg border p-4">
      <h2 className="font-semibold">Billing</h2>
      <p className="mb-3 text-sm text-muted-foreground">
        Subscription and prepaid wallet for this workspace. Plan changes and top-ups are
        handled through your invoices — contact support to upgrade.
      </p>
      {billing.isError && (
        <p role="alert" className="text-xs text-destructive">
          Could not load billing details.
        </p>
      )}
      {b && (
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div className="rounded-md border p-3">
            <dt className="text-xs text-muted-foreground">Plan</dt>
            <dd className="mt-1 font-medium">{b.plan ?? '—'}</dd>
          </div>
          <div className="rounded-md border p-3">
            <dt className="text-xs text-muted-foreground">Status</dt>
            <dd className="mt-1">
              <span
                className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${
                  STATUS_STYLES[b.status] ?? 'bg-muted text-muted-foreground'
                }`}
              >
                {b.status}
              </span>
            </dd>
          </div>
          <div className="rounded-md border p-3">
            <dt className="text-xs text-muted-foreground">Renews</dt>
            <dd className="mt-1 font-medium">
              {b.current_period_end
                ? new Date(b.current_period_end).toLocaleDateString()
                : '—'}
            </dd>
          </div>
          <div className="rounded-md border p-3">
            <dt className="text-xs text-muted-foreground">Wallet balance</dt>
            <dd className="mt-1 font-medium">
              ₹{b.wallet_balance.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </dd>
          </div>
        </dl>
      )}
      {ai.data?.has_ai ? (
        <section aria-label="AI usage" className="mt-4 rounded-md border p-3">
          <h3 className="text-sm font-semibold">AI usage this month</h3>
          <div className="mt-2 h-2 w-full overflow-hidden rounded bg-muted">
            <div
              className={`h-full ${
                ai.data.allowance_pct_used >= 80 ? 'bg-amber-500' : 'bg-primary'
              }`}
              style={{ width: `${Math.min(ai.data.allowance_pct_used, 100)}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {ai.data.allowance_pct_used}% of the monthly allowance used
            {ai.data.credits_inr > 0 &&
              ` · ₹${ai.data.credits_inr.toLocaleString('en-IN')} extra from wallet`}
            {ai.data.byok && ' · using your own API key'}
          </p>
          {ai.data.paused && (
            <p className="mt-1 text-xs font-medium text-destructive">
              AI is paused — allowance exhausted and wallet balance too low. Top up to
              resume.
            </p>
          )}
        </section>
      ) : (
        b && (
          <p className="mt-3 text-xs text-muted-foreground">
            AI add-on: {b.ai_addon ? 'active' : 'not enabled'}
          </p>
        )
      )}
    </section>
  );
}
