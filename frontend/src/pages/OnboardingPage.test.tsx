import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdOnboardingStatus } from '@wavedesk/api-client';
import OnboardingPage from './OnboardingPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    onboardingStatus: vi.fn(),
    createWorkspace: vi.fn(),
    listMembers: vi.fn(),
    listInvites: vi.fn(),
    inviteMember: vi.fn(),
    revokeInvite: vi.fn(),
  },
}));

function status(overrides: Partial<WdOnboardingStatus> = {}): WdOnboardingStatus {
  return {
    has_workspace: true,
    workspace: 'WS-1',
    workspace_name: 'Asha & Co',
    role: 'Owner',
    connected_numbers: 0,
    total_numbers: 0,
    members: 1,
    pending_invites: 0,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/onboarding']}>
        <Routes>
          <Route path="/onboarding" element={<OnboardingPage />} />
          <Route path="/inbox" element={<div>INBOX PROBE</div>} />
          <Route path="/numbers" element={<div>NUMBERS PROBE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('OnboardingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listMembers).mockResolvedValue([
      { user: 'owner@x.test', role: 'Owner', full_name: 'Owner' },
    ]);
    vi.mocked(client.listInvites).mockResolvedValue([]);
  });

  it('step 1: names and creates the workspace', async () => {
    vi.mocked(client.onboardingStatus).mockResolvedValue({ has_workspace: false });
    vi.mocked(client.createWorkspace).mockResolvedValue({
      workspace: 'WS-9',
      workspace_name: 'Asha Traders',
    });
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText('Name your workspace'), 'Asha Traders');
    await user.click(screen.getByRole('button', { name: 'Create workspace' }));
    await waitFor(() => {
      expect(client.createWorkspace).toHaveBeenCalledWith('Asha Traders');
    });
  });

  it('step 2: prompts to connect the first number with a skip', async () => {
    vi.mocked(client.onboardingStatus).mockResolvedValue(status({ connected_numbers: 0 }));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Connect a number' }));
    expect(await screen.findByText('NUMBERS PROBE')).toBeInTheDocument();
  });

  it('step 2 skip advances to invites', async () => {
    vi.mocked(client.onboardingStatus).mockResolvedValue(status({ connected_numbers: 0 }));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Skip for now' }));
    expect(await screen.findByLabelText('Invite email')).toBeInTheDocument();
  });

  it('step 3: invites a teammate and finishes to the inbox', async () => {
    vi.mocked(client.onboardingStatus).mockResolvedValue(status({ connected_numbers: 1 }));
    vi.mocked(client.inviteMember).mockResolvedValue({
      name: 'INV-1',
      email: 'riya@x.test',
      role: 'Agent',
      status: 'pending',
      expires_at: null,
      invite_url: 'http://x/invite/tok',
    });
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText('Invite email'), 'riya@x.test');
    await user.click(screen.getByRole('button', { name: 'Invite' }));
    await waitFor(() => {
      expect(client.inviteMember).toHaveBeenCalledWith('riya@x.test', 'Agent');
    });
    await user.click(screen.getByRole('button', { name: 'Go to your inbox' }));
    expect(await screen.findByText('INBOX PROBE')).toBeInTheDocument();
  });
});
