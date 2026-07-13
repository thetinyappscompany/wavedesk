import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy } from 'lucide-react';
import type { WdTwoFactorEnroll } from '@wavedesk/api-client';

import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

/**
 * Account security (P5): per-user TOTP two-factor auth + active-session control.
 * Self-service — every user manages their own account here.
 */
export default function SecurityCard(): React.JSX.Element {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ['twofa-status'], queryFn: () => client.twofaStatus() });
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: () => client.listSessions() });

  const [enroll, setEnroll] = useState<WdTwoFactorEnroll | null>(null);
  const [code, setCode] = useState('');
  const [recovery, setRecovery] = useState<string[] | null>(null);

  const invalidate = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['twofa-status'] });
  };

  const begin = useMutation({
    mutationFn: () => client.twofaBeginEnroll(),
    onSuccess: (data) => {
      setEnroll(data);
      setRecovery(null);
    },
  });
  const confirm = useMutation({
    mutationFn: () => client.twofaConfirm(code),
    onSuccess: (data) => {
      setEnroll(null);
      setCode('');
      setRecovery(data.recovery_codes);
      invalidate();
    },
  });
  const disable = useMutation({
    mutationFn: () => client.twofaDisable(code),
    onSuccess: () => {
      setCode('');
      invalidate();
    },
  });
  const revoke = useMutation({
    mutationFn: (sidTail: string) => client.revokeSession(sidTail),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['sessions'] }),
  });
  const revokeOthers = useMutation({
    mutationFn: () => client.revokeOtherSessions(),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['sessions'] }),
  });

  return (
    <section className="rounded-lg border p-4" data-testid="security-card">
      <h3 className="font-semibold">Security</h3>
      <p className="mb-3 text-sm text-muted-foreground">
        Two-factor authentication (TOTP) and your active sign-ins.
      </p>

      {/* 2FA */}
      <div className="mb-4">
        <div className="mb-1 flex items-center gap-2 text-sm">
          <span className="font-medium">Two-factor auth</span>
          <span
            data-testid="twofa-state"
            className={status.data ? 'text-emerald-600' : 'text-muted-foreground'}
          >
            {status.data ? 'enabled' : 'disabled'}
          </span>
        </div>

        {status.data === false && !enroll && (
          <Button size="sm" variant="outline" disabled={begin.isPending} onClick={() => begin.mutate()}>
            Enable 2FA
          </Button>
        )}

        {enroll && (
          <div className="space-y-2 rounded border p-2" data-testid="twofa-enroll">
            <p className="text-xs text-muted-foreground">
              Add this secret to your authenticator app, then enter the 6-digit code.
            </p>
            <code className="block break-all rounded bg-muted px-2 py-1 text-xs">{enroll.secret}</code>
            <div className="flex gap-2">
              <Input
                aria-label="2FA code"
                placeholder="000000"
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
              <Button
                size="sm"
                disabled={code.length < 6 || confirm.isPending}
                onClick={() => confirm.mutate()}
              >
                Confirm
              </Button>
            </div>
          </div>
        )}

        {recovery && (
          <div
            className="mt-2 rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs"
            data-testid="recovery-codes"
          >
            <p className="mb-1 font-medium">Save these recovery codes — shown once:</p>
            <div className="grid grid-cols-2 gap-1 font-mono">
              {recovery.map((c) => (
                <span key={c}>{c}</span>
              ))}
            </div>
            <button
              type="button"
              className="mt-1 inline-flex items-center gap-1 text-primary"
              onClick={() => void navigator.clipboard?.writeText(recovery.join('\n'))}
            >
              <Copy className="h-3 w-3" /> copy all
            </button>
          </div>
        )}

        {status.data === true && (
          <div className="mt-1 flex gap-2">
            <Input
              aria-label="2FA disable code"
              placeholder="Code to disable"
              className="max-w-40"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
            <Button
              size="sm"
              variant="destructive"
              disabled={code.length < 6 || disable.isPending}
              onClick={() => disable.mutate()}
            >
              Disable
            </Button>
          </div>
        )}
      </div>

      {/* Sessions */}
      <div>
        <div className="mb-1 flex items-center justify-between">
          <h4 className="text-xs font-medium uppercase text-muted-foreground">Active sessions</h4>
          <button
            type="button"
            className="text-xs text-primary"
            onClick={() => revokeOthers.mutate()}
          >
            Sign out other sessions
          </button>
        </div>
        <ul className="space-y-1" data-testid="session-list">
          {(sessions.data ?? []).map((s) => (
            <li key={s.sid_tail} className="flex items-center gap-2 text-xs">
              <span className="font-mono">…{s.sid_tail}</span>
              <span className="text-muted-foreground">{s.ip ?? 'unknown ip'}</span>
              {s.current && <span className="text-emerald-600">this device</span>}
              {!s.current && (
                <button
                  type="button"
                  className="ml-auto text-destructive"
                  aria-label={`Revoke session ${s.sid_tail}`}
                  onClick={() => revoke.mutate(s.sid_tail)}
                >
                  revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>

      {(begin.isError || confirm.isError || disable.isError) && (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {errorText(begin.error ?? confirm.error ?? disable.error)}
        </p>
      )}
    </section>
  );
}
