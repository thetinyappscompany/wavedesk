import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ContactsPage from './ContactsPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: { listContacts: vi.fn(), importContacts: vi.fn(), importStatus: vi.fn() },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ContactsPage />
    </QueryClientProvider>,
  );
}

describe('ContactsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listContacts).mockResolvedValue({
      contacts: [
        { name: 'CONT-1', phone: '919111100001', full_name: 'Asha Traders', email: 'a@x.test' },
        { name: 'CONT-2', phone: '919111100002', full_name: null, email: null },
      ],
      total: 2,
    });
  });

  it('lists contacts with total count', async () => {
    renderPage();
    expect(await screen.findByText('Asha Traders')).toBeInTheDocument();
    expect(screen.getByText('2 contacts')).toBeInTheDocument();
    expect(screen.getAllByTestId('contact-row')).toHaveLength(2);
  });

  it('debounces search into the API call', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByPlaceholderText(/Search name, phone or email/), 'Asha');
    await waitFor(() => {
      expect(client.listContacts).toHaveBeenCalledWith(
        expect.objectContaining({ search: 'Asha' }),
      );
    });
  });

  it('runs the CSV import flow and shows counts + error download', async () => {
    vi.mocked(client.importContacts).mockResolvedValue({
      import: 'CIMP-1',
      status: 'pending',
    });
    vi.mocked(client.importStatus).mockResolvedValue({
      import: 'CIMP-1',
      file_name: 'contacts.csv',
      status: 'completed',
      total_rows: 3,
      imported_rows: 2,
      merged_rows: 0,
      rejected_rows: 1,
      error_csv: 'name,phone,errors\nBad,123,phone is missing or invalid\n',
      failure_reason: null,
    });

    const user = userEvent.setup();
    renderPage();
    const file = new File(['name,phone\nA,919111100003\n'], 'contacts.csv', {
      type: 'text/csv',
    });
    await user.upload(screen.getByTestId('import-file-input'), file);

    await waitFor(() => {
      expect(client.importContacts).toHaveBeenCalledWith(
        'name,phone\nA,919111100003\n',
        'contacts.csv',
      );
    });
    expect(await screen.findByTestId('import-status')).toHaveTextContent(
      'Done: 2 new · 0 updated · 1 rejected',
    );
    expect(screen.getByRole('button', { name: 'Download rejected rows' })).toBeInTheDocument();
  });
});
