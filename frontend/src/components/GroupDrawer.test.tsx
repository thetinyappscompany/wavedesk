import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdGroupDetail } from '@wavedesk/api-client';
import GroupDrawer from './GroupDrawer';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    getGroup: vi.fn(),
    updateGroup: vi.fn(),
    groupParticipants: vi.fn(),
    revokeGroupInvite: vi.fn(),
  },
}));
vi.mock('@/components/GroupAnalytics', () => ({
  default: () => <div data-testid="group-analytics-stub" />,
}));

function detail(overrides: Partial<WdGroupDetail> = {}): WdGroupDetail {
  return {
    name: 'GRP-1',
    wa_group_id: '120363000011112222@g.us',
    subject: 'Surat Traders',
    description: 'traders of surat',
    member_count: 2,
    invite_link: 'https://chat.whatsapp.com/OLDCODE',
    owned_by_us: true,
    number: 'WNUM-1',
    members: [
      {
        name: 'GRPM-1',
        display: '919111100001',
        contact: 'CONT-1',
        contact_name: 'Riya',
        role: 'member',
        joined_at: '2026-07-09 01:00:00',
      },
      {
        name: 'GRPM-2',
        display: '919222200002',
        contact: null,
        contact_name: null,
        role: 'admin',
        joined_at: null,
      },
    ],
    ...overrides,
  };
}

function renderDrawer(canManage = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <GroupDrawer groupName="GRP-1" canManage={canManage} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe('GroupDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.getGroup).mockResolvedValue(detail());
    vi.mocked(client.updateGroup).mockResolvedValue({ group: 'GRP-1' });
    vi.mocked(client.groupParticipants).mockResolvedValue({
      group: 'GRP-1',
      action: 'promote',
      count: 1,
    });
    vi.mocked(client.revokeGroupInvite).mockResolvedValue({
      group: 'GRP-1',
      invite_link: 'https://chat.whatsapp.com/FRESH',
    });
  });

  it('renders detail, members, and roles', async () => {
    renderDrawer();
    expect(await screen.findByLabelText('Subject')).toHaveValue('Surat Traders');
    const members = screen.getAllByTestId('group-member-row');
    expect(members).toHaveLength(2);
    expect(members[0]).toHaveTextContent('Riya');
    expect(members[1]).toHaveTextContent('919222200002');
    expect(members[1]).toHaveTextContent('admin');
    expect(screen.getByText('https://chat.whatsapp.com/OLDCODE')).toBeInTheDocument();
  });

  it('saves edited metadata', async () => {
    const user = userEvent.setup();
    renderDrawer();
    const subject = await screen.findByLabelText('Subject');
    await user.clear(subject);
    await user.type(subject, 'Surat Traders 2.0');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(client.updateGroup).toHaveBeenCalledWith('GRP-1', {
        subject: 'Surat Traders 2.0',
      });
    });
  });

  it('promote / remove / add call the participants API', async () => {
    const user = userEvent.setup();
    renderDrawer();
    await user.click(await screen.findByLabelText('Promote 919111100001'));
    expect(client.groupParticipants).toHaveBeenCalledWith('GRP-1', ['919111100001'], 'promote');

    await user.click(screen.getByLabelText('Demote 919222200002'));
    expect(client.groupParticipants).toHaveBeenCalledWith('GRP-1', ['919222200002'], 'demote');

    await user.click(screen.getByLabelText('Remove 919111100001'));
    expect(client.groupParticipants).toHaveBeenCalledWith('GRP-1', ['919111100001'], 'remove');

    await user.type(screen.getByLabelText('Add participant phone'), '919333300003');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(client.groupParticipants).toHaveBeenCalledWith('GRP-1', ['919333300003'], 'add');
  });

  it('revokes the invite link', async () => {
    const user = userEvent.setup();
    renderDrawer();
    await user.click(await screen.findByRole('button', { name: /Revoke/ }));
    expect(client.revokeGroupInvite).toHaveBeenCalledWith('GRP-1');
  });

  it('read-only when the viewer cannot manage', async () => {
    renderDrawer(false);
    expect(await screen.findByLabelText('Subject')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Revoke/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Add participant phone')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Remove 919111100001')).not.toBeInTheDocument();
  });

  it('switches to the analytics tab', async () => {
    const user = userEvent.setup();
    renderDrawer();
    await user.click(await screen.findByRole('tab', { name: 'analytics' }));
    expect(screen.getByTestId('group-analytics-stub')).toBeInTheDocument();
    expect(screen.queryByLabelText('Subject')).not.toBeInTheDocument();
  });
});
