import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdNumber } from '@wavedesk/api-client';
import NumbersPage from './NumbersPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listNumbers: vi.fn(),
    connectBaileys: vi.fn(),
    numberStatus: vi.fn(),
    disconnectNumber: vi.fn(),
    reconnectNumber: vi.fn(),
    deleteNumber: vi.fn(),
    connectCloudNumber: vi.fn(),
  },
}));

const NUMBERS: WdNumber[] = [
  {
    name: 'WNUM-00001',
    phone: '+919999900001',
    display_name: 'Support line',
    connection_type: 'baileys',
    status: 'connected',
    health_score: 100,
    daily_send_limit: 0,
    warmup_stage: 1,
    waba_id: null,
    phone_number_id: null,
  },
  {
    name: 'WNUM-00002',
    phone: '+919999900002',
    display_name: 'Marketing',
    connection_type: 'cloud_api',
    status: 'connected',
    health_score: 100,
    daily_send_limit: 0,
    warmup_stage: 1,
    waba_id: 'WABA-1',
    phone_number_id: '111222333',
  },
];

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <NumbersPage />
    </QueryClientProvider>,
  );
}

describe('NumbersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists numbers with transport and status badges', async () => {
    vi.mocked(client.listNumbers).mockResolvedValue(NUMBERS);
    renderPage();
    expect(await screen.findByText('Support line')).toBeInTheDocument();
    expect(screen.getByText('Marketing')).toBeInTheDocument();
    expect(screen.getByText('Linked device')).toBeInTheDocument();
    expect(screen.getByText('Cloud API')).toBeInTheDocument();
    expect(screen.getAllByTestId('number-row')).toHaveLength(2);
  });

  it('shows the empty state', async () => {
    vi.mocked(client.listNumbers).mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/No numbers yet/)).toBeInTheDocument();
  });

  it('starts Baileys pairing and shows the QR from polling', async () => {
    vi.mocked(client.listNumbers).mockResolvedValue([]);
    vi.mocked(client.connectBaileys).mockResolvedValue({
      number: 'WNUM-00009',
      session_ref: 'wa-x',
    });
    vi.mocked(client.numberStatus).mockResolvedValue({
      number: 'WNUM-00009',
      status: 'connecting',
      qr: 'data:image/png;base64,QRDATA',
    });

    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: 'Connect via QR' }));
    await user.click(await screen.findByRole('button', { name: 'Start QR pairing' }));

    const qr = await screen.findByAltText('WhatsApp pairing QR code');
    expect(qr).toHaveAttribute('src', 'data:image/png;base64,QRDATA');
    expect(client.connectBaileys).toHaveBeenCalled();
  });

  it('submits the Cloud API form', async () => {
    vi.mocked(client.listNumbers).mockResolvedValue([]);
    vi.mocked(client.connectCloudNumber).mockResolvedValue({
      number: 'WNUM-00010',
      status: 'connected',
    });

    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: 'Add Cloud API' }));
    await user.type(screen.getByLabelText('Phone (international)'), '+919111100222');
    await user.type(screen.getByLabelText('Phone Number ID'), '111222333');
    await user.type(screen.getByLabelText('WABA ID'), 'WABA-1');
    await user.type(screen.getByLabelText('Permanent access token'), 'EAAG-tok');
    await user.click(screen.getByRole('button', { name: 'Connect Cloud API number' }));

    expect(client.connectCloudNumber).toHaveBeenCalledWith({
      phone: '+919111100222',
      phone_number_id: '111222333',
      waba_id: 'WABA-1',
      token: 'EAAG-tok',
    });
  });
});
