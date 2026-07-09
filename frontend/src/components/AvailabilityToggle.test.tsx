import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AvailabilityToggle from './AvailabilityToggle';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    getAvailability: vi.fn(),
    setAvailability: vi.fn(),
    routingHeartbeat: vi.fn(),
  },
}));

function renderToggle() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AvailabilityToggle />
    </QueryClientProvider>,
  );
}

describe('AvailabilityToggle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.routingHeartbeat).mockResolvedValue({ online: true });
  });

  it('heartbeats on mount and shows availability', async () => {
    vi.mocked(client.getAvailability).mockResolvedValue({ available: true, online: true });
    renderToggle();
    await waitFor(() => {
      expect(client.routingHeartbeat).toHaveBeenCalled();
    });
    expect(await screen.findByText('Available')).toBeInTheDocument();
  });

  it('toggles to paused', async () => {
    vi.mocked(client.getAvailability).mockResolvedValue({ available: true, online: true });
    vi.mocked(client.setAvailability).mockResolvedValue({ available: false });
    const user = userEvent.setup();
    renderToggle();
    await user.click(await screen.findByRole('button', { name: 'Pause new assignments' }));
    expect(client.setAvailability).toHaveBeenCalledWith(false);
  });

  it('shows paused state', async () => {
    vi.mocked(client.getAvailability).mockResolvedValue({ available: false, online: true });
    renderToggle();
    expect(await screen.findByText('Paused')).toBeInTheDocument();
  });
});
