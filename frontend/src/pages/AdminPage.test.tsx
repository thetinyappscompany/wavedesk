import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AdminPage from './AdminPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    adminWhoami: vi.fn(),
    adminPlatformStats: vi.fn(),
    adminListWorkspaces: vi.fn(),
    adminSuspendWorkspace: vi.fn(),
    adminUnsuspendWorkspace: vi.fn(),
    adminSetSendRateClamp: vi.fn(),
    adminCreditWallet: vi.fn(),
  },
}));

const STATS = {
  totals: { workspaces: 7, users: 12, messages: 3400, contacts: 890, numbers: 5 },
  operational: { suspended: 1 },
  by_subscription_status: { active: 3, trialing: 2, past_due: 1, suspended: 0, cancelled: 1, none: 0 },
  trial_vs_paid: { trial: 2, paid: 3, past_due: 1 },
  by_plan: [
    { plan: 'Pro', count: 4 },
    { plan: 'Trial', count: 3 },
  ],
};

const WS = {
  name: 'WS-00001',
  workspace_name: 'Acme',
  plan: 'Pro',
  owner_user: 'owner@acme.test',
  suspended: false,
  send_rate_clamp: 0,
  members: 3,
  messages_total: 42,
  subscription_status: 'active',
  creation: '2026-07-11 12:00:00',
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/admin']}>
        <Routes>
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/inbox" element={<div>inbox</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AdminPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.adminListWorkspaces).mockResolvedValue([WS]);
    vi.mocked(client.adminPlatformStats).mockResolvedValue(STATS);
  });

  it('redirects non-admins to the inbox', async () => {
    vi.mocked(client.adminWhoami).mockResolvedValue(false);
    renderPage();
    expect(await screen.findByText('inbox')).toBeInTheDocument();
    expect(client.adminListWorkspaces).not.toHaveBeenCalled();
  });

  it('lists workspaces for a platform admin', async () => {
    vi.mocked(client.adminWhoami).mockResolvedValue(true);
    renderPage();
    expect(await screen.findByText('Acme')).toBeInTheDocument();
    expect(screen.getByText('WS-00001')).toBeInTheDocument();
  });

  it('shows the platform-stats overview', async () => {
    vi.mocked(client.adminWhoami).mockResolvedValue(true);
    renderPage();
    // totals
    expect(await screen.findByText('Workspaces')).toBeInTheDocument();
    expect(screen.getByText('3,400')).toBeInTheDocument(); // messages, locale-formatted
    expect(screen.getByText('Users')).toBeInTheDocument();
    // breakdown line
    expect(screen.getByText('paid')).toBeInTheDocument();
    expect(screen.getByText(/Pro:/)).toBeInTheDocument();
  });

  it('suspends a workspace', async () => {
    vi.mocked(client.adminWhoami).mockResolvedValue(true);
    vi.mocked(client.adminSuspendWorkspace).mockResolvedValue({ suspended: true });
    renderPage();
    await screen.findByText('Acme');
    await userEvent.click(screen.getByRole('button', { name: 'Suspend' }));
    await waitFor(() =>
      expect(client.adminSuspendWorkspace).toHaveBeenCalledWith('WS-00001', expect.any(String)),
    );
  });

  it('credits a workspace wallet with a fresh idempotency key', async () => {
    vi.mocked(client.adminWhoami).mockResolvedValue(true);
    vi.mocked(client.adminCreditWallet).mockResolvedValue({ balance: 300 });
    renderPage();
    await screen.findByText('Acme');
    const creditBtn = screen.getByRole('button', { name: 'Credit' });
    expect(creditBtn).toBeDisabled(); // no amount yet
    await userEvent.type(screen.getByLabelText('Credit wallet for Acme'), '300');
    await userEvent.click(creditBtn);
    await waitFor(() =>
      expect(client.adminCreditWallet).toHaveBeenCalledWith(
        'WS-00001',
        300,
        expect.any(String),
        expect.any(String), // one idempotency key per submit
      ),
    );
  });

  it('sets a send-rate clamp on blur', async () => {
    vi.mocked(client.adminWhoami).mockResolvedValue(true);
    vi.mocked(client.adminSetSendRateClamp).mockResolvedValue({ send_rate_clamp: 500 });
    renderPage();
    await screen.findByText('Acme');
    const input = screen.getByLabelText('Send clamp for Acme');
    await userEvent.clear(input);
    await userEvent.type(input, '500');
    await userEvent.tab();
    await waitFor(() =>
      expect(client.adminSetSendRateClamp).toHaveBeenCalledWith('WS-00001', 500),
    );
  });
});
