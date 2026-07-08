import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import InvitePage from './InvitePage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: { acceptInvite: vi.fn() },
}));

function renderPage(token = 'tok-123') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/invite/${token}`]}>
        <Routes>
          <Route path="/invite/:token" element={<InvitePage />} />
          <Route path="/inbox" element={<div>INBOX PROBE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('InvitePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('accepts the invite with name + password and lands in the inbox', async () => {
    vi.mocked(client.acceptInvite).mockResolvedValue({
      workspace: 'WS-1',
      workspace_name: 'Asha & Co',
      user: 'riya@x.test',
      new_user: true,
    });
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText('Your name'), 'Riya S');
    await user.type(screen.getByLabelText('Choose a password'), 'sup3r-secret');
    await user.click(screen.getByRole('button', { name: 'Accept invite' }));

    expect(client.acceptInvite).toHaveBeenCalledWith('tok-123', {
      full_name: 'Riya S',
      password: 'sup3r-secret',
    });
    expect(await screen.findByText('INBOX PROBE')).toBeInTheDocument();
  });

  it('existing users can accept without a password', async () => {
    vi.mocked(client.acceptInvite).mockResolvedValue({
      workspace: 'WS-1',
      workspace_name: 'Asha & Co',
      user: 'riya@x.test',
      new_user: false,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: 'Accept invite' }));
    expect(client.acceptInvite).toHaveBeenCalledWith('tok-123', {});
  });

  it('surfaces invalid-token errors', async () => {
    vi.mocked(client.acceptInvite).mockRejectedValue(new Error('link is invalid'));
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: 'Accept invite' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid/);
  });
});
