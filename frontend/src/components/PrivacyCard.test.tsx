import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import PrivacyCard from './PrivacyCard';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    getRetention: vi.fn(),
    setRetention: vi.fn(),
    requestDataExport: vi.fn(),
    listDataExports: vi.fn(),
  },
}));

function renderCard(canManage = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <PrivacyCard canManage={canManage} />
    </QueryClientProvider>,
  );
}

describe('PrivacyCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.getRetention).mockResolvedValue(30);
    vi.mocked(client.listDataExports).mockResolvedValue([
      {
        name: 'DEXP-1',
        status: 'ready',
        file_url: '/private/files/export.json',
        record_counts: { contacts: 5 },
        requested_by: 'owner@x.test',
        creation: '2026-07-11 12:00:00',
      },
    ]);
  });

  it('shows the retention value and a ready export download link', async () => {
    renderCard();
    await waitFor(() => expect(screen.getByLabelText('Retention days')).toHaveValue(30));
    const link = screen.getByRole('link', { name: /download/i });
    expect(link).toHaveAttribute('href', '/private/files/export.json');
  });

  it('saves a changed retention window', async () => {
    vi.mocked(client.setRetention).mockResolvedValue({ retention_days: 90 });
    renderCard();
    const input = await screen.findByLabelText('Retention days');
    await waitFor(() => expect(input).toHaveValue(30)); // wait for load before editing
    await userEvent.clear(input);
    await userEvent.type(input, '90');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(client.setRetention).toHaveBeenCalledWith(90));
  });

  it('requests a data export', async () => {
    vi.mocked(client.requestDataExport).mockResolvedValue({ export: 'DEXP-2' });
    renderCard();
    await screen.findByLabelText('Retention days');
    await userEvent.click(screen.getByRole('button', { name: 'Request data export' }));
    await waitFor(() => expect(client.requestDataExport).toHaveBeenCalled());
  });

  it('hides mutations without manage rights', async () => {
    renderCard(false);
    await screen.findByLabelText('Retention days');
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Request data export' })).not.toBeInTheDocument();
  });
});
