import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdScheduledMessage } from '@wavedesk/api-client';
import SchedulesPage from './SchedulesPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listSchedules: vi.fn(),
    createSchedule: vi.fn(),
    updateSchedule: vi.fn(),
    cancelSchedule: vi.fn(),
    runScheduleNow: vi.fn(),
    deleteSchedule: vi.fn(),
  },
}));
vi.mock('@/lib/realtime', () => ({ useWorkspaceEvents: vi.fn() }));

function sched(overrides: Partial<WdScheduledMessage> = {}): WdScheduledMessage {
  return {
    name: 'SCHED-1',
    title: 'Monday standup',
    target_type: 'group',
    target: 'GRP-1',
    number: null,
    body: 'Standup!',
    schedule_type: 'recurring',
    scheduled_at: null,
    recurrence: { frequency: 'weekly', time: '09:00', weekdays: [0] },
    timezone: 'Asia/Kolkata',
    next_run_at: '2026-07-20 09:00:00',
    last_run_at: null,
    run_count: 0,
    status: 'scheduled',
    enabled: true,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SchedulesPage />
    </QueryClientProvider>,
  );
}

describe('SchedulesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listSchedules).mockResolvedValue([sched()]);
  });

  it('lists schedules with their recurrence summary', async () => {
    renderPage();
    const row = await screen.findByTestId('schedule-row');
    expect(row).toHaveTextContent('Monday standup');
    expect(row).toHaveTextContent('weekly at 09:00');
    expect(row).toHaveTextContent('Mon');
  });

  it('creates a one-time schedule', async () => {
    vi.mocked(client.createSchedule).mockResolvedValue(sched());
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'New schedule' }));
    await user.type(screen.getByLabelText('Schedule title'), 'Reminder');
    await user.type(screen.getByLabelText('Target id'), 'CHAT-9');
    await user.type(screen.getByLabelText('Message body'), 'Ping');
    await user.selectOptions(screen.getByLabelText('Schedule type'), 'once');
    await user.type(screen.getByLabelText('Send at'), '2026-07-15T09:30');
    await user.click(screen.getByRole('button', { name: 'Schedule' }));

    await waitFor(() => {
      expect(client.createSchedule).toHaveBeenCalledWith({
        title: 'Reminder',
        targetType: 'chat',
        target: 'CHAT-9',
        scheduleType: 'once',
        body: 'Ping',
        scheduledAt: '2026-07-15 09:30:00',
      });
    });
  });

  it('runs a schedule now and cancels', async () => {
    vi.mocked(client.runScheduleNow).mockResolvedValue(sched({ status: 'sent' }));
    vi.mocked(client.cancelSchedule).mockResolvedValue(sched({ status: 'cancelled' }));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByLabelText('Run Monday standup now'));
    expect(client.runScheduleNow).toHaveBeenCalledWith('SCHED-1');
    await user.click(screen.getByLabelText('Cancel Monday standup'));
    expect(client.cancelSchedule).toHaveBeenCalledWith('SCHED-1');
  });
});
