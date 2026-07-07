import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdChat } from '@wavedesk/api-client';
import InboxPage from './InboxPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: { listChats: vi.fn() },
}));

function chat(overrides: Partial<WdChat>): WdChat {
  return {
    name: 'CHAT-1',
    chat_type: 'dm',
    status: 'open',
    number: null,
    assigned_agent: null,
    last_message_at: '2026-07-07 12:00:00',
    unread_count: 0,
    wa_chat_id: '9199@s.whatsapp.net',
    contact_name: 'Asha Traders',
    contact_phone: '+919111100001',
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <InboxPage />
    </QueryClientProvider>,
  );
}

describe('InboxPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders chats with unread badges', async () => {
    vi.mocked(client.listChats).mockResolvedValue({
      chats: [
        chat({ name: 'CHAT-1', contact_name: 'Asha Traders', unread_count: 3 }),
        chat({ name: 'CHAT-2', contact_name: 'Bharat Metals', unread_count: 0 }),
      ],
      total: 2,
    });
    renderPage();
    expect(await screen.findByText('Asha Traders')).toBeInTheDocument();
    expect(screen.getByText('Bharat Metals')).toBeInTheDocument();
    expect(screen.getAllByTestId('unread-badge')).toHaveLength(1);
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('passes the status filter to the API', async () => {
    vi.mocked(client.listChats).mockResolvedValue({ chats: [], total: 0 });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/No conversations yet/);
    await user.click(screen.getByRole('tab', { name: 'Open' }));
    await waitFor(() => {
      expect(client.listChats).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'open' }),
      );
    });
  });

  it('debounces search into the API call', async () => {
    vi.mocked(client.listChats).mockResolvedValue({ chats: [], total: 0 });
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByPlaceholderText(/Search name or phone/), 'Asha');
    await waitFor(() => {
      expect(client.listChats).toHaveBeenCalledWith(
        expect.objectContaining({ search: 'Asha' }),
      );
    });
  });

  it('selecting a chat shows the placeholder conversation pane', async () => {
    vi.mocked(client.listChats).mockResolvedValue({
      chats: [chat({ name: 'CHAT-42' })],
      total: 1,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId('chat-row'));
    expect(screen.getByText('CHAT-42')).toBeInTheDocument();
    expect(screen.getByText(/lands in the next/)).toBeInTheDocument();
  });
});
