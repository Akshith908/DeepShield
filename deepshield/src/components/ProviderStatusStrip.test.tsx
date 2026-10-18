import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProviderStatusStrip } from './ProviderStatusStrip';
import type { ProviderOutcome } from '../types/analysis';

const BITMIND_OK: ProviderOutcome = {
  provider: 'BitMind',
  status: 'OK',
  prediction: 'LIKELY_AI_GENERATED',
  riskScore: 88,
};

const RD_FAILED: ProviderOutcome = {
  provider: 'Reality Defender',
  status: 'FAILED',
  message: 'Provider rejected the request.',
};

const RD_OK: ProviderOutcome = {
  provider: 'Reality Defender',
  status: 'OK',
  prediction: 'LIKELY_AUTHENTIC',
  riskScore: 15,
};

describe('ProviderStatusStrip', () => {
  it('renders nothing when no provider ledger is present', () => {
    const { container } = render(<ProviderStatusStrip />);

    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for a healthy single-provider result', () => {
    const { container } = render(
      <ProviderStatusStrip providers={[BITMIND_OK]} />
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('renders both provider results for a two-provider result', () => {
    render(
      <ProviderStatusStrip providers={[BITMIND_OK, RD_OK]} />
    );

    expect(screen.getByText('Provider Results')).toBeInTheDocument();
    expect(screen.getByText('BitMind')).toBeInTheDocument();
    expect(screen.getByText('Reality Defender')).toBeInTheDocument();
    expect(screen.getByText(/88\.0% risk/)).toBeInTheDocument();
    expect(screen.getByText(/15\.0% risk/)).toBeInTheDocument();
  });

  it('reports the failed provider status without a fabricated score', () => {
    render(<ProviderStatusStrip providers={[BITMIND_OK, RD_FAILED]} />);

    expect(screen.getByText(/failed/)).toBeInTheDocument();
    expect(
      screen.getByText(/Provider rejected the request\./)
    ).toBeInTheDocument();
  });
});
