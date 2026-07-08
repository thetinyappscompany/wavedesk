import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { client } from '@/lib/client';
import InvitePanel from '@/components/InvitePanel';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { cn } from '@/lib/utils';

const STEPS = ['Workspace', 'Connect a number', 'Invite your team'] as const;

function StepDots({ current }: { current: number }): React.JSX.Element {
  return (
    <ol className="mb-4 flex items-center justify-center gap-2" aria-label="Onboarding steps">
      {STEPS.map((label, index) => (
        <li key={label} className="flex items-center gap-2 text-xs">
          <span
            className={cn(
              'flex h-5 w-5 items-center justify-center rounded-full border text-[10px]',
              index === current
                ? 'border-primary bg-primary text-primary-foreground'
                : 'text-muted-foreground',
            )}
          >
            {index + 1}
          </span>
          <span className={index === current ? 'font-medium' : 'text-muted-foreground'}>
            {label}
          </span>
        </li>
      ))}
    </ol>
  );
}

export default function OnboardingPage(): React.JSX.Element {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ['onboarding'],
    queryFn: () => client.onboardingStatus(),
  });
  const [workspaceName, setWorkspaceName] = useState('');
  const [numberSkipped, setNumberSkipped] = useState(false);

  const createWorkspace = useMutation({
    mutationFn: () => client.createWorkspace(workspaceName.trim()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['onboarding'] });
      void queryClient.invalidateQueries({ queryKey: ['workspace-settings'] });
    },
  });

  const step = !status.data?.has_workspace
    ? 0
    : (status.data.connected_numbers ?? 0) === 0 && !numberSkipped
      ? 1
      : 2;

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-lg">
        <CardHeader className="space-y-1 text-center">
          <CardTitle className="text-2xl">Welcome to WaveDesk</CardTitle>
          <CardDescription>
            {status.data?.workspace_name ?? 'Set up your team inbox in three steps'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {status.isLoading ? (
            <p className="text-center text-sm text-muted-foreground">Loading…</p>
          ) : (
            <>
              <StepDots current={step} />

              {step === 0 && (
                <form
                  className="space-y-3"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (workspaceName.trim()) {
                      createWorkspace.mutate();
                    }
                  }}
                >
                  <label className="block text-sm font-medium" htmlFor="workspace-name">
                    Name your workspace
                  </label>
                  <Input
                    id="workspace-name"
                    placeholder="e.g. Asha Traders"
                    value={workspaceName}
                    onChange={(e) => {
                      setWorkspaceName(e.target.value);
                    }}
                  />
                  <Button
                    type="submit"
                    className="w-full"
                    disabled={!workspaceName.trim() || createWorkspace.isPending}
                  >
                    Create workspace
                  </Button>
                  {createWorkspace.isError && (
                    <p role="alert" className="text-sm text-destructive">
                      {createWorkspace.error.message}
                    </p>
                  )}
                  <p className="text-center text-xs text-muted-foreground">
                    Starts a free 14-day trial — no card needed.
                  </p>
                </form>
              )}

              {step === 1 && (
                <div className="space-y-3 text-center">
                  <p className="text-sm text-muted-foreground">
                    Connect your first WhatsApp number — scan a QR from the phone that owns it,
                    or plug in Cloud API credentials.
                  </p>
                  <Button
                    className="w-full"
                    onClick={() => {
                      void navigate('/numbers');
                    }}
                  >
                    Connect a number
                  </Button>
                  <Button
                    variant="ghost"
                    className="w-full"
                    onClick={() => {
                      setNumberSkipped(true);
                    }}
                  >
                    Skip for now
                  </Button>
                </div>
              )}

              {step === 2 && (
                <div className="space-y-4">
                  <InvitePanel canManage={status.data?.role !== 'Agent'} />
                  <Button
                    className="w-full"
                    onClick={() => {
                      void navigate('/inbox');
                    }}
                  >
                    Go to your inbox
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
