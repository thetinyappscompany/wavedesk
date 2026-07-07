import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { WdNumber } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

const STATUS_STYLES: Record<WdNumber['status'], string> = {
  connected: 'bg-primary/15 text-primary',
  connecting: 'bg-amber-500/15 text-amber-600',
  disconnected: 'bg-muted text-muted-foreground',
  banned: 'bg-destructive/15 text-destructive',
};

function StatusBadge({ status }: { status: WdNumber['status'] }): React.JSX.Element {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}>
      {status}
    </span>
  );
}

function TransportBadge({ transport }: { transport: WdNumber['connection_type'] }): React.JSX.Element {
  return (
    <span className="rounded border px-1.5 py-0.5 text-xs text-muted-foreground">
      {transport === 'baileys' ? 'Linked device' : 'Cloud API'}
    </span>
  );
}

function BaileysConnectPanel({ onDone }: { onDone: () => void }): React.JSX.Element {
  const [numberName, setNumberName] = useState<string | null>(null);

  const connect = useMutation({
    mutationFn: () => client.connectBaileys(),
    onSuccess: (result) => {
      setNumberName(result.number);
    },
  });

  const status = useQuery({
    queryKey: ['number-status', numberName],
    queryFn: () => client.numberStatus(numberName as string),
    enabled: numberName !== null,
    refetchInterval: (query) => (query.state.data?.status === 'connected' ? false : 2500),
  });

  if (!numberName) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">
          Links a regular WhatsApp number via QR scan (Settings → Linked devices).
        </p>
        <Button onClick={() => connect.mutate()} disabled={connect.isPending}>
          {connect.isPending ? 'Starting…' : 'Start QR pairing'}
        </Button>
        {connect.isError && (
          <p role="alert" className="text-sm text-destructive">
            {connect.error.message}
          </p>
        )}
      </div>
    );
  }

  if (status.data?.status === 'connected') {
    return (
      <div className="space-y-3">
        <p className="text-sm font-medium text-primary">Connected ✓</p>
        <Button variant="secondary" onClick={onDone}>
          Done
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Scan with WhatsApp on your phone: Settings → Linked devices → Link a device.
      </p>
      {status.data?.qr ? (
        <img src={status.data.qr} alt="WhatsApp pairing QR code" className="h-52 w-52" />
      ) : (
        <p className="text-sm text-muted-foreground">Waiting for QR…</p>
      )}
    </div>
  );
}

function CloudConnectPanel({ onDone }: { onDone: () => void }): React.JSX.Element {
  const [form, setForm] = useState({ phone: '', phone_number_id: '', waba_id: '', token: '' });
  const connect = useMutation({
    mutationFn: () => client.connectCloudNumber(form),
    onSuccess: onDone,
  });
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => ({ ...prev, [key]: e.target.value }));
  };

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        connect.mutate();
      }}
    >
      <div className="grid gap-2">
        <Label htmlFor="cloud-phone">Phone (international)</Label>
        <Input id="cloud-phone" value={form.phone} onChange={set('phone')} placeholder="+9198…" />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="cloud-pnid">Phone Number ID</Label>
        <Input id="cloud-pnid" value={form.phone_number_id} onChange={set('phone_number_id')} />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="cloud-waba">WABA ID</Label>
        <Input id="cloud-waba" value={form.waba_id} onChange={set('waba_id')} />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="cloud-token">Permanent access token</Label>
        <Input id="cloud-token" type="password" value={form.token} onChange={set('token')} />
      </div>
      <Button type="submit" disabled={connect.isPending}>
        {connect.isPending ? 'Connecting…' : 'Connect Cloud API number'}
      </Button>
      {connect.isError && (
        <p role="alert" className="text-sm text-destructive">
          {connect.error.message}
        </p>
      )}
    </form>
  );
}

export default function NumbersPage(): React.JSX.Element {
  const queryClient = useQueryClient();
  const [panel, setPanel] = useState<'none' | 'baileys' | 'cloud'>('none');

  const numbers = useQuery({ queryKey: ['numbers'], queryFn: () => client.listNumbers() });

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['numbers'] });
  const disconnect = useMutation({
    mutationFn: (name: string) => client.disconnectNumber(name),
    onSuccess: invalidate,
  });
  const reconnect = useMutation({
    mutationFn: (name: string) => client.reconnectNumber(name),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (name: string) => client.deleteNumber(name),
    onSuccess: invalidate,
  });

  const closePanel = (): void => {
    setPanel('none');
    invalidate();
  };

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">WhatsApp numbers</h1>
          <p className="text-sm text-muted-foreground">
            Connect numbers via linked device (QR) or the official Cloud API.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setPanel('cloud')}>
            Add Cloud API
          </Button>
          <Button onClick={() => setPanel('baileys')}>Connect via QR</Button>
        </div>
      </div>

      {panel !== 'none' && (
        <Card>
          <CardHeader>
            <CardTitle>
              {panel === 'baileys' ? 'Link a WhatsApp number' : 'Cloud API setup'}
            </CardTitle>
            <CardDescription>
              {panel === 'baileys'
                ? 'Keep this open until the status shows connected.'
                : 'From Meta Business: WABA ID, phone number ID and a permanent token.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {panel === 'baileys' ? (
              <BaileysConnectPanel onDone={closePanel} />
            ) : (
              <CloudConnectPanel onDone={closePanel} />
            )}
            <Button variant="ghost" size="sm" className="mt-4" onClick={closePanel}>
              Close
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="space-y-3">
        {numbers.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {numbers.isError && (
          <p role="alert" className="text-sm text-destructive">
            Failed to load numbers — are you logged in?
          </p>
        )}
        {numbers.data?.length === 0 && (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              No numbers yet. Connect your first WhatsApp number to start receiving messages.
            </CardContent>
          </Card>
        )}
        {numbers.data?.map((number) => (
          <Card key={number.name} data-testid="number-row">
            <CardContent className="flex items-center justify-between p-4">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{number.display_name ?? number.phone}</span>
                  <TransportBadge transport={number.connection_type} />
                  <StatusBadge status={number.status} />
                </div>
                <p className="text-sm text-muted-foreground">
                  {number.phone ?? 'number pending pairing'}
                </p>
              </div>
              <div className="flex gap-1">
                {number.status === 'connected' && number.connection_type === 'baileys' && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => disconnect.mutate(number.name)}
                  >
                    Disconnect
                  </Button>
                )}
                {number.status === 'disconnected' && number.connection_type === 'baileys' && (
                  <Button variant="ghost" size="sm" onClick={() => reconnect.mutate(number.name)}>
                    Reconnect
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive"
                  onClick={() => remove.mutate(number.name)}
                >
                  Delete
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </main>
  );
}
