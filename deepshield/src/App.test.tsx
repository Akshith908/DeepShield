import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import App from './App';

// Representative normalized backend payload exactly as the /analyze endpoint
// would deliver it (snake_case provider fields).
const REP_PAYLOAD = {
  success: true,
  media_type: 'image',
  prediction: 'LIKELY_AI_GENERATED',
  risk_score: 88.4,
  risk_level: 'HIGH',
  confidence: 88.4,
  analysis_time: 2.5,
  provider: 'BitMind',
  signals: [
    { name: 'AI Generation Detection', value: 'AI-generated', score: 88.4 },
  ],
  explanation: {
    summary: 'The BitMind detector flagged this image as AI-generated with 88.4% risk, above the 30% low-risk threshold.',
    reasons: [
      'BitMind classified the file as AI-generated at 88.4% confidence; risk score equals that confidence.',
      'Largest contributor: AI Generation Detection accounted for +88.4 of the risk score.',
    ],
    contributions: [
      { name: 'AI Generation Detection', value: 'AI-generated', score: 88.4, points: 88.4 },
    ],
    caveat: 'This verdict rests on a single detector output, so there is no cross-model agreement check.',
  },
};

describe('App RESULTS view shows the explanation', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:preview'),
      revokeObjectURL: vi.fn(),
    });

    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(REP_PAYLOAD),
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the explanation inside the results after analyzing a file', async () => {
    render(<App />);

    // Upload through the file input inside UploadZone.
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();

    fireEvent.change(input, {
      target: { files: [new File(['fake-bytes'], 'photo.jpg', { type: 'image/jpeg' })] },
    });

    // Advance to the FilePreview and start analysis.
    fireEvent.click(await screen.findByRole('button', { name: /analyze media/i }));

    // The backend receives the upload.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain('/analyze');

    // The RESULTS view is reached and displays the explanation content.
    expect(await screen.findByText('Explainable AI')).toBeInTheDocument();
    expect(
      screen.getByText(/flagged this image as AI-generated with 88.4% risk/)
    ).toBeInTheDocument();
    expect(
      screen.getByText('BitMind classified the file as AI-generated at 88.4% confidence; risk score equals that confidence.')
    ).toBeInTheDocument();
    // Renders in both the signals table and the explanation contribution row.
    expect(screen.getAllByText('AI Generation Detection').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('88.4% → +88.4')).toBeInTheDocument();
    expect(
      screen.getByText(/cross-model agreement check/i)
    ).toBeInTheDocument();
  });
});
