import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdDashboard } from '@wavedesk/api-client';
import DashboardPage from './DashboardPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    workspaceDashboard: vi.fn(),
    dashboardCsvUrl: vi.fn((days: number) => `/api/method/export?days=${String(days)}`),
  },
}));
vi.mock('@/lib/realtime', () => ({
  useWorkspaceEvents: vi.fn(),
}));

function dashboard(overrides: Partial<WdDashboard> = {}): WdDashboard {
  return {
    days: 14,
    live: { open: 5, unassigned: 2, needs_reply: 1 },
    conversations_trend: [
      { date: '2026-07-08', count: 4 },
      { date: '2026-07-09', count: 9 },
    ],
    conversations_total: 13,
    first_response_avg_mins: 12.5,
    first_response_p90_mins: 40,
    resolution_avg_mins: 120,
    resolution_p90_mins: 300,
    messages_per_agent: [
      { agent: 'riya@x.test', agent_name: 'Riya', messages: 22 },
      { agent: 'amit@x.test', agent_name: 'Amit', messages: 9 },
    ],
    per_number_volume: [{ number: 'WNUM-1', display_name: 'Sales Line', messages: 31 }],
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <DashboardPage />
    </QueryClientProvider>,
  );
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.workspaceDashboard).mockResolvedValue(dashboard());
  });

  it('renders live tiles, chart, timing, per-agent and per-number', async () => {
    renderPage();
    expect(await screen.findAllByTestId('live-tile')).toHaveLength(3);
    expect(screen.getByText('5')).toBeInTheDocument(); // open
    expect(screen.getAllByTestId('conv-bar')).toHaveLength(2);
    expect(screen.getByText('12.5m')).toBeInTheDocument();
    expect(screen.getByText('300m')).toBeInTheDocument();
    expect(screen.getAllByTestId('agent-row')).toHaveLength(2);
    expect(screen.getByText('Riya')).toBeInTheDocument();
    expect(screen.getByText('Sales Line')).toBeInTheDocument();
  });

  it('changing the date range refetches for the new window', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findAllByTestId('live-tile');
    await user.click(screen.getByRole('tab', { name: '30d' }));
    await waitFor(() => {
      expect(client.workspaceDashboard).toHaveBeenCalledWith(30);
    });
  });

  it('the CSV link points at the export endpoint for the active range', async () => {
    renderPage();
    const link = await screen.findByTestId('csv-link');
    expect(link).toHaveAttribute('href', '/api/method/export?days=14');
  });

  it('handles empty timing and volume', async () => {
    vi.mocked(client.workspaceDashboard).mockResolvedValue(
      dashboard({
        first_response_avg_mins: null,
        resolution_avg_mins: null,
        first_response_p90_mins: null,
        resolution_p90_mins: null,
        messages_per_agent: [],
        per_number_volume: [],
      }),
    );
    renderPage();
    expect(await screen.findByText('No outbound messages yet.')).toBeInTheDocument();
    expect(screen.getByText('No traffic yet.')).toBeInTheDocument();
  });
});
