import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { WdBusinessHours, WdWorkspaceSettings } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const DAYS: { key: keyof WdBusinessHours['days']; label: string }[] = [
  { key: 'mon', label: 'Mon' },
  { key: 'tue', label: 'Tue' },
  { key: 'wed', label: 'Wed' },
  { key: 'thu', label: 'Thu' },
  { key: 'fri', label: 'Fri' },
  { key: 'sat', label: 'Sat' },
  { key: 'sun', label: 'Sun' },
];

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

/** Business hours + holiday calendar + out-of-office auto-reply (P3.2). */
export default function BusinessHoursCard({
  canManage,
  settings,
}: {
  canManage: boolean;
  settings: WdWorkspaceSettings;
}): React.JSX.Element {
  const queryClient = useQueryClient();
  // Defensive default: a settings payload missing business_hours must never
  // crash the whole Settings page (reading `.enabled` off undefined).
  const bh: WdBusinessHours = settings.business_hours ?? {
    enabled: false,
    timezone: 'Asia/Kolkata',
    days: {},
    holidays: [],
  };
  const [enabled, setEnabled] = useState(bh.enabled);
  const [timezone, setTimezone] = useState(bh.timezone);
  const [days, setDays] = useState<WdBusinessHours['days']>(bh.days);
  const [holidays, setHolidays] = useState((bh.holidays ?? []).join(', '));
  const [oooEnabled, setOooEnabled] = useState(settings.ooo_reply_enabled ?? false);
  const [oooMessage, setOooMessage] = useState(settings.ooo_reply_message ?? '');

  const save = useMutation({
    mutationFn: () =>
      client.updateWorkspaceSettings({
        business_hours: {
          enabled,
          timezone: timezone.trim() || 'Asia/Kolkata',
          days,
          holidays: holidays
            .split(/[\s,]+/)
            .map((d) => d.trim())
            .filter(Boolean),
        } satisfies WdBusinessHours,
        ooo_reply_enabled: oooEnabled,
        ooo_reply_message: oooMessage,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['workspace-settings'] });
    },
  });

  const setDay = (key: keyof WdBusinessHours['days'], open: string, close: string): void => {
    setDays((d) => ({ ...d, [key]: { open, close } }));
  };
  const clearDay = (key: keyof WdBusinessHours['days']): void => {
    setDays((d) => {
      const next = { ...d };
      delete next[key];
      return next;
    });
  };

  return (
    <section aria-label="Business hours" className="rounded-lg border p-4">
      <h2 className="font-semibold">Business hours</h2>
      <p className="mb-3 text-sm text-muted-foreground">
        Outside these hours (and on holidays) new customer DMs can get an automatic reply.
      </p>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          aria-label="Enable business hours"
          checked={enabled}
          disabled={!canManage}
          onChange={(e) => {
            setEnabled(e.target.checked);
          }}
        />
        Enforce business hours (off = always open)
      </label>

      <label className="mt-3 block text-sm" htmlFor="bh-timezone">
        Timezone
      </label>
      <Input
        id="bh-timezone"
        aria-label="Business hours timezone"
        className="mt-1 w-56"
        value={timezone}
        disabled={!canManage}
        onChange={(e) => {
          setTimezone(e.target.value);
        }}
      />

      <div className="mt-3 space-y-1">
        {DAYS.map(({ key, label }) => {
          const window = days[key];
          const on = Boolean(window);
          return (
            <div key={key} className="flex items-center gap-2 text-sm" data-testid="bh-day-row">
              <label className="flex w-20 items-center gap-1">
                <input
                  type="checkbox"
                  aria-label={`Open on ${label}`}
                  checked={on}
                  disabled={!canManage}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setDay(key, window?.open ?? '09:00', window?.close ?? '18:00');
                    } else {
                      clearDay(key);
                    }
                  }}
                />
                {label}
              </label>
              <Input
                aria-label={`${label} open`}
                type="time"
                className="h-8 w-32"
                value={window?.open ?? '09:00'}
                disabled={!canManage || !on}
                onChange={(e) => {
                  setDay(key, e.target.value, window?.close ?? '18:00');
                }}
              />
              <span className="text-muted-foreground">–</span>
              <Input
                aria-label={`${label} close`}
                type="time"
                className="h-8 w-32"
                value={window?.close ?? '18:00'}
                disabled={!canManage || !on}
                onChange={(e) => {
                  setDay(key, window?.open ?? '09:00', e.target.value);
                }}
              />
            </div>
          );
        })}
      </div>

      <label className="mt-3 block text-sm" htmlFor="bh-holidays">
        Holidays
        <span className="block text-xs text-muted-foreground">
          Comma-separated ISO dates (YYYY-MM-DD) — closed all day.
        </span>
      </label>
      <Input
        id="bh-holidays"
        aria-label="Holidays"
        className="mt-1"
        placeholder="2026-01-26, 2026-08-15"
        value={holidays}
        disabled={!canManage}
        onChange={(e) => {
          setHolidays(e.target.value);
        }}
      />

      <div className="mt-4 border-t pt-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            aria-label="Enable out-of-office auto-reply"
            checked={oooEnabled}
            disabled={!canManage}
            onChange={(e) => {
              setOooEnabled(e.target.checked);
            }}
          />
          Send an out-of-office auto-reply
        </label>
        <textarea
          aria-label="Out-of-office message"
          className="mt-2 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          rows={2}
          placeholder="Thanks for your message! We're closed and will reply during business hours."
          value={oooMessage}
          disabled={!canManage}
          onChange={(e) => {
            setOooMessage(e.target.value);
          }}
        />
      </div>

      {canManage && (
        <Button
          className="mt-3"
          disabled={save.isPending}
          onClick={() => {
            save.mutate();
          }}
        >
          Save business hours
        </Button>
      )}
      {save.isError && (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {errorText(save.error)}
        </p>
      )}
      {save.isSuccess && (
        <p className="mt-2 text-xs text-muted-foreground" role="status">
          Saved.
        </p>
      )}
    </section>
  );
}
