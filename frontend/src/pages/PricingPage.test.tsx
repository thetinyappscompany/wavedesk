import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import PricingPage from './PricingPage';

function renderPage() {
  return render(
    <MemoryRouter>
      <PricingPage />
    </MemoryRouter>,
  );
}

describe('PricingPage', () => {
  it('renders all four plan tiers with their prices', () => {
    renderPage();
    const tiers = screen.getAllByTestId('pricing-tier');
    expect(tiers).toHaveLength(4);
    expect(screen.getByText('Free Trial')).toBeInTheDocument();
    expect(screen.getByText('₹1,499')).toBeInTheDocument();
    expect(screen.getByText('₹3,999')).toBeInTheDocument();
    expect(screen.getByText('₹4,999')).toBeInTheDocument();
    expect(screen.getByText('Most popular')).toBeInTheDocument();
  });

  it('every plan CTA leads to signup', () => {
    renderPage();
    const ctas = [
      'Start free trial',
      'Start with Starter',
      'Start with Pro',
      'Start with Business',
    ];
    for (const label of ctas) {
      expect(screen.getByRole('link', { name: label })).toHaveAttribute('href', '/signup');
    }
  });

  it('shows the AI add-on as a flat price with no internal pricing details', () => {
    renderPage();
    expect(screen.getByText(/AI Add-on — ₹1,200\/mo/)).toBeInTheDocument();
    // confidential mechanics must never appear client-side (non-negotiable #4)
    const body = document.body.textContent ?? '';
    expect(body).not.toMatch(/1\.25|markup|cost×|token rate|\$5/i);
  });
});
