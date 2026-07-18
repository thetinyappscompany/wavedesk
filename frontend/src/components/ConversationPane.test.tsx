import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdChat, WdMessage } from '@wavedesk/api-client';
import ConversationPane from './ConversationPane';
import { client } from '@/lib/client';
import { useChatPresence } from '@/lib/realtime';

vi.mock('@/lib/client', () => ({
  client: {
    listMessages: vi.fn(),
    markChatRead: vi.fn(),
    sendMessage: vi.fn(),
    retryMessage: vi.fn(),
    listMembers: vi.fn(),
    assignChat: vi.fn(),
    setChatStatus: vi.fn(),
    presencePing: vi.fn(),
    getLoggedUser: vi.fn(),
    searchCanned: vi.fn(),
    listLabels: vi.fn(),
    setChatLabels: vi.fn(),
    createTicket: vi.fn(),
    getMediaUrl: vi.fn(),
    addNote: vi.fn(),
    setChatPriority: vi.fn(),
    listMacros: vi.fn(),
    runMacro: vi.fn(),
  },
}));
vi.mock('@/lib/realtime', () => ({
  useChatPresence: vi.fn(() => []),
}));

function message(overrides: Partial<WdMessage>): WdMessage {
  return {
    name: `MSG-${Math.random().toString(36).slice(2, 8)}`,
    direction: 'in',
    message_type: 'text',
    body: 'hello',
    status: null,
    sender_agent: null,
    sender_contact: null,
    sender_jid: null,
    sender_name: null,
    sender_display: null,
    wa_message_id: null,
    quoted_message: null,
    quoted_body: null,
    flagged: false,
    flag_reason: null,
    has_media: false,
    media_mimetype: null,
    media_filename: null,
    media_size: null,
    media_duration: null,
    is_voice: false,
    transcript: null,
    is_private: false,
    creation: '2026-07-07 12:00:00',
    ...overrides,
  };
}

function chatRow(overrides: Partial<WdChat> = {}): WdChat {
  return {
    name: 'CHAT-1',
    chat_type: 'dm',
    status: 'open',
    priority: null,
    number: null,
    contact: null,
    assigned_agent: null,
    assigned_team: null,
    snoozed_until: null,
    last_message_at: '2026-07-08 12:00:00',
    unread_count: 0,
    wa_chat_id: '9199@s.whatsapp.net',
    contact_name: 'Asha Traders',
    contact_phone: '+919111100001',
    group: null,
    group_subject: null,
    needs_reply: false,
    pending_query_since: null,
    labels: [],
    ...overrides,
  };
}

function renderPane(chat: WdChat = chatRow()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConversationPane chatName="CHAT-1" title="Asha Traders" chat={chat} />
    </QueryClientProvider>,
  );
}

