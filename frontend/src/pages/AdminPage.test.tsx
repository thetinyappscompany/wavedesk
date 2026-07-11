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
    adminListWorkspaces: vi.fn(),
    adminSuspendWorkspace: vi.fn(),
    adminUnsuspendWorkspace: vi.fn(),
    adminSetSendRateClamp: vi.fn(),
  },
}));

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
