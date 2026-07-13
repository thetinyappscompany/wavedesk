import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import StarterTemplatesCard from './StarterTemplatesCard';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listVerticals: vi.fn(),
    applyVertical: vi.fn(),
  },
}));

const VERTICALS = [
  {
    key: 'd2c',
    label: 'D2C / E-commerce',
    description: 'Online store support.',
    labels: ['order', 'refund'],
    canned: ['thanks', 'track'],
    automation: ['Tag refund requests'],
  },
  {
    key: 'support',
    label: 'Customer Support',
    description: 'Helpdesk.',
    labels: ['bug'],
    canned: ['greet'],
    automation: ['Tag bug reports'],
  },
];

function renderCard(canManage = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <StarterTemplatesCard canManage={canManage} />
    </QueryClientProvider>,
  );
}

describe('StarterTemplatesCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listVerticals).mockResolvedValue(VERTICALS);
  });

  it('previews a selected vertical and applies it', async () => {
    vi.mocked(client.applyVertical).mockResolvedValue({
      vertical: 'd2c',
      added: { labels: 2, canned: 2, automation: 1 },
    });
    renderCard();
    await userEvent.click(await screen.findByRole('button', { name: 'D2C / E-commerce' }));
    expect(screen.getByTestId('vertical-preview')).toHaveTextContent('order, refund');
    await userEvent.click(screen.getByRole('button', { name: 'Apply pack' }));
    await waitFor(() => expect(client.applyVertical).toHaveBeenCalledWith('d2c'));
    expect(await screen.findByTestId('apply-result')).toHaveTextContent(
      'Added 2 labels, 2 canned replies, 1 rules.',
    );
  });

  it('disables apply until a vertical is chosen', async () => {
    renderCard();
    await screen.findByRole('button', { name: 'Customer Support' });
    expect(screen.getByRole('button', { name: 'Apply pack' })).toBeDisabled();
  });

  it('hides controls without manage rights', async () => {
    renderCard(false);
    await screen.findByText('Starter Templates');
    expect(screen.queryByRole('button', { name: 'Apply pack' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('vertical-options')).not.toBeInTheDocument();
  });
});
