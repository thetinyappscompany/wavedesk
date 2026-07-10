import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import type { WdVolumePoint } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { useWorkspaceEvents } from '@/lib/realtime';
import { Button } from '@/components/ui/button';

const RANGES = [
  { days: 7, label: '7d' },
  { days: 14, label: '14d' },
  { days: 30, label: '30d' },
] as const;

function Chart({ points }: { points: WdVolumePoint[] }): React.JSX.Element {
  const max = Math.max(1, ...points.map((p) => p.count));
  const width = 100;
  const height = 40;
  const gap = 1;
  const barWidth = points.length > 0 ? (width - gap * (points.length - 1)) / points.length : width;
  return (
    <svg
      viewBox={`0 0 ${String(width)} ${String(height)}`}
      className="h-24 w-full"
      preserveAspectRatio="none"
      role="img"
      aria-label="New conversations per day"
    >
      {points.map((point, i) => (
        <rect
          key={point.date}
          data-testid="conv-bar"
          x={i * (barWidth + gap)}
          y={height - (point.count / max) * height}
          width={barWidth}
          height={(point.count / max) * height}
          className="fill-primary/70"
        >
          <title>{`${point.date}: ${String(point.count)}`}</title>
        </rect>
      ))}
    </svg>
  );
}

function mins(value: number | null): string {
  return value === null ? '—' : `${String(value)}m`;
}

function Tile({ label, value, tone }: { label: string; value: number; tone?: 'warn' }): React.JSX.Element {
  return (
    <div data-testid="live-tile" className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`text-2xl font-semibold ${tone === 'warn' ? 'text-amber-600' : ''}`}>
        {value}
      </div>
    </div>
  );
}

/** Workspace analytics dashboard (P2.6): live tiles + historical operational
 * metrics with a date range and CSV export. */
export default function DashboardPage(): React.JSX.Element {
  useWorkspaceEvents(); // live tiles refresh on wd:chat / wd:message
  const [days, setDays] = useState(14);
  const dashboard = useQuery({
    queryKey: ['dashboard', days],
    queryFn: () => client.workspaceDashboard(days),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
  const d = dashboard.data;

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Analytics</h1>
        <div role="tablist" aria-label="Date range" className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r.days}
              role="tab"
              aria-selected={days === r.days}
              onClick={() => {
                setDays(r.days);
              }}
              className={
                days === r.days
                  ? 'rounded-md bg-primary px-2 py-1 text-xs text-primary-foreground'
                  : 'rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-accent'
              }
            >
              {r.label}
            </button>
          ))}
        </div>
        <a
          href={client.dashboardCsvUrl(days)}
          className="ml-auto"
          data-testid="csv-link"
          download
        >
          <Button variant="outline" size="sm">
            <Download className="mr-1 h-3.5 w-3.5" />
            Export CSV
          </Button>
        </a>
      </div>

      {dashboard.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {dashboard.isError && (
        <p role="alert" className="text-sm text-destructive">
          Failed to load analytics.
        </p>
      )}

      {d && (
        <>
          <section aria-label="Live" className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile label="Open chats" value={d.live.open} />
            <Tile label="Unassigned" value={d.live.unassigned} />
            <Tile label="Needs reply" value={d.live.needs_reply} tone="warn" />
            <Tile label="SLA breached" value={d.live.sla_breached} tone="warn" />
          </section>

          <section aria-label="Conversations" className="rounded-lg border p-3">
            <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
              <span>New conversations · last {d.days} days</span>
              <span>{d.conversations_total} total</span>
            </div>
            <Chart points={d.conversations_trend} />
          </section>

          <section aria-label="Response times" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Tile2 label="First response (avg)" value={mins(d.first_response_avg_mins)} />
            <Tile2 label="First response (p90)" value={mins(d.first_response_p90_mins)} />
            <Tile2 label="Resolution (avg)" value={mins(d.resolution_avg_mins)} />
            <Tile2 label="Resolution (p90)" value={mins(d.resolution_p90_mins)} />
          </section>

          <div className="grid gap-4 sm:grid-cols-2">
            <section aria-label="Messages per agent" className="rounded-lg border p-3">
              <h2 className="mb-2 text-sm font-medium">Messages per agent</h2>
              {d.messages_per_agent.length === 0 ? (
                <p className="text-sm text-muted-foreground">No outbound messages yet.</p>
              ) : (
                <ul className="space-y-1">
                  {d.messages_per_agent.map((row) => (
                    <li
                      key={row.agent}
                      data-testid="agent-row"
                      className="flex justify-between text-sm"
                    >
                      <span className="truncate">{row.agent_name}</span>
                      <span className="text-muted-foreground">{row.messages}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-label="Per number volume" className="rounded-lg border p-3">
              <h2 className="mb-2 text-sm font-medium">Volume per number</h2>
              {d.per_number_volume.length === 0 ? (
                <p className="text-sm text-muted-foreground">No traffic yet.</p>
              ) : (
                <ul className="space-y-1">
                  {d.per_number_volume.map((row) => (
                    <li
                      key={row.number}
                      data-testid="number-row"
                      className="flex justify-between text-sm"
                    >
                      <span className="truncate">{row.display_name ?? row.number}</span>
                      <span className="text-muted-foreground">{row.messages}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function Tile2({ label, value }: { label: string; value: string }): React.JSX.Element {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}
