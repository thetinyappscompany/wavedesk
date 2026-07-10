import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AiFlaggingCard from './AiFlaggingCard';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listFlagRules: vi.fn(),
    createFlagRule: vi.fn(),
    updateFlagRule: vi.fn(),
    deleteFlagRule: vi.fn(),
  },
}));

const RULE = {
  name: 'FLAGRULE-1',
  flag_key: 'purchase_intent',
  label: 'Purchase intent',
  prompt: 'Customer wants to buy',
  action: 'flag' as const,
  priority: 'medium',
  enabled: true,
};

function renderCard(canManage = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <AiFlaggingCard canManage={canManage} />
    </QueryClientProvider>,
  );
}

describe('AiFlaggingCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listFlagRules).mockResolvedValue([RULE]);
  });

  it('lists rules and creates a new one', async () => {
    vi.mocked(client.createFlagRule).mockResolvedValue({ name: 'FLAGRULE-2', flag_key: 'angry' });
    renderCard();
    expect(await screen.findByText('purchase_intent')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Flag key'), 'angry');
    await userEvent.type(screen.getByLabelText('Flag criteria'), 'Customer is angry');
    await userEvent.click(screen.getByRole('button', { name: 'Add flag rule' }));
    await waitFor(() =>
      expect(client.createFlagRule).toHaveBeenCalledWith(
        'angry',
        'Customer is angry',
        expect.objectContaining({ action: 'flag' }),
      ),
    );
  });

  it('toggles a rule enabled state', async () => {
    vi.mocked(client.updateFlagRule).mockResolvedValue({ name: RULE.name, enabled: false });
    renderCard();
    await userEvent.click(await screen.findByLabelText('Toggle purchase_intent'));
    await waitFor(() =>
      expect(client.updateFlagRule).toHaveBeenCalledWith('FLAGRULE-1', { enabled: false }),
    );
  });

  it('deletes a rule', async () => {
    vi.mocked(client.deleteFlagRule).mockResolvedValue({ deleted: 'FLAGRULE-1' });
    renderCard();
    await userEvent.click(await screen.findByLabelText('Delete purchase_intent'));
    await waitFor(() => expect(client.deleteFlagRule).toHaveBeenCalledWith('FLAGRULE-1'));
  });

  it('hides mutations without manage rights', async () => {
    renderCard(false);
    await screen.findByText('purchase_intent');
    expect(screen.queryByRole('button', { name: 'Add flag rule' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Delete purchase_intent')).not.toBeInTheDocument();
  });
});
