import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdSegment } from '@wavedesk/api-client';
import SegmentsPage from './SegmentsPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listSegments: vi.fn(),
    createSegment: vi.fn(),
    updateSegment: vi.fn(),
    deleteSegment: vi.fn(),
    previewSegment: vi.fn(),
  },
}));

function segment(overrides: Partial<WdSegment> = {}): WdSegment {
  return {
    name: 'SEG-1',
    segment_name: 'Mumbai VIPs',
    description: null,
    match_type: 'all',
    filters: [{ type: 'has_tag', value: 'vip' }],
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SegmentsPage />
    </QueryClientProvider>,
  );
}

describe('SegmentsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listSegments).mockResolvedValue([segment()]);
    vi.mocked(client.previewSegment).mockResolvedValue({ count: 42, sample: [] });
  });

  it('lists segments with a live preview count', async () => {
    renderPage();
    const row = await screen.findByTestId('segment-row');
    expect(row).toHaveTextContent('Mumbai VIPs');
    expect(row).toHaveTextContent('match all');
    expect(await screen.findByText('42 contacts')).toBeInTheDocument();
  });

  it('builds a segment with filters', async () => {
    vi.mocked(client.createSegment).mockResolvedValue(segment());
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'New segment' }));
    await user.type(screen.getByLabelText('Segment name'), 'Delhi promo');
    await user.selectOptions(screen.getByLabelText('Filter 1 type'), 'attribute');
    await user.type(screen.getByLabelText('Filter 1 key'), 'city');
    await user.type(screen.getByLabelText('Filter 1 value'), 'Delhi');
    await user.click(screen.getByRole('button', { name: 'Save segment' }));

    await waitFor(() => {
      expect(client.createSegment).toHaveBeenCalledWith({
        segmentName: 'Delhi promo',
        matchType: 'all',
        filters: [{ type: 'attribute', key: 'city', value: 'Delhi' }],
      });
    });
  });

  it('deletes a segment', async () => {
    vi.mocked(client.deleteSegment).mockResolvedValue({ deleted: 'SEG-1' });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByLabelText('Delete Mumbai VIPs'));
    expect(client.deleteSegment).toHaveBeenCalledWith('SEG-1');
  });
});
