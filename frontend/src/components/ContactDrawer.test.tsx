import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdContactProfile } from '@wavedesk/api-client';
import ContactDrawer from './ContactDrawer';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: { getContact: vi.fn(), updateContact: vi.fn(), eraseContact: vi.fn() },
}));

function profile(overrides: Partial<WdContactProfile> = {}): WdContactProfile {
  return {
    name: 'CONT-1',
    phone: '919111100001',
    full_name: 'Asha Traders',
    email: 'asha@x.test',
    custom_attributes: { city: 'Surat' },
    opt_out: false,
    chats: [
      {
        name: 'CHAT-1',
        status: 'open',
        last_message_at: '2026-07-08 12:00:00',
        unread_count: 0,
        number_name: 'Sales Line',
        number_phone: '917700000001',
      },
      {
        name: 'CHAT-2',
        status: 'resolved',
        last_message_at: '2026-07-01 12:00:00',
        unread_count: 0,
        number_name: 'Support Line',
        number_phone: '917700000002',
      },
    ],
    ...overrides,
  };
}

function renderDrawer(onOpenChat = vi.fn(), onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ContactDrawer
        contactName="CONT-1"
        activeChat="CHAT-1"
        onOpenChat={onOpenChat}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { onOpenChat, onClose };
}

describe('ContactDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.getContact).mockResolvedValue(profile());
    vi.mocked(client.updateContact).mockResolvedValue(profile());
  });

  it('shows contact fields and cross-number conversations', async () => {
    renderDrawer();
    await waitFor(() =>
      expect(screen.getByLabelText('Contact name')).toHaveValue('Asha Traders'),
    );
    expect(screen.getByText('+919111100001')).toBeInTheDocument();
    expect(screen.getByLabelText('Contact email')).toHaveValue('asha@x.test');
    expect(screen.getByText('Surat')).toBeInTheDocument();
    const chats = screen.getAllByTestId('contact-chat-row');
    expect(chats).toHaveLength(2);
    expect(chats[0]).toHaveTextContent('Sales Line');
    expect(chats[1]).toHaveTextContent('Support Line');
  });

  it('saves edited name and email', async () => {
    const user = userEvent.setup();
    renderDrawer();
    const name = await screen.findByLabelText('Contact name');
    await user.clear(name);
    await user.type(name, 'Asha & Sons');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(client.updateContact).toHaveBeenCalledWith('CONT-1', {
        full_name: 'Asha & Sons',
        email: 'asha@x.test',
      });
    });
  });

  it('erases a contact after confirmation (GDPR)', async () => {
    const user = userEvent.setup();
    vi.mocked(client.eraseContact).mockResolvedValue({ contact: 'CONT-1', erased: true });
    renderDrawer();
    await user.click(await screen.findByRole('button', { name: 'Erase contact (GDPR)' }));
    // two-step confirm — nothing sent yet
    expect(client.eraseContact).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Confirm erase' }));
    await waitFor(() => expect(client.eraseContact).toHaveBeenCalledWith('CONT-1'));
  });

  it('adds a custom attribute', async () => {
    const user = userEvent.setup();
    renderDrawer();
    await screen.findByLabelText('Attribute name');
    await user.type(screen.getByLabelText('Attribute name'), 'gstin');
    await user.type(screen.getByLabelText('Attribute value'), '24ABC');
    await user.click(screen.getByLabelText('Add attribute'));
    await waitFor(() => {
      expect(client.updateContact).toHaveBeenCalledWith('CONT-1', {
        custom_attributes: { city: 'Surat', gstin: '24ABC' },
      });
    });
  });

  it('switches conversation on chat click', async () => {
    const user = userEvent.setup();
    const { onOpenChat } = renderDrawer();
    const rows = await screen.findAllByTestId('contact-chat-row');
    const supportRow = rows[1];
    if (!supportRow) {
      throw new Error('expected two chat rows');
    }
    await user.click(supportRow);
    expect(onOpenChat).toHaveBeenCalledWith('CHAT-2');
  });
});
