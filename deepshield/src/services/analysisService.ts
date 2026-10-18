import { AnalysisExplanation, AnalysisResult, ProviderOutcome } from '../types/analysis';

// Backend endpoint, overridable per environment via VITE_BACKEND_URL.
// Default '' = same origin: `npm start` (server.js) runs the FastAPI
// backend behind this app and proxies /analyze. For frontend-only dev
// (`npm run dev`), set VITE_BACKEND_URL=http://127.0.0.1:8000 in .env.local.
const BACKEND_BASE =
  (import.meta.env.VITE_BACKEND_URL as string | undefined) ?? '';

const BACKEND_URL = BACKEND_BASE.replace(/\/$/, '') + '/analyze';

// Hard cap on a single analysis request (video can legitimately take a
// while, but the UI should never hang forever on a dead server).
const REQUEST_TIMEOUT_MS = 330_000;

// Provider responses are untrusted input: a missing or malformed field must
// degrade to a sane default instead of rendering "NaN%" in the gauge.
function toFiniteNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);

  return Number.isFinite(parsed) ? parsed : fallback;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function isUsableScore(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * Normalize the backend's `providers` ledger into the shape the UI consumes.
 *
 * Legacy parser (`parseProviderOutcomes`) was removed because it was only
 * used by the stale `providerRouting` path. The main analysis path now uses
 * this helper directly.
 */
function normalizeProviders(
  raw: unknown,
): ProviderOutcome[] {
  if (!Array.isArray(raw) || raw.length === 0) return [];

  const STATUSES = new Set(['OK', 'FAILED', 'UNAVAILABLE']);

  const out = raw
    .filter(
      (item: any) =>
        item &&
        typeof item.provider === 'string' &&
        item.provider &&
        STATUSES.has(item.status)
    )
    .map((item: any) => ({
      provider: item.provider,
      status: item.status as ProviderOutcome['status'],
      prediction:
        typeof item.prediction === 'string' && item.prediction
          ? item.prediction
          : undefined,
      riskScore: isUsableScore(item.risk_score)
        ? clamp(item.risk_score, 0, 100)
        : undefined,
      message:
        typeof item.message === 'string' && item.message
          ? item.message
          : undefined,
    }));

  return out.length > 0 ? out : [];
}

function getErrorDetail(
  detail: unknown,
  status: number
): string {
  if (typeof detail === 'string' && detail) return detail;

  if (
    detail &&
    typeof detail === 'object' &&
    typeof (detail as Record<string, unknown>).message === 'string'
  ) {
    return (detail as Record<string, string>).message;
  }

  return `Analysis failed with status ${status}.`;
}

function getRecommendation(
  riskScore: number,
  prediction: string
): string {
  if (prediction === 'INCONCLUSIVE') {
    return 'The analysis was inconclusive. Treat this media as unverified and confirm its authenticity with the original source before relying on it.';
  }

  if (
    prediction === 'LIKELY_MANIPULATED' ||
    prediction === 'LIKELY_AI_GENERATED' ||
    riskScore >= 70
  ) {
    return 'High manipulation risk detected. Do not make financial, security, identity-related, or other important decisions based solely on this media. Verify the source through an independent channel.';
  }

  if (riskScore >= 30) {
    return 'Some characteristics warrant additional verification. Exercise caution before sharing or acting on information contained in this media and verify the original source.';
  }

  return 'Low manipulation risk detected. No strong indicators of AI-generated or manipulated content were found. For important decisions, always verify information through trusted sources.';
}

// Provider responses are untrusted input: only surface an explanation whose
// shape we fully validate, so a malformed payload degrades to no panel at all
// instead of breaking the results view.
function parseExplanation(raw: unknown): AnalysisExplanation | undefined {
  if (!raw || typeof raw !== 'object') return undefined;

  const data = raw as Record<string, unknown>;

  if (
    typeof data.summary !== 'string' ||
    !data.summary ||
    !Array.isArray(data.reasons) ||
    !Array.isArray(data.contributions)
  ) {
    return undefined;
  }

  const contributions = (data.contributions as any[])
    .filter(
      (item) =>
        item &&
        typeof item.name === 'string' &&
        typeof item.value === 'string' &&
        isUsableScore(item.score) &&
        isUsableScore(item.points)
    )
    .map((item) => ({
      name: item.name,
      value: item.value,
      score: clamp(item.score, 0, 100),
      points: clamp(item.points, 0, 100),
    }));

  return {
    summary: data.summary,

    reasons: (data.reasons as unknown[]).filter(
      (reason): reason is string => typeof reason === 'string' && !!reason
    ),

    contributions,

    caveat:
      typeof data.caveat === 'string' && data.caveat
      ? data.caveat
      : undefined,
  };
}

function getSignalDescription(
  signal: {
    name: string;
    value: string;
    score?: number;
  },
  provider: string
): string {
  const scoreText =
  isUsableScore(signal.score)
  ? ` Detection score: ${signal.score.toFixed(1)}%.`
  : '';

  if (provider === 'Reality Defender') {
    return `Detection model verdict: ${signal.value}.${scoreText}`;
  }

  return `${signal.value}.${scoreText}`;
}

export async function analyzeMedia(
  file: File
): Promise<AnalysisResult> {
  // User-side timing starts the moment the request begins; the caller
  // measures the full user-visible span from the Analyze click.
  const tRequestStart = performance.now();

  const formData = new FormData();
  formData.append('file', file);

  const controller = new AbortController();
  const timeoutId = setTimeout(
    () => controller.abort(),
    REQUEST_TIMEOUT_MS
  );

  let response: Response;

  try {
    response = await fetch(BACKEND_URL, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(
        'The analysis took too long and was cancelled. Please try again with a smaller file.'
      );
    }

    console.error('Network error:', error);

    throw new Error(
      'Unable to reach the DeepShield analysis server. Please ensure the backend is running and VITE_BACKEND_URL is configured.'
    );
  } finally {
    clearTimeout(timeoutId);
  }

  const tResponse = performance.now();

  let data: any;

  try {
    data = await response.json();
  } catch {
    throw new Error(
      'The analysis server returned an invalid response.'
    );
  }

  const tParsed = performance.now();

  if (!response.ok) {
    if (response.status === 413) {
      throw new Error(data.detail || 'The file is too large to analyze.');
    }

    throw new Error(
      // Sanitized 424 provider errors carry a structured detail object
      // ({provider, file, message}); string details (413) pass through
      // untouched. Anything malformed falls back to a generic message.
      getErrorDetail(data.detail, response.status)
    );
  }

  if (!data.success) {
    throw new Error(
      data.detail ||
      'The analysis could not be completed.'
    );
  }

  const fileSizeMB = (
    file.size / (1024 * 1024)
  ).toFixed(2);

  const format =
  file.name
  .split('.')
  .pop()
  ?.toUpperCase() ||
  'UNKNOWN';

  // Clamp and validate everything before it reaches the UI.
  const riskScore = clamp(toFiniteNumber(data.risk_score, 0), 0, 100);

  const timings = {
    // From request start until response headers/body arrival.
    requestMs: Math.round(tResponse - tRequestStart),
    // JSON body parsing only.
    parseMs: Math.round(tParsed - tResponse),
    // Full run of this client-side function.
    clientTotalMs: Math.round(performance.now() - tRequestStart),
  };

  console.info(
    `[DeepShield timing] request=${timings.requestMs}ms ` +
    `parse=${timings.parseMs}ms clientTotal=${timings.clientTotalMs}ms` +
    ` server=${toFiniteNumber(data.analysis_time, 0).toFixed(2)}s` +
    (data.request_id ? ` reqId=${data.request_id}` : '')
  );

  const riskLevel =
  data.risk_level === 'LOW' ||
  data.risk_level === 'MEDIUM' ||
  data.risk_level === 'HIGH'
  ? data.risk_level
  : riskScore < 30
  ? 'LOW'
  : riskScore < 70
  ? 'MEDIUM'
  : 'HIGH';

  return {
    riskScore,

    riskLevel,

    prediction:
    typeof data.prediction === 'string' && data.prediction
    ? data.prediction
    : 'INCONCLUSIVE',

    confidence: `${clamp(
      toFiniteNumber(data.confidence, 0),
      0,
      100
    ).toFixed(1)}%`,

    // Server-side processing time, as reported by the backend. The caller
    // (App) stamps `totalTime` from the analysis click so the UI can
    // distinguish server work from the full user-visible wait.
    analysisTime: toFiniteNumber(data.analysis_time, 0),

    mediaType:
    typeof data.media_type === 'string' && data.media_type
    ? data.media_type
    : 'unknown',

    format,

    fileSize: `${fileSizeMB} MB`,

    signals: (data.signals || []).map(
      (signal: any) => ({
        name: signal.name || 'Detection Signal',

        value:
        isUsableScore(signal.score)
        ? `${signal.value || 'UNKNOWN'} • ${signal.score.toFixed(1)}%`
        : signal.value || 'NO SCORE',

        description: getSignalDescription(
          signal,
          data.provider || ''
        ),
      })
    ),

    explanation: parseExplanation(data.explanation),

    providers: normalizeProviders(data.providers),

    recommendation: getRecommendation(
      riskScore,
      typeof data.prediction === 'string' && data.prediction
      ? data.prediction
      : 'INCONCLUSIVE'
    ),
  };
}
