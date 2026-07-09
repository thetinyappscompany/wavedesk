import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdAlert } from '@wavedesk/api-client';
import AlertsPage from './AlertsPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: { listAlerts: vi.fn(), markAlertsSeen: vi.fn() },
}));
vi.mock('@/lib/realtime', () => ({
  useWorkspaceEvents: vi.fn(),
}));

function alert(overrides: Partial<WdAlert> = {}): WdAlert {
  return {
    name: 'ALERT-1',
    rule_name: 'Competitor watch',
    kind: 'keyword',
    group: 'GRP-1',
    group_subject: 'Surat Traders',
    chat: 'CHAT-1',
    message: 'MSG-1',
    summary: "Competitor watch: 'scam' in Surat Traders — bhai yeh scam hai",
    seen: false,
    creation: '2026-07-09 03:00:00',
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AlertsPage />
    </QueryClientProvider>,
  );
}

describe('AlertsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists alerts with unseen count and marks all seen', async () => {
    vi.mocked(client.listAlerts).mockResolvedValue({
      alerts: [
        alert(),
        alert({
          name: 'ALERT-2',
          kind: 'member_change',
          seen: true,
          summary: 'Door watch: 1 member left Surat Traders',
        }),
      ],
      unseen: 1,
    });
    vi.mocked(client.markAlertsSeen).mockResolvedValue({ unseen: 0 });
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findAllByTestId('alert-row')).toHaveLength(2);
    expect(screen.getByTestId('unseen-count')).toHaveTextContent('1 new');
    expect(screen.getByText(/scam' in Surat Traders/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Mark all seen' }));
    await waitFor(() => {
      expect(client.markAlertsSeen).toHaveBeenCalled();
    });
  });

  it('shows the empty state', async () => {
    vi.mocked(client.listAlerts).mockResolvedValue({ alerts: [], unseen: 0 });
    renderPage();
    expect(await screen.findByText(/Nothing caught yet/)).toBeInTheDocument();
  });
});
