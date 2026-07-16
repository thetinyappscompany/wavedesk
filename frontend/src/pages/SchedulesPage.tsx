import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Clock, Play, Plus, Trash2, X } from 'lucide-react';
import type {
  WdRecurrence,
  WdScheduledMessage,
  WdScheduleTargetType,
  WdScheduleType,
} from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { useWorkspaceEvents } from '@/lib/realtime';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const TARGETS: { value: WdScheduleTargetType; label: string }[] = [
  { value: 'chat', label: 'Chat' },
  { value: 'group', label: 'Group' },
  { value: 'broadcast', label: 'Broadcast' },
];
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

function Composer({ onDone }: { onDone: () => void }): React.JSX.Element {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState('');
  const [targetType, setTargetType] = useState<WdScheduleTargetType>('chat');
  const [target, setTarget] = useState('');
  const [body, setBody] = useState('');
  const [scheduleType, setScheduleType] = useState<WdScheduleType>('once');
  const [when, setWhen] = useState('');
  const [frequency, setFrequency] = useState<'daily' | 'weekly'>('daily');
  const [time, setTime] = useState('09:00');
  const [weekdays, setWeekdays] = useState<number[]>([0]);

  const create = useMutation({
    mutationFn: () => {
      const recurrence: WdRecurrence = {
        frequency,
        time,
        ...(frequency === 'weekly' ? { weekdays } : {}),
      };
      return client.createSchedule({
        title: title.trim(),
        targetType,
        target: target.trim(),
        scheduleType,
        ...(targetType !== 'broadcast' ? { body } : {}),
        ...(scheduleType === 'once'
          ? { scheduledAt: when ? `${when.replace('T', ' ')}:00` : undefined }
          : { recurrence }),
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['schedules'] });
      onDone();
    },
  });

  const needsBody = targetType !== 'broadcast';
  const canSave =
    title.trim() &&
    target.trim() &&
    (!needsBody || body.trim()) &&
    (scheduleType === 'once' ? Boolean(when) : true);

  return (
    <form
      className="space-y-3 rounded-lg border p-4"
      data-testid="schedule-composer"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSave) {
          create.mutate();
        }
      }}
    >
      <Input
        aria-label="Schedule title"
        placeholder="e.g. Monday standup ping"
        value={title}
        onChange={(e) => {
          setTitle(e.target.value);
        }}
      />
      <div className="flex flex-wrap gap-2">
        <select
          aria-label="Target type"
          value={targetType}
          onChange={(e) => {
            setTargetType(e.target.value as WdScheduleTargetType);
          }}
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
        >
          {TARGETS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <Input
          aria-label="Target id"
          placeholder={`${targetType} id`}
          value={target}
          onChange={(e) => {
            setTarget(e.target.value);
          }}
        />
      </div>

      {needsBody && (
        <textarea
          aria-label="Message body"
          placeholder="Good morning team! 🌞"
          value={body}
          rows={2}
          onChange={(e) => {
            setBody(e.target.value);
          }}
          className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
        />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Schedule type"
          value={scheduleType}
          onChange={(e) => {
            setScheduleType(e.target.value as WdScheduleType);
          }}
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
        >
          <option value="once">Once</option>
          <option value="recurring">Recurring</option>
        </select>

        {scheduleType === 'once' ? (
          <Input
            aria-label="Send at"
            type="datetime-local"
            className="w-56"
            value={when}
            onChange={(e) => {
              setWhen(e.target.value);
            }}
          />
        ) : (
          <>
            <select
              aria-label="Frequency"
              value={frequency}
              onChange={(e) => {
                setFrequency(e.target.value as 'daily' | 'weekly');
              }}
              className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
            >
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </select>
            <Input
              aria-label="Time"
              type="time"
              className="w-32"
              value={time}
              onChange={(e) => {
                setTime(e.target.value);
              }}
            />
          </>
        )}
      </div>

      {scheduleType === 'recurring' && frequency === 'weekly' && (
        <div className="flex flex-wrap gap-1" role="group" aria-label="Weekdays">
          {DAYS.map((d, i) => (
            <button
              key={d}
              type="button"
              aria-label={d}
              aria-pressed={weekdays.includes(i)}
              className={`rounded border px-2 py-1 text-xs ${
                weekdays.includes(i) ? 'bg-primary text-primary-foreground' : ''
              }`}
              onClick={() => {
                setWeekdays((w) => (w.includes(i) ? w.filter((x) => x !== i) : [...w, i]));
              }}
            >
              {d}
            </button>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <Button type="submit" disabled={!canSave || create.isPending}>
          Schedule
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
      {create.isError && (
        <p role="alert" className="text-xs text-destructive">
          {errorText(create.error)}
        </p>
      )}
    </form>
  );
}

function summary(s: WdScheduledMessage): string {
  if (s.schedule_type === 'once') {
    return s.next_run_at ? `once · ${s.next_run_at}` : 'once';
  }
  const r = s.recurrence as WdRecurrence;
  const days =
    r.frequency === 'weekly' && r.weekdays
      ? ' · ' + r.weekdays.map((d) => DAYS[d]).join(',')
      : '';
  return `${r.frequency ?? 'recurring'} at ${r.time ?? ''}${days}`;
}

export default function SchedulesPage(): React.JSX.Element {
  useWorkspaceEvents();
  const queryClient = useQueryClient();
  const [building, setBuilding] = useState(false);
  const schedules = useQuery({
    queryKey: ['schedules'],
    queryFn: () => client.listSchedules(),
    refetchInterval: 30_000,
  });
  const onSuccess = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['schedules'] });
  };
  const toggle = useMutation({
    mutationFn: (c: { name: string; enabled: boolean }) =>
      client.updateSchedule(c.name, { enabled: c.enabled }),
    onSuccess,
  });
  const cancel = useMutation({ mutationFn: (n: string) => client.cancelSchedule(n), onSuccess });
  const runNow = useMutation({ mutationFn: (n: string) => client.runScheduleNow(n), onSuccess });
  const remove = useMutation({ mutationFn: (n: string) => client.deleteSchedule(n), onSuccess });

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div className="flex items-center gap-3">
        <Clock className="h-5 w-5" />
        <h1 className="text-lg font-semibold">Scheduled messages</h1>
        {!building && (
          <Button size="sm" onClick={() => setBuilding(true)}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            New schedule
          </Button>
        )}
      </div>

      {building && (
        <Composer
          onDone={() => {
            setBuilding(false);
          }}
        />
      )}

      <ul className="space-y-2">
        {(schedules.data ?? []).map((s) => (
          <li
            key={s.name}
            data-testid="schedule-row"
            className="flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate font-medium">{s.title}</span>
                <span className="rounded border px-1 text-[10px] text-muted-foreground">
                  {s.target_type}
                </span>
                <span className="rounded border px-1 text-[10px] text-muted-foreground">
                  {s.status}
                </span>
              </div>
              <div className="truncate text-xs text-muted-foreground">{summary(s)}</div>
            </div>
            {s.status === 'scheduled' && (
              <>
                <button
                  type="button"
                  aria-label={`Run ${s.title} now`}
                  className="rounded p-1 text-emerald-600 hover:bg-accent"
                  onClick={() => {
                    runNow.mutate(s.name);
                  }}
                >
                  <Play className="h-3.5 w-3.5" />
                </button>
                <label className="flex items-center gap-1 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    aria-label={`Enable ${s.title}`}
                    checked={s.enabled}
                    onChange={(e) => {
                      toggle.mutate({ name: s.name, enabled: e.target.checked });
                    }}
                  />
                  on
                </label>
                <button
                  type="button"
                  aria-label={`Cancel ${s.title}`}
                  className="rounded p-1 text-destructive hover:bg-accent"
                  onClick={() => {
                    cancel.mutate(s.name);
                  }}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </>
            )}
            {s.status !== 'scheduled' && (
              <button
                type="button"
                aria-label={`Delete ${s.title}`}
                className="rounded p-1 text-destructive hover:bg-accent"
                onClick={() => {
                  remove.mutate(s.name);
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </li>
        ))}
        {schedules.data?.length === 0 && !building && (
          <li className="rounded-lg border px-3 py-6 text-center text-sm text-muted-foreground">
            No schedules yet — queue a one-time or recurring message.
          </li>
        )}
      </ul>
    </div>
  );
}
