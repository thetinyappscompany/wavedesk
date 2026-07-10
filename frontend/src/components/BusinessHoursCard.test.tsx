import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdWorkspaceSettings } from '@wavedesk/api-client';
import BusinessHoursCard from './BusinessHoursCard';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: { updateWorkspaceSettings: vi.fn() },
}));

const settings = {
  business_hours: { enabled: false, timezone: 'Asia/Kolkata', days: {}, holidays: [] },
  ooo_reply_enabled: false,
  ooo_reply_message: '',
} as unknown as WdWorkspaceSettings;

function renderCard(canManage = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <BusinessHoursCard canManage={canManage} settings={settings} />
    </QueryClientProvider>,
  );
}

describe('BusinessHoursCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('enables hours, a day, and OOO, then saves', async () => {
    vi.mocked(client.updateWorkspaceSettings).mockResolvedValue(settings);
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByLabelText('Enable business hours'));
    await user.click(screen.getByLabelText('Open on Mon'));
    await user.click(screen.getByLabelText('Enable out-of-office auto-reply'));
    await user.type(screen.getByLabelText('Out-of-office message'), 'Back at 9am');
    await user.click(screen.getByRole('button', { name: 'Save business hours' }));

    await waitFor(() => {
      expect(client.updateWorkspaceSettings).toHaveBeenCalledTimes(1);
    });
    const arg = vi.mocked(client.updateWorkspaceSettings).mock.calls[0]?.[0];
    expect(arg?.business_hours?.enabled).toBe(true);
    expect(arg?.business_hours?.days.mon).toEqual({ open: '09:00', close: '18:00' });
    expect(arg?.ooo_reply_enabled).toBe(true);
    expect(arg?.ooo_reply_message).toBe('Back at 9am');
  });

  it('parses holidays into a list', async () => {
    vi.mocked(client.updateWorkspaceSettings).mockResolvedValue(settings);
    const user = userEvent.setup();
    renderCard();
    await user.type(screen.getByLabelText('Holidays'), '2026-01-26, 2026-08-15');
    await user.click(screen.getByRole('button', { name: 'Save business hours' }));
    await waitFor(() => {
      const arg = vi.mocked(client.updateWorkspaceSettings).mock.calls[0]?.[0];
      expect(arg?.business_hours?.holidays).toEqual(['2026-01-26', '2026-08-15']);
    });
  });

  it('hides the save button for agents', () => {
    renderCard(false);
    expect(screen.queryByRole('button', { name: 'Save business hours' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Enable business hours')).toBeDisabled();
  });
});
