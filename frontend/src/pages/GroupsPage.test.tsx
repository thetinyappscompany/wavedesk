import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdGroup } from '@wavedesk/api-client';
import GroupsPage from './GroupsPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listGroups: vi.fn(),
    getWorkspaceSettings: vi.fn(),
    sendToGroups: vi.fn(),
  },
}));
vi.mock('@/lib/realtime', () => ({
  useWorkspaceEvents: vi.fn(),
}));
vi.mock('@/components/GroupDrawer', () => ({
  default: ({ groupName }: { groupName: string }) => (
    <div data-testid="group-drawer">{groupName}</div>
  ),
}));

function group(overrides: Partial<WdGroup>): WdGroup {
  return {
    name: 'GRP-1',
    wa_group_id: '120363000000000001@g.us',
    subject: 'Surat Traders',
    description: 'traders of surat',
    member_count: 128,
    invite_link: null,
    owned_by_us: false,
    number: 'WNUM-1',
    number_name: 'Sales Line',
    chat: 'CHAT-1',
    last_message_at: '2026-07-09 09:00:00',
    unread_count: 3,
    msgs_today: 42,
    needs_reply: false,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <GroupsPage />
    </QueryClientProvider>,
  );
}

describe('GroupsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.getWorkspaceSettings).mockResolvedValue({
      workspace: 'WS-1',
      workspace_name: 'Asha & Co',
      role: 'Owner',
      mask_numbers: false,
      needs_reply_minutes: 10,
    });
  });

  it('renders the registry table with stats and admin badge', async () => {
    vi.mocked(client.listGroups).mockResolvedValue({
      groups: [
        group({ name: 'GRP-1', subject: 'Surat Traders', owned_by_us: true, needs_reply: true }),
        group({
          name: 'GRP-2',
          subject: 'Quiet Corner',
          member_count: 12,
          msgs_today: 0,
          unread_count: 0,
        }),
      ],
      total: 2,
    });
    renderPage();
    expect(await screen.findByText('Surat Traders')).toBeInTheDocument();
    expect(screen.getAllByTestId('group-needs-reply')).toHaveLength(1);
    expect(screen.getByText('Quiet Corner')).toBeInTheDocument();
    expect(screen.getAllByTestId('group-row')).toHaveLength(2);
    expect(screen.getByText('128')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByLabelText('We are admin')).toBeInTheDocument();
    expect(screen.getByText('2 groups')).toBeInTheDocument();
  });

  it('debounces search into the API call', async () => {
    vi.mocked(client.listGroups).mockResolvedValue({ groups: [], total: 0 });
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByPlaceholderText('Search groups…'), 'surat');
    await waitFor(() => {
      expect(client.listGroups).toHaveBeenCalledWith(
        expect.objectContaining({ search: 'surat' }),
      );
    });
  });

  it('bulk select tracks rows and select-all toggles', async () => {
    vi.mocked(client.listGroups).mockResolvedValue({
      groups: [group({ name: 'GRP-1' }), group({ name: 'GRP-2', subject: 'Second' })],
      total: 2,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByLabelText('Select Surat Traders'));
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('1 selected');

    await user.click(screen.getByLabelText('Select all groups'));
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('2 selected');

    await user.click(screen.getByLabelText('Select all groups'));
    expect(screen.queryByTestId('bulk-bar')).not.toBeInTheDocument();
  });

  it('bulk message dialog sends to the selected groups', async () => {
    vi.mocked(client.listGroups).mockResolvedValue({
      groups: [group({ name: 'GRP-1' }), group({ name: 'GRP-2', subject: 'Second' })],
      total: 2,
    });
    vi.mocked(client.sendToGroups).mockResolvedValue({ queued_groups: 2 });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByLabelText('Select all groups'));
    await user.click(screen.getByRole('button', { name: /Message 2 groups/ }));
    await user.type(screen.getByLabelText(/Message to 2 selected/), 'diwali offer 10% off');
    await user.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => {
      expect(client.sendToGroups).toHaveBeenCalledWith(
        ['GRP-1', 'GRP-2'],
        'diwali offer 10% off',
      );
    });
    expect(await screen.findByTestId('bulk-result')).toHaveTextContent('Queued for 2 groups');
    expect(screen.queryByTestId('bulk-dialog')).not.toBeInTheDocument();
  });

  it('agents see no bulk message button', async () => {
    vi.mocked(client.getWorkspaceSettings).mockResolvedValue({
      workspace: 'WS-1',
      workspace_name: 'Asha & Co',
      role: 'Agent',
      mask_numbers: false,
      needs_reply_minutes: 10,
    });
    vi.mocked(client.listGroups).mockResolvedValue({
      groups: [group({ name: 'GRP-1' })],
      total: 1,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByLabelText('Select Surat Traders'));
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('1 selected');
    expect(screen.queryByRole('button', { name: /Message 1 group/ })).not.toBeInTheDocument();
  });

  it('clicking a group subject opens the drawer', async () => {
    vi.mocked(client.listGroups).mockResolvedValue({
      groups: [group({ name: 'GRP-1' })],
      total: 1,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId('group-open'));
    expect(screen.getByTestId('group-drawer')).toHaveTextContent('GRP-1');
  });

  it('shows the empty state', async () => {
    vi.mocked(client.listGroups).mockResolvedValue({ groups: [], total: 0 });
    renderPage();
    expect(await screen.findByText(/No groups yet/)).toBeInTheDocument();
  });
});
