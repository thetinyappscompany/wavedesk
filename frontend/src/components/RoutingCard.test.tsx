import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdTeam, WdWorkspaceSettings } from '@wavedesk/api-client';
import RoutingCard from './RoutingCard';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listTeams: vi.fn(),
    createTeam: vi.fn(),
    updateTeam: vi.fn(),
    deleteTeam: vi.fn(),
    updateWorkspaceSettings: vi.fn(),
  },
}));

function team(overrides: Partial<WdTeam> = {}): WdTeam {
  return {
    name: 'TEAM-1',
    team_name: 'Sales',
    routing: 'manual',
    capacity_per_agent: 0,
    members: [],
    ...overrides,
  };
}

const settings = {
  default_routing_team: null,
} as unknown as WdWorkspaceSettings;

function renderCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <RoutingCard canManage settings={settings} />
    </QueryClientProvider>,
  );
}

describe('RoutingCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listTeams).mockResolvedValue([team()]);
  });

  it('changes a team routing mode', async () => {
    vi.mocked(client.updateTeam).mockResolvedValue(team({ routing: 'round_robin' }));
    const user = userEvent.setup();
    renderCard();
    await user.selectOptions(await screen.findByLabelText('Routing for Sales'), 'round_robin');
    expect(client.updateTeam).toHaveBeenCalledWith('TEAM-1', { routing: 'round_robin' });
  });

  it('saves capacity on blur', async () => {
    vi.mocked(client.updateTeam).mockResolvedValue(team({ capacity_per_agent: 5 }));
    const user = userEvent.setup();
    renderCard();
    const cap = await screen.findByLabelText('Capacity for Sales');
    await user.clear(cap);
    await user.type(cap, '5');
    await user.tab();
    await waitFor(() => {
      expect(client.updateTeam).toHaveBeenCalledWith('TEAM-1', { capacityPerAgent: 5 });
    });
  });

  it('creates a team as round-robin', async () => {
    vi.mocked(client.createTeam).mockResolvedValue(team({ name: 'TEAM-2', team_name: 'Support' }));
    const user = userEvent.setup();
    renderCard();
    await user.type(await screen.findByLabelText('New team name'), 'Support');
    await user.click(screen.getByRole('button', { name: 'Add team' }));
    await waitFor(() => {
      expect(client.createTeam).toHaveBeenCalledWith('Support', { routing: 'round_robin' });
    });
  });

  it('sets the default routing team', async () => {
    vi.mocked(client.updateWorkspaceSettings).mockResolvedValue(settings);
    const user = userEvent.setup();
    renderCard();
    await screen.findByLabelText('Routing for Sales'); // teams loaded → option present
    await user.selectOptions(screen.getByLabelText('Default routing team'), 'TEAM-1');
    expect(client.updateWorkspaceSettings).toHaveBeenCalledWith({ default_routing_team: 'TEAM-1' });
  });

  it('is read-only for agents', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <RoutingCard canManage={false} settings={settings} />
      </QueryClientProvider>,
    );
    expect(await screen.findByLabelText('Routing for Sales')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Add team' })).not.toBeInTheDocument();
  });
});
