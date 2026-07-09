import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdTicket } from '@wavedesk/api-client';
import TicketsPage from './TicketsPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: { listTickets: vi.fn(), updateTicket: vi.fn() },
}));
vi.mock('@/lib/realtime', () => ({
  useWorkspaceEvents: vi.fn(),
}));

function ticket(overrides: Partial<WdTicket>): WdTicket {
  return {
    name: 'TKT-1',
    title: 'Order missing',
    status: 'open',
    priority: 'high',
    chat: 'CHAT-1',
    assigned_agent: null,
    team: null,
    creation: '2026-07-09 12:00:00',
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TicketsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('TicketsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.updateTicket).mockResolvedValue(ticket({ status: 'resolved' }));
  });

  it('lists tickets with priority badges', async () => {
    vi.mocked(client.listTickets).mockResolvedValue({
      tickets: [
        ticket({ name: 'TKT-1', title: 'Order missing', priority: 'urgent' }),
        ticket({ name: 'TKT-2', title: 'Wrong item', priority: 'low' }),
      ],
      total: 2,
    });
    renderPage();
    expect(await screen.findAllByTestId('ticket-row')).toHaveLength(2);
    expect(screen.getByText('Order missing')).toBeInTheDocument();
    expect(screen.getAllByTestId('priority-badge')[0]).toHaveTextContent('urgent');
  });

  it('status filter passes to the API', async () => {
    vi.mocked(client.listTickets).mockResolvedValue({ tickets: [], total: 0 });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/No tickets/);
    await user.click(screen.getByRole('tab', { name: 'In progress' }));
    await waitFor(() => {
      expect(client.listTickets).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'in_progress' }),
      );
    });
  });

  it('assignee filter passes to the API', async () => {
    vi.mocked(client.listTickets).mockResolvedValue({ tickets: [], total: 0 });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/No tickets/);
    await user.selectOptions(screen.getByLabelText('Assignee filter'), 'me');
    await waitFor(() => {
      expect(client.listTickets).toHaveBeenCalledWith(
        expect.objectContaining({ assignee: 'me' }),
      );
    });
  });

  it('changing a ticket status calls the API', async () => {
    vi.mocked(client.listTickets).mockResolvedValue({
      tickets: [ticket({ name: 'TKT-1', title: 'Order missing' })],
      total: 1,
    });
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(
      await screen.findByLabelText('Status of Order missing'),
      'resolved',
    );
    expect(client.updateTicket).toHaveBeenCalledWith('TKT-1', { status: 'resolved' });
  });
});
