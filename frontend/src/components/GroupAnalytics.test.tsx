import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdGroupAnalytics } from '@wavedesk/api-client';
import GroupAnalytics from './GroupAnalytics';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: { groupAnalytics: vi.fn() },
}));

function analytics(overrides: Partial<WdGroupAnalytics> = {}): WdGroupAnalytics {
  return {
    days: 14,
    total_messages: 42,
    inbound_messages: 30,
    outbound_messages: 12,
    volume_trend: [
      { date: '2026-07-08', count: 3 },
      { date: '2026-07-09', count: 7 },
    ],
    active_member_pct: 66.7,
    top_contributors: [
      { display: 'Riya', messages: 10 },
      { display: '919222200002', messages: 4 },
    ],
    best_posting_hours: [
      { hour: 9, messages: 12 },
      { hour: 20, messages: 8 },
    ],
    avg_response_mins: 30,
    answered_queries: 5,
    unanswered_now: 1,
    ...overrides,
  };
}

function renderChart() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <GroupAnalytics groupName="GRP-1" />
    </QueryClientProvider>,
  );
}

describe('GroupAnalytics', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the volume chart, stats, contributors, and hours', async () => {
    vi.mocked(client.groupAnalytics).mockResolvedValue(analytics());
    renderChart();
    expect(await screen.findByTestId('group-analytics')).toBeInTheDocument();
    expect(screen.getAllByTestId('volume-bar')).toHaveLength(2);
    expect(screen.getByText('66.7%')).toBeInTheDocument();
    expect(screen.getByText('30m')).toBeInTheDocument();
    const contributors = screen.getAllByTestId('contributor-row');
    expect(contributors).toHaveLength(2);
    expect(contributors[0]).toHaveTextContent('Riya');
    expect(screen.getByText('9am, 8pm')).toBeInTheDocument();
  });

  it('handles a group with no response data', async () => {
    vi.mocked(client.groupAnalytics).mockResolvedValue(
      analytics({ avg_response_mins: null, top_contributors: [], best_posting_hours: [] }),
    );
    renderChart();
    expect(await screen.findByText('—')).toBeInTheDocument();
    expect(screen.queryByTestId('contributor-row')).not.toBeInTheDocument();
  });
});
