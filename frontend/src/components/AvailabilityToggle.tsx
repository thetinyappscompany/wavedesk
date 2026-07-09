import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { client } from '@/lib/client';
import { cn } from '@/lib/utils';

const HEARTBEAT_MS = 30_000; // keep the online key (60s TTL server-side) warm

/** Agent availability control (P3.2) — an online heartbeat plus a manual
 * "taking chats / paused" toggle that gates auto-routing. Sits in the nav rail. */
export default function AvailabilityToggle(): React.JSX.Element {
  const queryClient = useQueryClient();
  const availability = useQuery({
    queryKey: ['availability'],
    queryFn: () => client.getAvailability(),
    refetchInterval: HEARTBEAT_MS,
  });

  // Heartbeat on a timer so the server keeps the agent eligible for routing.
  useEffect(() => {
    void client.routingHeartbeat();
    const id = setInterval(() => {
      void client.routingHeartbeat();
    }, HEARTBEAT_MS);
    return () => {
      clearInterval(id);
    };
  }, []);

  const toggle = useMutation({
    mutationFn: (available: boolean) => client.setAvailability(available),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['availability'] });
    },
  });

  const available = availability.data?.available ?? true;

  return (
    <button
      type="button"
      aria-label={available ? 'Pause new assignments' : 'Resume taking chats'}
      aria-pressed={available}
      className="mt-2 flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent"
      onClick={() => {
        toggle.mutate(!available);
      }}
      disabled={toggle.isPending}
    >
      <span
        data-testid="availability-dot"
        className={cn(
          'h-2.5 w-2.5 shrink-0 rounded-full',
          available ? 'bg-emerald-500' : 'bg-muted-foreground/40',
        )}
      />
      <span className="hidden md:inline">{available ? 'Available' : 'Paused'}</span>
    </button>
  );
}
