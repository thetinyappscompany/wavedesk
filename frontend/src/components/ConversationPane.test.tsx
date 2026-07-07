import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdMessage } from '@wavedesk/api-client';
import ConversationPane from './ConversationPane';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: { listMessages: vi.fn(), markChatRead: vi.fn() },
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
    wa_message_id: null,
    quoted_message: null,
    quoted_body: null,
    creation: '2026-07-07 12:00:00',
    ...overrides,
  };
}

function renderPane() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConversationPane chatName="CHAT-1" title="Asha Traders" />
    </QueryClientProvider>,
  );
}

describe('ConversationPane', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.markChatRead).mockResolvedValue({ chat: 'CHAT-1', unread_count: 0 });
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

  it('renders quoted snippets and media placeholders', async () => {
    vi.mocked(client.listMessages).mockResolvedValue({
      messages: [
        message({ name: 'M1', quoted_message: 'M0', quoted_body: 'original', body: 'reply' }),
        message({ name: 'M2', message_type: 'audio', body: null }),
      ],
      has_more: false,
      next_before: null,
    });
    renderPane();

    expect(await screen.findByText('original')).toBeInTheDocument();
    expect(screen.getByText('reply')).toBeInTheDocument();
    expect(screen.getByText(/Voice message/)).toBeInTheDocument();
    expect(screen.getByText(/media preview lands/)).toBeInTheDocument();
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
});