describe('ConversationPane', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.markChatRead).mockResolvedValue({ chat: 'CHAT-1', unread_count: 0 });
    vi.mocked(client.listMembers).mockResolvedValue([
      { user: 'riya@x.test', role: 'Agent', full_name: 'Riya' },
    ]);
    vi.mocked(client.presencePing).mockResolvedValue({ ok: true });
    vi.mocked(client.getLoggedUser).mockResolvedValue('me@x.test');
    vi.mocked(client.searchCanned).mockResolvedValue([]);
    vi.mocked(client.listLabels).mockResolvedValue([]);
    vi.mocked(client.createTicket).mockResolvedValue({
      name: 'TKT-1',
      title: 'namaste',
      status: 'open',
      priority: 'medium',
      chat: 'CHAT-1',
      assigned_agent: null,
      team: null,
      creation: '2026-07-09 12:00:00',
    });
    vi.mocked(useChatPresence).mockReturnValue([]);
  });

  it('renders in/out bubbles with status ticks and marks the chat read', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [
        message({ name: 'M1', body: 'namaste', direction: 'in' }),
        message({ name: 'M2', body: 'hello ji', direction: 'out', status: 'read' }),
      ],
      has_more: false,
      next_before: null,
    });
    renderPane();

    expect(await screen.findByText('namaste')).toBeInTheDocument();
    const bubbles = screen.getAllByTestId('message-bubble');
    expect(bubbles[0]).toHaveAttribute('data-direction', 'in');
    expect(bubbles[1]).toHaveAttribute('data-direction', 'out');
    expect(screen.getByLabelText('read')).toBeInTheDocument();
    expect(client.markChatRead).toHaveBeenCalledWith('CHAT-1');
  });

  it('group chats show the sender on inbound bubbles', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [
        message({ name: 'M1', body: 'price kya hai?', sender_display: 'Riya S' }),
        message({ name: 'M2', body: 'checking ji', direction: 'out', sender_display: null }),
      ],
      has_more: false,
      next_before: null,
    });
    renderPane(chatRow({ chat_type: 'group' }));
    expect(await screen.findByTestId('sender-name')).toHaveTextContent('Riya S');
    // exactly one: the outbound bubble never shows a sender
    expect(screen.getAllByTestId('sender-name')).toHaveLength(1);
  });

  it('note mode saves a private note instead of sending', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [],
      has_more: false,
      next_before: null,
    });
    vi.mocked(client.addNote).mockResolvedValue(
      message({ name: 'N1', body: 'VIP hai', is_private: true, message_type: 'note' }),
    );
    const user = userEvent.setup();
    renderPane();

    await user.click(await screen.findByTestId('note-mode-toggle'));
    await user.type(screen.getByLabelText('Message'), 'VIP hai');
    await user.click(screen.getByLabelText('Save note'));
    await waitFor(() => {
      expect(client.addNote).toHaveBeenCalledWith('CHAT-1', 'VIP hai');
    });
    expect(client.sendMessage).not.toHaveBeenCalled();
  });

  it('private notes render with the amber badge', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [
        message({
          name: 'N1',
          body: 'internal only',
          direction: 'out',
          message_type: 'note',
          is_private: true,
          sender_display: 'Riya',
        }),
      ],
      has_more: false,
      next_before: null,
    });
    renderPane();
    expect(await screen.findByTestId('private-note-badge')).toHaveTextContent('Private note — Riya');
    expect(screen.getByText('internal only')).toBeInTheDocument();
  });

  it('priority select updates the chat priority', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [],
      has_more: false,
      next_before: null,
    });
    vi.mocked(client.setChatPriority).mockResolvedValue({ chat: 'CHAT-1', priority: 'urgent' });
    const user = userEvent.setup();
    renderPane();
    await user.selectOptions(await screen.findByLabelText('Priority'), 'urgent');
    await waitFor(() => {
      expect(client.setChatPriority).toHaveBeenCalledWith('CHAT-1', 'urgent');
    });
  });

  it('runs a macro from the macro menu', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [],
      has_more: false,
      next_before: null,
    });
    vi.mocked(client.listMacros).mockResolvedValue({
      macros: [
        {
          name: 'MAC-1',
          macro_name: 'VIP intake',
          visibility: 'global',
          actions: [{ type: 'set_priority', value: 'high' }],
          run_count: 0,
          created_by: null,
        },
      ],
    });
    vi.mocked(client.runMacro).mockResolvedValue({
      results: [{ type: 'set_priority', ok: true }],
      run_count: 1,
    });
    const user = userEvent.setup();
    renderPane();
    await user.click(await screen.findByLabelText('Run macro'));
    await user.click(await screen.findByText('VIP intake'));
    await waitFor(() => {
      expect(client.runMacro).toHaveBeenCalledWith('MAC-1', 'CHAT-1');
    });
  });

  it('flagged messages show the monitoring badge', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [
        message({ name: 'M1', body: 'yeh scam hai', flagged: true, flag_reason: 'Competitor watch' }),
      ],
      has_more: false,
      next_before: null,
    });
    renderPane();
    expect(await screen.findByTestId('flag-badge')).toHaveTextContent('Competitor watch');
  });

  it('dm chats never show sender names', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [message({ name: 'M1', body: 'hello', sender_display: 'Asha' })],
      has_more: false,
      next_before: null,
    });
    renderPane(chatRow({ chat_type: 'dm' }));
    expect(await screen.findByText('hello')).toBeInTheDocument();
    expect(screen.queryByTestId('sender-name')).not.toBeInTheDocument();
  });

  it('renders quoted snippets and a media placeholder when media is not downloaded', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [
        message({ name: 'M1', quoted_message: 'M0', quoted_body: 'original', body: 'reply' }),
        message({ name: 'M2', message_type: 'audio', body: null, has_media: false }),
      ],
      has_more: false,
      next_before: null,
    });
    renderPane();

    expect(await screen.findByText('original')).toBeInTheDocument();
    expect(screen.getByText('reply')).toBeInTheDocument();
    // No downloaded media → labelled placeholder, no getMediaUrl call.
    expect(screen.getByText(/Voice message/)).toBeInTheDocument();
    expect(client.getMediaUrl).not.toHaveBeenCalled();
  });

  it('renders a voice note player with its transcript from a presigned URL', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [
        message({
          name: 'M9',
          message_type: 'audio',
          body: null,
          has_media: true,
          is_voice: true,
          transcript: 'please send the invoice',
        }),
      ],
      has_more: false,
      next_before: null,
    });
    vi.mocked(client.getMediaUrl).mockResolvedValue({
      message: 'M9',
      message_type: 'audio',
      url: 'https://minio/signed/audio.ogg',
      mimetype: 'audio/ogg',
      filename: null,
      size: 1024,
      duration: 5,
      is_voice: true,
      available: true,
    });
    renderPane();

    expect(await screen.findByTestId('media-content')).toBeInTheDocument();
    expect(screen.getByTestId('voice-transcript')).toHaveTextContent('please send the invoice');
    expect(client.getMediaUrl).toHaveBeenCalledWith('M9');
  });

  it('sends a message on Enter through the queued pipeline', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [],
      has_more: false,
      next_before: null,
    });
    vi.mocked(client.sendMessage).mockResolvedValue({ name: 'MSG-NEW', status: 'queued' });

    const user = userEvent.setup();
    renderPane();
    const box = await screen.findByLabelText('Message');
    await user.type(box, 'namaste ji{Enter}');

    expect(client.sendMessage).toHaveBeenCalledWith('CHAT-1', 'namaste ji');
    expect(box).toHaveValue(''); // draft cleared
  });

  it('Shift+Enter makes a newline instead of sending', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [],
      has_more: false,
      next_before: null,
    });
    const user = userEvent.setup();
    renderPane();
    const box = await screen.findByLabelText('Message');
    await user.type(box, 'line1{Shift>}{Enter}{/Shift}line2');
    expect(client.sendMessage).not.toHaveBeenCalled();
    expect(box).toHaveValue('line1\nline2');
  });

  it('failed outbound bubbles offer retry', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [
        message({ name: 'M-FAIL', direction: 'out', status: 'failed', body: 'lost one' }),
      ],
      has_more: false,
      next_before: null,
    });
    vi.mocked(client.retryMessage).mockResolvedValue({ name: 'M-FAIL', status: 'queued' });

    const user = userEvent.setup();
    renderPane();
    await user.click(await screen.findByLabelText('Retry send'));
    expect(client.retryMessage).toHaveBeenCalledWith('M-FAIL');
  });

  it('loads earlier messages via the cursor', async () => {
    vi.mocked(client.listMessages)
      .mockResolvedValueOnce({
        messages: [message({ name: 'M3', body: 'newest' })],
        has_more: true,
        next_before: '2026-07-07 11:00:00',
      })
      .mockResolvedValueOnce({
        messages: [message({ name: 'M1', body: 'older' })],
        has_more: false,
        next_before: null,
      });

    const user = userEvent.setup();
    renderPane();
    await user.click(await screen.findByRole('button', { name: 'Load earlier messages' }));

    expect(await screen.findByText('older')).toBeInTheDocument();
    expect(screen.getByText('newest')).toBeInTheDocument();
    await waitFor(() => {
      expect(client.listMessages).toHaveBeenCalledWith('CHAT-1', '2026-07-07 11:00:00');
    });
    // older page renders ABOVE the newest page
    const bodies = screen.getAllByTestId('message-bubble').map((el) => el.textContent);
    expect(bodies[0]).toContain('older');
    expect(bodies[1]).toContain('newest');
  });

  // --- P1.7: assignment, status, presence ---

  const emptyThread = () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [],
      has_more: false,
      next_before: null,
    });
  };

  it('assigns the chat to a member from the header picker', async () => {
    emptyThread();
    vi.mocked(client.assignChat).mockResolvedValue({
      chat: 'CHAT-1',
      assigned_agent: 'riya@x.test',
      assigned_team: null,
    });
    const user = userEvent.setup();
    renderPane();
    const picker = await screen.findByLabelText('Assignee');
    await screen.findByRole('option', { name: 'Riya' });
    await user.selectOptions(picker, 'riya@x.test');
    expect(client.assignChat).toHaveBeenCalledWith('CHAT-1', 'riya@x.test');
  });

  it('resolves the chat via the header button', async () => {
    emptyThread();
    vi.mocked(client.setChatStatus).mockResolvedValue({
      chat: 'CHAT-1',
      status: 'resolved',
      snoozed_until: null,
    });
    const user = userEvent.setup();
    renderPane();
    await user.click(await screen.findByRole('button', { name: 'Resolve' }));
    expect(client.setChatStatus).toHaveBeenCalledWith('CHAT-1', 'resolved', undefined);
  });

  it('snooze preset sends a future timestamp', async () => {
    emptyThread();
    vi.mocked(client.setChatStatus).mockResolvedValue({
      chat: 'CHAT-1',
      status: 'snoozed',
      snoozed_until: 'x',
    });
    const user = userEvent.setup();
    renderPane();
    await user.selectOptions(await screen.findByLabelText('Status'), 'snooze-1h');
    expect(client.setChatStatus).toHaveBeenCalledWith(
      'CHAT-1',
      'snoozed',
      expect.stringMatching(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/),
    );
  });

  it('heartbeats viewing presence and shows other agents', async () => {
    emptyThread();
    vi.mocked(useChatPresence).mockReturnValue([{ fullName: 'Riya', state: 'typing' }]);
    renderPane();
    expect(await screen.findByTestId('presence-indicator')).toHaveTextContent('Riya is typing…');
    await waitFor(() => {
      expect(client.presencePing).toHaveBeenCalledWith('CHAT-1', 'viewing');
    });
  });

  it('typing in the composer pings typing presence', async () => {
    emptyThread();
    const user = userEvent.setup();
    renderPane();
    await user.type(await screen.findByLabelText('Message'), 'hi');
    await waitFor(() => {
      expect(client.presencePing).toHaveBeenCalledWith('CHAT-1', 'typing');
    });
  });

  // --- P1.9: canned responses + labels ---

  it('/ opens the canned menu and Enter inserts with variables substituted', async () => {
    emptyThread();
    vi.mocked(client.searchCanned).mockResolvedValue([
      { name: 'CANNED-1', shortcode: 'greet', content: 'Namaste {{contact.name}}!' },
      { name: 'CANNED-2', shortcode: 'closing', content: 'Anything else?' },
    ]);
    const user = userEvent.setup();
    renderPane();
    const box = await screen.findByLabelText('Message');
    await user.type(box, '/gr');
    expect(await screen.findByTestId('canned-menu')).toBeInTheDocument();
    expect(screen.getAllByTestId('canned-item')).toHaveLength(2);
    await waitFor(() => {
      expect(client.searchCanned).toHaveBeenCalledWith('gr');
    });

    await user.keyboard('{Enter}');
    // Enter selects — it must NOT send while the menu is open
    expect(client.sendMessage).not.toHaveBeenCalled();
    expect(box).toHaveValue('Namaste Asha Traders!');
    expect(screen.queryByTestId('canned-menu')).not.toBeInTheDocument();
  });

  it('arrow keys move the canned selection before Enter picks it', async () => {
    emptyThread();
    vi.mocked(client.searchCanned).mockResolvedValue([
      { name: 'CANNED-1', shortcode: 'greet', content: 'Namaste!' },
      { name: 'CANNED-2', shortcode: 'closing', content: 'Anything else?' },
    ]);
    const user = userEvent.setup();
    renderPane();
    const box = await screen.findByLabelText('Message');
    await user.type(box, '/');
    await screen.findByTestId('canned-menu');
    await user.keyboard('{ArrowDown}{Enter}');
    expect(box).toHaveValue('Anything else?');
  });

  it('unresolved variables stay literal', async () => {
    emptyThread();
    vi.mocked(client.searchCanned).mockResolvedValue([
      { name: 'CANNED-1', shortcode: 'order', content: 'Order {{order.id}} shipped' },
    ]);
    const user = userEvent.setup();
    renderPane();
    const box = await screen.findByLabelText('Message');
    await user.type(box, '/order');
    await screen.findByTestId('canned-menu');
    await user.keyboard('{Enter}');
    expect(box).toHaveValue('Order {{order.id}} shipped');
  });

  it('converts the conversation into a ticket from the last inbound message', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [
        message({ name: 'M1', body: 'order missing', direction: 'in' }),
        message({ name: 'M2', body: 'looking into it', direction: 'out' }),
      ],
      has_more: false,
      next_before: null,
    });
    const user = userEvent.setup();
    renderPane();
    await user.click(await screen.findByLabelText('Create ticket'));
    expect(client.createTicket).toHaveBeenCalledWith({
      chat: 'CHAT-1',
      source_message: 'M1',
    });
  });

  it('label picker applies the full selection to the chat', async () => {
    emptyThread();
    vi.mocked(client.listLabels).mockResolvedValue([
      { name: 'LBL-1', title: 'vip', color: '#ff5533', description: null },
      { name: 'LBL-2', title: 'billing', color: '#1f93ff', description: null },
    ]);
    vi.mocked(client.setChatLabels).mockResolvedValue({ chat: 'CHAT-1', labels: [] });
    const user = userEvent.setup();
    renderPane(chatRow({ labels: [{ label: 'LBL-1', title: 'vip', color: '#ff5533' }] }));
    await user.click(await screen.findByLabelText('Labels'));
    const billing = await screen.findByRole('checkbox', { name: /billing/ });
    expect(screen.getByRole('checkbox', { name: /vip/ })).toBeChecked();
    await user.click(billing);
    expect(client.setChatLabels).toHaveBeenCalledWith('CHAT-1', ['LBL-1', 'LBL-2']);
  });
});
