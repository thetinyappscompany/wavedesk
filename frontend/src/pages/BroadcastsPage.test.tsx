import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdBroadcast } from '@wavedesk/api-client';
import BroadcastsPage from './BroadcastsPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listBroadcasts: vi.fn(),
    createBroadcast: vi.fn(),
    startBroadcast: vi.fn(),
    pauseBroadcast: vi.fn(),
    resumeBroadcast: vi.fn(),
    cancelBroadcast: vi.fn(),
    retryBroadcast: vi.fn(),
    broadcastReport: vi.fn(),
    deleteBroadcast: vi.fn(),
    listNumbers: vi.fn(),
  },
}));
vi.mock('@/lib/realtime', () => ({ useWorkspaceEvents: vi.fn() }));

function broadcast(overrides: Partial<WdBroadcast> = {}): WdBroadcast {
  return {
    name: 'BC-1',
    broadcast_name: 'Diwali offer',
    number: 'WNUM-1',
    message_template: 'Hi {{name}}',
    status: 'draft',
    audience_type: 'all_contacts',
    audience_ref: null,
    total_recipients: 3,
    sent_count: 0,
    failed_count: 0,
    daily_cap: 0,
    min_interval_sec: 3,
    max_interval_sec: 8,
    failure_pause_pct: 10,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <BroadcastsPage />
    </QueryClientProvider>,
  );
}

describe('BroadcastsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listBroadcasts).mockResolvedValue([broadcast()]);
    vi.mocked(client.listNumbers).mockResolvedValue([
      { name: 'WNUM-1', phone: '+919000000000' } as never,
    ]);
  });

  it('lists broadcasts with status and progress', async () => {
    renderPage();
    const row = await screen.findByTestId('broadcast-row');
    expect(row).toHaveTextContent('Diwali offer');
    expect(row).toHaveTextContent('draft');
    expect(row).toHaveTextContent('0/3 sent');
  });

  it('creates a CSV broadcast', async () => {
    vi.mocked(client.createBroadcast).mockResolvedValue(broadcast());
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'New broadcast' }));
    await user.type(screen.getByLabelText('Broadcast name'), 'Sale');
    await user.selectOptions(screen.getByLabelText('Sending number'), 'WNUM-1');
    await user.selectOptions(screen.getByLabelText('Audience'), 'csv');
    await user.type(screen.getByLabelText('CSV recipients'), '919900000001,Asha\n919900000002,Riya');
    await user.type(screen.getByLabelText('Message template'), 'Namaste friends');
    await user.click(screen.getByRole('button', { name: 'Create broadcast' }));

    await waitFor(() => {
      expect(client.createBroadcast).toHaveBeenCalledWith({
        broadcastName: 'Sale',
        number: 'WNUM-1',
        messageTemplate: 'Namaste friends',
        audienceType: 'csv',
        audience: [
          { phone: '919900000001', name: 'Asha' },
          { phone: '919900000002', name: 'Riya' },
        ],
        dailyCap: 0,
      });
    });
  });

  it('starts a draft broadcast', async () => {
    vi.mocked(client.startBroadcast).mockResolvedValue(broadcast({ status: 'sending' }));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByLabelText('Start Diwali offer'));
    expect(client.startBroadcast).toHaveBeenCalledWith('BC-1');
  });

  it('shows the delivery report on demand', async () => {
    vi.mocked(client.broadcastReport).mockResolvedValue({
      broadcast: broadcast({ status: 'completed', sent_count: 3 }),
      counts: { pending: 0, sent: 3, failed: 0, opted_out: 0, skipped: 0 },
      recipients: [
        {
          name: 'BCR-1',
          phone: '919900000001',
          recipient_name: 'Asha',
          status: 'sent',
          error: null,
          message_status: 'sent',
        },
      ],
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Report' }));
    expect(await screen.findByTestId('broadcast-report')).toHaveTextContent('sent: 3');
    expect(screen.getByTestId('recipient-row')).toHaveTextContent('Asha');
  });
});
