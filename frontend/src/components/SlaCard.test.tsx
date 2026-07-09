import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdSlaPolicy } from '@wavedesk/api-client';
import SlaCard from './SlaCard';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listSlaPolicies: vi.fn(),
    createSlaPolicy: vi.fn(),
    updateSlaPolicy: vi.fn(),
    deleteSlaPolicy: vi.fn(),
  },
}));

function policy(overrides: Partial<WdSlaPolicy> = {}): WdSlaPolicy {
  return {
    name: 'SLA-1',
    policy_name: 'Gold',
    enabled: true,
    first_response_mins: 10,
    resolution_mins: 60,
    escalation_chain: [{ after_mins: 0, target: 'agent' }],
    ...overrides,
  };
}

function renderCard(canManage = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SlaCard canManage={canManage} />
    </QueryClientProvider>,
  );
}

describe('SlaCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listSlaPolicies).mockResolvedValue([policy()]);
  });

  it('lists policies with their targets', async () => {
    renderCard();
    const row = await screen.findByTestId('sla-policy-row');
    expect(row).toHaveTextContent('Gold');
    expect(row).toHaveTextContent('FR 10m');
    expect(row).toHaveTextContent('Res 60m');
    expect(row).toHaveTextContent('1 escalation');
  });

  it('creates a policy with an escalation step', async () => {
    vi.mocked(client.createSlaPolicy).mockResolvedValue(policy());
    const user = userEvent.setup();
    renderCard();
    await user.type(await screen.findByLabelText('SLA policy name'), 'Gold');
    const fr = screen.getByLabelText('First response minutes');
    await user.clear(fr);
    await user.type(fr, '5');
    await user.click(screen.getByLabelText('Add escalation step'));
    await user.selectOptions(screen.getByLabelText('Step 1 target'), 'owner');
    await user.click(screen.getByRole('button', { name: 'Add policy' }));

    await waitFor(() => {
      expect(client.createSlaPolicy).toHaveBeenCalledWith({
        policyName: 'Gold',
        firstResponseMins: 5,
        resolutionMins: 0,
        escalationChain: [{ after_mins: 0, target: 'owner' }],
      });
    });
  });

  it('toggles and deletes a policy', async () => {
    vi.mocked(client.updateSlaPolicy).mockResolvedValue(policy({ enabled: false }));
    vi.mocked(client.deleteSlaPolicy).mockResolvedValue({ deleted: 'SLA-1' });
    const user = userEvent.setup();
    renderCard();
    await user.click(await screen.findByLabelText('Enable Gold'));
    expect(client.updateSlaPolicy).toHaveBeenCalledWith('SLA-1', { enabled: false });
    await user.click(screen.getByLabelText('Delete Gold'));
    expect(client.deleteSlaPolicy).toHaveBeenCalledWith('SLA-1');
  });

  it('is read-only for agents', async () => {
    renderCard(false);
    await screen.findByTestId('sla-policy-row');
    expect(screen.queryByRole('button', { name: 'Add policy' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Enable Gold')).not.toBeInTheDocument();
  });
});
