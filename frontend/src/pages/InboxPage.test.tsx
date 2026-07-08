import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdChat } from '@wavedesk/api-client';
import InboxPage from './InboxPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listChats: vi.fn(),
    listMessages: vi.fn(),
    markChatRead: vi.fn(),
    listMembers: vi.fn(),
    assignChat: vi.fn(),
    setChatStatus: vi.fn(),
    presencePing: vi.fn(),
    getLoggedUser: vi.fn(),
  },
}));
vi.mock('@/lib/realtime', () => ({
  useWorkspaceEvents: vi.fn(),
  useChatPresence: vi.fn(() => []),
}));

function chat(overrides: Partial<WdChat>): WdChat {
  return {
    name: 'CHAT-1',
    chat_type: 'dm',
    status: 'open',
    number: null,
    assigned_agent: null,
    assigned_team: null,
    snoozed_until: null,
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
    vi.mocked(client.listMembers).mockResolvedValue([]);
    vi.mocked(client.presencePing).mockResolvedValue({ ok: true });
    vi.mocked(client.getLoggedUser).mockResolvedValue('me@x.test');
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

  it('Mine and Unassigned views pass the assignee filter', async () => {
    vi.mocked(client.listChats).mockResolvedValue({ chats: [], total: 0 });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/No conversations yet/);
    await user.click(screen.getByRole('tab', { name: 'Mine' }));
    await waitFor(() => {
      expect(client.listChats).toHaveBeenCalledWith(
        expect.objectContaining({ assignee: 'me' }),
      );
    });
    await user.click(screen.getByRole('tab', { name: 'Unassigned' }));
    await waitFor(() => {
      expect(client.listChats).toHaveBeenCalledWith(
        expect.objectContaining({ assignee: 'unassigned' }),
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

  it('selecting a chat opens the conversation pane', async () => {
    vi.mocked(client.listChats).mockResolvedValue({
      chats: [chat({ name: 'CHAT-42', contact_name: 'Asha Traders' })],
      total: 1,
    });
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [],
      has_more: false,
      next_before: null,
    });
    vi.mocked(client.markChatRead).mockResolvedValue({ chat: 'CHAT-42', unread_count: 0 });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId('chat-row'));
    expect(await screen.findByRole('heading', { name: 'Asha Traders' })).toBeInTheDocument();
    expect(client.listMessages).toHaveBeenCalledWith('CHAT-42', undefined);
    expect(client.markChatRead).toHaveBeenCalledWith('CHAT-42');
  });
});
