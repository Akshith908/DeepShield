export interface AnalysisSignal {
  name: string;
  value: string;
  description: string;
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

  mediaType: string;

  signals: AnalysisSignal[];

  explanation?: AnalysisExplanation;

  recommendation: string;

  fileSize?: string;

  format?: string;

  duration?: number;
}
