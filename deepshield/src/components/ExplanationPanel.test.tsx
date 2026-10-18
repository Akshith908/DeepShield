import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ExplanationPanel } from './ExplanationPanel';
import type { AnalysisExplanation } from '../types/analysis';

const FULL: AnalysisExplanation = {
  summary: 'The BitMind detector flagged this image as AI-generated with 88.4% risk.',
  reasons: [
    'BitMind classified the file as AI-generated at 88.4% confidence.',
    'Largest contributor: AI Generation Detection (+88.4 of the risk score).',
  ],
  contributions: [
    { name: 'AI Generation Detection', value: 'AI-generated', score: 88.4, points: 88.4 },
    { name: 'Spectrogram Evidence', value: 'ANOMALOUS', score: 41.0, points: 0.1 },
  ],
  caveat: 'This verdict rests on a single detector output, so treat scores near the 30-70% band as inconclusive.',
};

describe('ExplanationPanel', () => {
  it('renders nothing when no explanation is provided', () => {
    const { container } = render(<ExplanationPanel />);

    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when explanation is undefined', () => {
    const { container } = render(<ExplanationPanel explanation={undefined} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('renders the summary text', () => {
    render(<ExplanationPanel explanation={FULL} />);

    expect(
      screen.getByText('The BitMind detector flagged this image as AI-generated with 88.4% risk.')
    ).toBeInTheDocument();
  });

  it('renders every reason in the Decision Rationale list', () => {
    render(<ExplanationPanel explanation={FULL} />);

    expect(screen.getByText('Decision Rationale')).toBeInTheDocument();
    for (const reason of FULL.reasons) {
      expect(screen.getByText(reason)).toBeInTheDocument();
    }
  });

  it('renders each contribution with its score and point allocation', () => {
    render(<ExplanationPanel explanation={FULL} />);

    expect(screen.getByText('Score Composition')).toBeInTheDocument();
    expect(screen.getByText('AI Generation Detection')).toBeInTheDocument();
    expect(screen.getByText('Spectrogram Evidence')).toBeInTheDocument();
    expect(screen.getByText('88.4% → +88.4')).toBeInTheDocument();
    expect(screen.getByText('41.0% → +0.1')).toBeInTheDocument();
  });

  it('labels the breakdown as evidence allocation, not causal proof', () => {
    render(<ExplanationPanel explanation={FULL} />);

    expect(
      screen.getByText(/proportional to each signal's evidence strength/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/evidence contributions, not definitive causal explanations/i)
    ).toBeInTheDocument();
  });

  it('renders the caveat inside a visible callout', () => {
    render(<ExplanationPanel explanation={FULL} />);

    expect(screen.getByText(FULL.caveat as string)).toBeInTheDocument();
  });

  it('omits the Rationale and Composition sections when arrays are empty', () => {
    render(
      <ExplanationPanel
        explanation={{
          summary: 'Only a summary was available.',
          reasons: [],
          contributions: [],
        }}
      />
    );

    expect(screen.getByText('Only a summary was available.')).toBeInTheDocument();
    expect(screen.queryByText('Decision Rationale')).not.toBeInTheDocument();
    expect(screen.queryByText('Score Composition')).not.toBeInTheDocument();
    expect(screen.queryByText(/evidence contributions/i)).not.toBeInTheDocument();
  });

  it('omits the caveat callout when no caveat is present', () => {
    render(
      <ExplanationPanel
        explanation={{
          summary: 'No caveats here.',
          reasons: ['A single reason.'],
          contributions: [
            { name: 'Signal', value: 'v', score: 10, points: 10 },
          ],
        }}
      />
    );

    expect(screen.queryByText(/treated as inconclusive/i)).not.toBeInTheDocument();
    expect(screen.getByText('A single reason.')).toBeInTheDocument();
  });
});
