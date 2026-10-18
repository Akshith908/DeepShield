import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { analyzeMedia } from './analysisService';

// Representative normalized backend payload. Incomplete on purpose in the
// malformed cases so each test overrides only what it needs.
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
    summary: 'The BitMind detector flagged this image as AI-generated with 88.4% risk.',
    reasons: ['BitMind classified the file as AI-generated at 88.4% confidence.'],
    contributions: [
      { name: 'AI Generation Detection', value: 'AI-generated', score: 88.4, points: 88.4 },
    ],
    caveat: 'This verdict rests on a single detector output.',
  },
};

function mockBackend(payload: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve(payload),
  });
}

function makeFile(): File {
  return new File(['fake-bytes'], 'photo.jpg', { type: 'image/jpeg' });
}

describe('analyzeMedia explanation handling', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockBackend(REP_PAYLOAD));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('valid explanation is parsed and clamped into the result', async () => {
    const result = await analyzeMedia(makeFile());

    expect(result.explanation).toBeDefined();
    expect(result.explanation?.summary).toContain('88.4%');
    expect(result.explanation?.reasons).toHaveLength(1);
    expect(result.explanation?.contributions).toEqual([
      {
        name: 'AI Generation Detection',
        value: 'AI-generated',
        score: 88.4,
        points: 88.4,
      },
    ]);
    expect(result.explanation?.caveat).toBe(
      'This verdict rests on a single detector output.'
    );
  });

  it('missing explanation field yields undefined (no panel rendered)', async () => {
    vi.stubGlobal('fetch', mockBackend({ ...REP_PAYLOAD, explanation: undefined }));

    const result = await analyzeMedia(makeFile());

    expect(result.explanation).toBeUndefined();
  });

  it('null explanation field is dropped safely', async () => {
    vi.stubGlobal('fetch', mockBackend({ ...REP_PAYLOAD, explanation: null }));

    const result = await analyzeMedia(makeFile());

    expect(result.explanation).toBeUndefined();
  });

  it('non-object explanation (string) is dropped safely', async () => {
    vi.stubGlobal('fetch', mockBackend({ ...REP_PAYLOAD, explanation: 'totally-broken' }));

    const result = await analyzeMedia(makeFile());

    expect(result.explanation).toBeUndefined();
  });

  it('malformed explanation missing required arrays is dropped safely', async () => {
    vi.stubGlobal('fetch', mockBackend({
      ...REP_PAYLOAD,
      explanation: { summary: 'no reasons or contributions here' },
    }));

    const result = await analyzeMedia(makeFile());

    expect(result.explanation).toBeUndefined();
  });

  it('malformed contributions are filtered, not dropped wholesale', async () => {
    vi.stubGlobal('fetch', mockBackend({
      ...REP_PAYLOAD,
      explanation: {
        summary: 'Partial explanation survives sanitization.',
        reasons: ['Reason one', "", null, 42],
        contributions: [
          { name: 'Good', value: 'ok', score: 50, points: 10 },
          { name: 'No points', value: 'bad', score: 50, points: NaN },
          null,
          'not-an-object',
          { name: 'Out of range', value: 'clamped', score: 500, points: -5 },
        ],
        caveat: '',
      },
    }));

    const result = await analyzeMedia(makeFile());

    expect(result.explanation).toBeDefined();
    expect(result.explanation?.reasons).toEqual(['Reason one']);
    expect(result.explanation?.contributions).toHaveLength(2);
    // Garbage numeric evidence is clamped into the 0-100 range, never NaN.
    expect(result.explanation?.contributions[1]).toEqual({
      name: 'Out of range',
      value: 'clamped',
      score: 100,
      points: 0,
    });
    // Empty caveat string collapses to undefined.
    expect(result.explanation?.caveat).toBeUndefined();
  });
});
