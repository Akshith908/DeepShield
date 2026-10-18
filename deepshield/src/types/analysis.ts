export interface AnalysisSignal {
  name: string;
  value: string;
  description: string;
}

// Per-provider outcome ledger. Present on multi-provider or partial-failure
// results; single-provider results may also carry a one-entry ledger.
export interface ProviderOutcome {
  provider: string;
  status: 'OK' | 'FAILED' | 'UNAVAILABLE';
  prediction?: string;
  riskScore?: number;
  message?: string;
}

// One detector's share of the final risk score, allocated proportionally to
// its evidence score so all points sum to riskScore (within rounding).
export interface ExplanationContribution {
  name: string;
  value: string;
  score: number;
  points: number;
}

export interface AnalysisExplanation {
  summary: string;
  reasons: string[];
  contributions: ExplanationContribution[];
  caveat?: string;
}

export interface AnalysisResult {
  riskScore: number;

  riskLevel: 'LOW' | 'MEDIUM' | 'HIGH';

  prediction: string;

  confidence: string;

  // Server-side processing time (backend `analysis_time`).
  analysisTime: number;

  // Full user-visible duration: from the moment the Analyze action starts
  // until the result state is committed, measured client-side. Includes
  // upload transit, backend wait, parsing, and state handling. The final
  // paint after the state commit is not part of this measurement.
  totalTime?: number;

  mediaType: string;

  signals: AnalysisSignal[];

  providers?: ProviderOutcome[];

  explanation?: AnalysisExplanation;

  recommendation: string;

  fileSize?: string;

  format?: string;

  duration?: number;
}
