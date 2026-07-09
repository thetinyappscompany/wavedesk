import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AtSign, Link2, Phone, UsersRound } from 'lucide-react';
import type { WdMonitoringRuleType } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { useWorkspaceEvents } from '@/lib/realtime';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const KIND_ICON: Record<WdMonitoringRuleType, typeof AtSign> = {
  keyword: AtSign,
  link: Link2,
  phone_number: Phone,
  member_change: UsersRound,
};

function timeLabel(iso: string): string {
  const date = new Date(iso.replace(' ', 'T'));
  const today = new Date();
  return date.toDateString() === today.toDateString()
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString([], { day: '2-digit', month: 'short' });
}

/** Alerts feed (P2.4) — everything the monitoring rules caught. */
export default function AlertsPage(): React.JSX.Element {
  useWorkspaceEvents(); // wd:alert refreshes the feed live
  const queryClient = useQueryClient();
  const alerts = useQuery({
    queryKey: ['alerts'],
    queryFn: () => client.listAlerts(),
    refetchInterval: 60_000,
  });
  const markSeen = useMutation({
    mutationFn: () => client.markAlertsSeen(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alerts'] });
    },
  });

  const rows = alerts.data?.alerts ?? [];
  return (
    <div className="mx-auto max-w-3xl p-6">
      <div className="mb-3 flex items-center gap-3">
        <h1 className="text-lg font-semibold">Alerts</h1>
        {alerts.data !== undefined && alerts.data.unseen > 0 && (
          <>
            <span
              data-testid="unseen-count"
              className="rounded-full bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground"
            >
              {alerts.data.unseen} new
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={markSeen.isPending}
              onClick={() => {
                markSeen.mutate();
              }}
            >
              Mark all seen
            </Button>
          </>
        )}
      </div>

      {alerts.isLoading && <p className="text-sm text-muted-foreground">Loading alerts…</p>}
      {alerts.isError && (
        <p role="alert" className="text-sm text-destructive">
          Failed to load alerts.
        </p>
      )}
      {alerts.data && rows.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Nothing caught yet — configure monitoring rules in Settings.
        </p>
      )}

      <ul className="space-y-1">
        {rows.map((alert) => {
          const Icon = KIND_ICON[alert.kind] ?? AtSign;
          return (
            <li
              key={alert.name}
              data-testid="alert-row"
              className={cn(
                'flex items-start gap-2 rounded-md border px-3 py-2 text-sm',
                !alert.seen && 'border-primary/40 bg-primary/5',
              )}
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="break-words">{alert.summary}</p>
                <p className="text-xs text-muted-foreground">
                  {alert.group_subject ?? 'group'} · {timeLabel(alert.creation)}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
