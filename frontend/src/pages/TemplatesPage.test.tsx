import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdMessageTemplate } from '@wavedesk/api-client';
import TemplatesPage from './TemplatesPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listTemplates: vi.fn(),
    createTemplate: vi.fn(),
    updateTemplate: vi.fn(),
    deleteTemplate: vi.fn(),
    submitTemplate: vi.fn(),
    previewTemplate: vi.fn(),
  },
}));

function template(overrides: Partial<WdMessageTemplate> = {}): WdMessageTemplate {
  return {
    name: 'TPL-1',
    template_name: 'order_update',
    category: 'utility',
    language: 'en',
    header_text: null,
    body_text: 'Hi {{1}}, order {{2}} shipped',
    footer_text: null,
    buttons: [],
    variable_count: 2,
    status: 'draft',
    meta_template_id: null,
    rejection_reason: null,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <TemplatesPage />
    </QueryClientProvider>,
  );
}

describe('TemplatesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listTemplates).mockResolvedValue([template()]);
  });

  it('lists templates with status', async () => {
    renderPage();
    const row = await screen.findByTestId('template-row');
    expect(row).toHaveTextContent('order_update');
    expect(row).toHaveTextContent('utility');
    expect(row).toHaveTextContent('draft');
  });

  it('creates a template', async () => {
    vi.mocked(client.createTemplate).mockResolvedValue(template());
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'New template' }));
    await user.type(screen.getByLabelText('Template name'), 'welcome_msg');
    await user.type(screen.getByLabelText('Body text'), 'Welcome friend');
    await user.click(screen.getByRole('button', { name: 'Save template' }));
    await waitFor(() => {
      expect(client.createTemplate).toHaveBeenCalledWith({
        templateName: 'welcome_msg',
        bodyText: 'Welcome friend',
        category: 'utility',
        language: 'en',
      });
    });
  });

  it('submits a template and shows the gating note', async () => {
    vi.mocked(client.submitTemplate).mockResolvedValue({
      status: 'pending',
      live: false,
      note: 'No connected Cloud API number — saved as pending.',
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByLabelText('Submit order_update'));
    expect(client.submitTemplate).toHaveBeenCalledWith('TPL-1');
    expect(await screen.findByText(/No connected Cloud API number/)).toBeInTheDocument();
  });
});
