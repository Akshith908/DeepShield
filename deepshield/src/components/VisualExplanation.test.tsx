import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { GRADCAM_DISCLAIMER, VisualExplanation } from './VisualExplanation';

const HEATMAP_URI = 'data:image/png;base64,heat';
const OVERLAY_URI = 'data:image/png;base64,overlay';

const SUCCESS_PAYLOAD = {
  success: true,
  model_id: 'honi05/deepfake-detection:efficientnet-b4-celebdf',
  model_source: 'https://huggingface.co/honi05/deepfake-detection',
  model_license: 'MIT',
  gradcam_layer: 'features[-1]',
  local_prediction: 'FAKE',
  local_confidence: 87.4,
  fake_probability: 87.4,
  heatmap: HEATMAP_URI,
  overlay: OVERLAY_URI,
  image_width: 800,
  image_height: 600,
  overlay_width: 800,
  overlay_height: 600,
  analysed_crop: { x: 10, y: 10, width: 200, height: 200 },
  faces_detected: 1,
  processing_time: 1.23,
  limitations: ['The local model is a face-level classifier.'],
};

function mockFetch(response: { ok: boolean; status: number; body: unknown }) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: response.ok,
    status: response.status,
    json: () => Promise.resolve(response.body),
  });

  vi.stubGlobal('fetch', fetchMock);

  return fetchMock;
}

const FILE = new File(['fake-bytes'], 'portrait.jpg', { type: 'image/jpeg' });

describe('VisualExplanation', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:original'),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('uses the exact required disclaimer wording', () => {
    // Locked to the literal product copy so the string cannot drift.
    expect(GRADCAM_DISCLAIMER).toBe(
      "Local model explanation: This heatmap highlights regions influencing the local model's prediction. It does not prove that those regions are manipulated and may not explain the verdict returned by an external detection provider."
    );
  });

  it('does nothing until the user asks for an explanation', () => {
    const fetchMock = mockFetch({ ok: true, status: 200, body: SUCCESS_PAYLOAD });

    render(<VisualExplanation file={FILE} />);

    expect(screen.getByRole('button', { name: /generate visual explanation/i })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(GRADCAM_DISCLAIMER)).toBeInTheDocument();
  });

  it('shows a loading state while the local model runs', async () => {
    let resolveJson: (value: unknown) => void = () => {};

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () =>
          new Promise((resolve) => {
            resolveJson = resolve;
          }),
      })
    );

    render(<VisualExplanation file={FILE} />);

    fireEvent.click(screen.getByRole('button', { name: /generate visual explanation/i }));

    expect(await screen.findByRole('status')).toHaveTextContent(/running the local model/i);

    resolveJson(SUCCESS_PAYLOAD);

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  });

  it('renders the heatmap, overlay, model metadata and disclaimer on success', async () => {
    const fetchMock = mockFetch({ ok: true, status: 200, body: SUCCESS_PAYLOAD });

    render(<VisualExplanation file={FILE} />);

    fireEvent.click(screen.getByRole('button', { name: /generate visual explanation/i }));

    expect(await screen.findByText(/local model: fake/i)).toBeInTheDocument();
    expect(screen.getByText(/87\.4% confidence/i)).toBeInTheDocument();
    expect(screen.getByText(/honi05\/deepfake-detection/)).toBeInTheDocument();
    expect(screen.getByText('features[-1]')).toBeInTheDocument();
    expect(screen.getByText('The local model is a face-level classifier.')).toBeInTheDocument();
    expect(screen.getByText(GRADCAM_DISCLAIMER)).toBeInTheDocument();

    const overlay = screen.getByAltText(/grad-cam heatmap blended over the original/i);
    expect(overlay).toHaveAttribute('src', OVERLAY_URI);
    expect(screen.queryByAltText('Grad-CAM heatmap')).not.toBeInTheDocument();

    expect(fetchMock.mock.calls[0][0]).toContain('/explain');
  });

  it('adjusts heatmap opacity and switches to a side-by-side view', async () => {
    mockFetch({ ok: true, status: 200, body: SUCCESS_PAYLOAD });

    render(<VisualExplanation file={FILE} />);

    fireEvent.click(screen.getByRole('button', { name: /generate visual explanation/i }));

    const slider = await screen.findByLabelText(/heatmap opacity/i);
    expect(slider).toHaveValue('60');

    fireEvent.change(slider, { target: { value: '25' } });

    const overlay = screen.getByAltText(/grad-cam heatmap blended over the original/i);
    expect(overlay).toHaveStyle({ opacity: '0.25' });

    fireEvent.click(screen.getByRole('button', { name: /side by side/i }));

    expect(screen.getByAltText('Original')).toBeInTheDocument();
    expect(screen.getByAltText('Grad-CAM heatmap')).toHaveAttribute('src', HEATMAP_URI);
    expect(screen.getByAltText('Overlay')).toHaveAttribute('src', OVERLAY_URI);
  });

  it('shows the no-face message and no heatmap', async () => {
    mockFetch({
      ok: false,
      status: 422,
      body: {
        detail: {
          code: 'no_face_detected',
          message: 'No face was detected in this image.',
        },
      },
    });

    render(<VisualExplanation file={FILE} />);

    fireEvent.click(screen.getByRole('button', { name: /generate visual explanation/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/no face was detected/i);
    expect(screen.getByText(/no heatmap is shown when generation fails/i)).toBeInTheDocument();
    expect(screen.queryByAltText(/grad-cam heatmap blended/i)).not.toBeInTheDocument();
    expect(screen.queryByAltText('Grad-CAM heatmap')).not.toBeInTheDocument();
  });

  it('shows an unavailable state when the model is missing on the server', async () => {
    mockFetch({
      ok: false,
      status: 503,
      body: {
        detail: {
          code: 'model_unavailable',
          message: 'Model weights are not available.',
        },
      },
    });

    render(<VisualExplanation file={FILE} />);

    fireEvent.click(screen.getByRole('button', { name: /generate visual explanation/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/model weights are not available/i);
    expect(screen.queryByAltText(/grad-cam heatmap blended/i)).not.toBeInTheDocument();
  });

  it('rejects an incomplete payload instead of half-rendering it', async () => {
    mockFetch({
      ok: true,
      status: 200,
      body: { ...SUCCESS_PAYLOAD, overlay: '' },
    });

    render(<VisualExplanation file={FILE} />);

    fireEvent.click(screen.getByRole('button', { name: /generate visual explanation/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/incomplete result/i);
    expect(screen.queryByAltText('Grad-CAM heatmap')).not.toBeInTheDocument();
  });

  it('reports network failures without rendering a heatmap', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));

    render(<VisualExplanation file={FILE} />);

    fireEvent.click(screen.getByRole('button', { name: /generate visual explanation/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach/i);
    expect(screen.queryByAltText(/grad-cam heatmap blended/i)).not.toBeInTheDocument();
  });
});
