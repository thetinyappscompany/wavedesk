import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AccessControlCard from './AccessControlCard';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: { getIpAllowlist: vi.fn(), setIpAllowlist: vi.fn() },
}));

function renderCard(canManage = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <AccessControlCard canManage={canManage} />
    </QueryClientProvider>,
  );
}

describe('AccessControlCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.getIpAllowlist).mockResolvedValue(['10.0.0.0/8']);
  });

  it('shows the current allowlist and saves edits as a parsed list', async () => {
    vi.mocked(client.setIpAllowlist).mockResolvedValue({ ip_allowlist: ['10.0.0.0/8', '203.0.113.5/32'] });
    renderCard();
    const box = await screen.findByLabelText('IP allowlist');
    await waitFor(() => expect(box).toHaveValue('10.0.0.0/8'));
    await userEvent.type(box, '\n203.0.113.5');
    await userEvent.click(screen.getByRole('button', { name: 'Save allowlist' }));
    await waitFor(() =>
      expect(client.setIpAllowlist).toHaveBeenCalledWith(['10.0.0.0/8', '203.0.113.5']),
    );
  });

  it('hides save without manage rights', async () => {
    renderCard(false);
    await screen.findByLabelText('IP allowlist');
    expect(screen.queryByRole('button', { name: 'Save allowlist' })).not.toBeInTheDocument();
  });
});
