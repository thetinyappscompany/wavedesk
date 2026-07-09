import { useQuery } from '@tanstack/react-query';
import type { WdVolumePoint } from '@wavedesk/api-client';
import { client } from '@/lib/client';

/** Dependency-free inline SVG bar chart — one bar per day. */
function VolumeChart({ points }: { points: WdVolumePoint[] }): React.JSX.Element {
  const max = Math.max(1, ...points.map((p) => p.count));
  const width = 100;
  const height = 40;
  const gap = 1;
  const barWidth = points.length > 0 ? (width - gap * (points.length - 1)) / points.length : width;
  return (
    <svg
      viewBox={`0 0 ${String(width)} ${String(height)}`}
      className="h-16 w-full"
      preserveAspectRatio="none"
      role="img"
      aria-label="Message volume trend"
    >
      {points.map((point, i) => {
        const barHeight = (point.count / max) * height;
        return (
          <rect
            key={point.date}
            data-testid="volume-bar"
            x={i * (barWidth + gap)}
            y={height - barHeight}
            width={barWidth}
            height={barHeight}
            className="fill-primary/70"
          >
            <title>{`${point.date}: ${String(point.count)}`}</title>
          </rect>
        );
      })}
    </svg>
  );
}

function Stat({ label, value }: { label: string; value: string }): React.JSX.Element {
  return (
    <div className="rounded-md border p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}

const HOUR_LABEL = (hour: number): string => {
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  return `${String(h12)}${hour < 12 ? 'am' : 'pm'}`;
};

/** Group analytics tab (P2.5): volume trend + key stats over a window. */
export default function GroupAnalytics({ groupName }: { groupName: string }): React.JSX.Element {
  const analytics = useQuery({
    queryKey: ['group-analytics', groupName],
    queryFn: () => client.groupAnalytics(groupName),
  });

  if (analytics.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading analytics…</p>;
  }
  if (analytics.isError || !analytics.data) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Failed to load analytics.
      </p>
    );
  }
  const a = analytics.data;

  return (
    <div className="space-y-3" data-testid="group-analytics">
      <div>
        <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
          <span>Messages · last {a.days} days</span>
          <span>{a.total_messages} total</span>
        </div>
        <VolumeChart points={a.volume_trend} />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Stat label="Active members" value={`${String(a.active_member_pct)}%`} />
        <Stat
          label="Avg response"
          value={a.avg_response_mins === null ? '—' : `${String(a.avg_response_mins)}m`}
        />
        <Stat label="Answered queries" value={String(a.answered_queries)} />
        <Stat label="Unanswered now" value={String(a.unanswered_now)} />
      </div>

      {a.top_contributors.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-muted-foreground">Top contributors</h4>
          <ul className="mt-1 space-y-0.5">
            {a.top_contributors.map((c) => (
              <li
                key={c.display}
                data-testid="contributor-row"
                className="flex justify-between text-sm"
              >
                <span className="truncate">{c.display}</span>
                <span className="text-muted-foreground">{c.messages}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {a.best_posting_hours.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-muted-foreground">Busiest hours</h4>
          <p className="mt-1 text-sm">
            {a.best_posting_hours.map((h) => HOUR_LABEL(h.hour)).join(', ')}
          </p>
        </div>
      )}
    </div>
  );
}
